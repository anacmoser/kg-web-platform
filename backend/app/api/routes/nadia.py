from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import uuid
import networkx as nx
import httpx
from openai import OpenAI
import logging
import re
import unicodedata
import numpy as np
import base64
import io

from app.config import settings
from app.api.seade_kb import SEADE_CONTEXT
from app.pipeline.orchestrator import orchestrator
from app.utils import retry_with_exponential_backoff

# For structural embeddings
from app.pipeline.stages.structural_extractor import FaissIndex
import chromadb

# These were missing imports in the Flask version or part of the larger app
try:
    from app.api.usage_tracker import usage_tracker
except ImportError:
    class DummyUsageTracker:
        def log_usage(self, *args, **kwargs): pass
        def get_stats(self): return {}
    usage_tracker = DummyUsageTracker()

try:
    from app.api.local_audio import local_audio
except ImportError:
    class DummyLocalAudio:
        def generate_audio_base64(self, text): return None
    local_audio = DummyLocalAudio()

logger = logging.getLogger(__name__)

router = APIRouter()

http_client = httpx.Client(verify=settings.VERIFY_SSL)
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.LLM_BASE_URL,
    http_client=http_client
)

# ─── Schemas ──────────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    job_id: Optional[str] = None
    messages: List[ChatMessage]
    cytoscape: Optional[Dict[str, Any]] = None
    stats: Optional[Dict[str, Any]] = {}
    voice_mode: str = "none"

class AudioRequest(BaseModel):
    text: str
    voice_mode: str = "premium"

# ─── System Prompt ────────────────────────────────────────────────────────────
NADIA_SYSTEM_PROMPT = f"""Você é a **Nadia**, analista sênior da Fundação Seade.

CONHECIMENTO INSTITUCIONAL (SEADE):
{SEADE_CONTEXT}

DIRETRIZES DE PERSONALIDADE E COMPORTAMENTO (MUITO IMPORTANTE):
1. **Seja Extremamente Concisa:** Suas respostas devem ser curtas, diretas e muito dinâmicas (idealmente 1 ou 2 parágrafos curtos).
2. **Tom de Voz:** Fale como uma colega inteligente em uma chamada rápida. Seja coloquial, envolvente e dispensando formalidades. Nada de "prezado" ou relatórios mecanicistas.
3. **Gatilhos Conversacionais:** Comece de forma natural. Ex: "Olha só, pelo que vi...", "O ponto principal aqui é...", "Que interessante, percebi que..."
4. **Estrutura Proibida:** NUNCA use marcadores, bullet points, listas numeradas ou subtítulos de seções. Escreva de forma fluida (como mensagem de chat corporativo).
5. **Destaques:** Se for citar uma métrica ou a entidade mais importante, você pode usar **negrito** uma ou duas vezes, mas não exagere.
6. **Integridade:** Só fale do que está no grafo ou resumo. Se a pergunta fugir dos dados, diga tranquilamente algo como: "Olha, vasculhei os dados mas não encontrei referência a isso aqui."
7. **Direta e Reta:** Responda à dúvida principal já na primeira frase.

EXPERTISE NO DOCUMENTO:
Você tem duas fontes exclusivas sobre o documento em que estamos trabalhando:
1. **RESUMO SEMÂNTICO**: A estrutura geral da narrativa.
2. **GRAFO DE CONHECIMENTO**: Os nós reais (entidades) e conexões precisas.

Leia o contexto abaixo, absorva a pergunta e mande uma resposta genial, rápida e natural:

{{document_context}}
"""

# ─── GraphRAG Core ─────────────────────────────────────────────────────────────

def _normalize_text(text: str) -> str:
    if not text:
        return ""
    return "".join(
        c for c in unicodedata.normalize('NFD', text.lower())
        if unicodedata.category(c) != 'Mn'
    )


def _build_document_context(nodes, edges, stats, job=None) -> str:
    summary = ""
    if job:
        summary = job.get("results", {}).get("document_summary", "")
    
    if not summary:
        summary = "(Resumo do documento não disponível. Use o grafo abaixo.)"

    total_nodes = stats.get("total_nodes", len(nodes))
    total_edges = stats.get("total_edges", len(edges))
    
    importance = stats.get("node_importance", {})
    top_nodes = sorted(
        nodes,
        key=lambda n: importance.get(str(n["data"].get("id")), 0),
        reverse=True
    )[:20]
    
    type_groups: dict = {}
    for n in nodes:
        ntype = n["data"].get("type", "DESCONHECIDO")
        label = n["data"].get("label", n["data"].get("id", ""))
        if ntype not in type_groups:
            type_groups[ntype] = []
        type_groups[ntype].append(label)

    entities_by_type = "\n".join([
        f"  {ntype} ({len(labels)}): {', '.join(labels[:8])}{'...' if len(labels) > 8 else ''}"
        for ntype, labels in sorted(type_groups.items(), key=lambda x: -len(x[1]))
    ])

    top_entities_str = "\n".join([
        f"  - {n['data'].get('label', n['data'].get('id'))} [{n['data'].get('type', '?')}]"
        for n in top_nodes
    ])

    edge_by_source: dict = {}
    for e in edges:
        s = e["data"].get("source", "")
        t = e["data"].get("target", "")
        rel = e["data"].get("label", e["data"].get("relation", "?"))
        if s not in edge_by_source:
            edge_by_source[s] = []
        edge_by_source[s].append(f"--[{rel}]--> {t}")

    edge_lines = []
    for src, rels in list(edge_by_source.items())[:80]:
        for rel in rels[:5]:
            edge_lines.append(f"  {src} {rel}")
    
    edge_str = "\n".join(edge_lines) if edge_lines else "  (Nenhuma relação encontrada)"

    return f"""
─── RESUMO SEMÂNTICO DO DOCUMENTO ───
{summary}

─── VISÃO GERAL DO GRAFO ({total_nodes} entidades, {total_edges} relações) ───
Entidades por tipo:
{entities_by_type}

Entidades mais conectadas (hubs):
{top_entities_str}

─── TODAS AS RELAÇÕES EXTRAÍDAS ───
{edge_str}
"""


@retry_with_exponential_backoff()
def _get_query_embedding(query: str, client: OpenAI) -> np.ndarray:
    resp = client.embeddings.create(model="text-embedding-3-small", input=query[:8000])
    return np.array(resp.data[0].embedding, dtype=np.float32)

def _get_structural_context(query: str, client: OpenAI) -> str:
    if not FaissIndex.exists():
        return ""
        
    try:
        import faiss
        
        faiss_idx = FaissIndex.load()
        if len(faiss_idx.id_map) == 0:
            return ""
            
        q_vec = _get_query_embedding(query, client).reshape(1, -1)
        faiss.normalize_L2(q_vec)
        
        k = min(5, len(faiss_idx.id_map))
        D, I = faiss_idx.index.search(q_vec, k)
        
        top_ids = []
        for i in I[0]:
            if i != -1:
                node_id = faiss_idx.id_map[i]
                if node_id not in top_ids:
                    top_ids.append(node_id)

        if not top_ids:
            return ""
            
        chroma_client = chromadb.PersistentClient(path=str(settings.CHROMA_PATH))
        collection = chroma_client.get_collection(name=settings.COLLECTION_NAME)
        
        results = collection.get(ids=top_ids)
        documents = results.get("documents", [])
        metadatas = results.get("metadatas", [])
        
        if not documents:
            return ""
            
        chunks_str = []
        for doc, meta in zip(documents, metadatas):
            doc_label = meta.get("label", "Fonte desconhecida")
            chunks_str.append(f"[{doc_label}]\n{doc}")
            
        return "\n\n".join(chunks_str)
        
    except Exception as e:
        logger.warning(f"Erro ao buscar contexto estrutural: {e}")
        return ""

def _get_semantic_context(query: str, client: OpenAI) -> str:
    """Busca entidades e conceitos relacionados na coleção semântica."""
    try:
        chroma_client = chromadb.PersistentClient(path=str(settings.CHROMA_PATH))
        # Get semantic collection
        collection = chroma_client.get_or_create_collection(name=settings.COLLECTION_SEMANTIC_NAME)
        
        if collection.count() == 0:
            return ""
            
        # Search by query text (let Chroma use its default embedding function)
        results = collection.query(
            query_texts=[query],
            n_results=4
        )
        
        docs = results.get("documents", [[]])[0]
        if not docs:
            return ""
            
        context_blocks = []
        for d in docs:
            context_blocks.append(f"── Conceito Relacionado ──\n{d}")
            
        return "\n\n".join(context_blocks)
        
    except Exception as e:
        logger.warning(f"Erro ao buscar contexto semântico: {e}")
        return ""

def _build_query_context(nodes, edges, stats, query: str, job=None, client=None) -> str:
    full_ctx = _build_document_context(nodes, edges, stats, job)

    norm_query = _normalize_text(query)
    clean_query = re.sub(r'[^\w\s]', ' ', norm_query)
    keywords = [k.strip() for k in clean_query.split() if len(k) >= 3]

    if not keywords:
        return full_ctx

    scored = []
    for n in nodes:
        data = n.get("data", {})
        nid = _normalize_text(str(data.get("id", "")))
        label = _normalize_text(str(data.get("label", "")))
        ntype = _normalize_text(str(data.get("type", "")))

        score = 0
        for kw in keywords:
            if kw == label or kw == nid:
                score += 15
            elif kw in label:
                score += 7
            elif kw in ntype:
                score += 3
        if score > 0:
            scored.append((data.get("id"), score))

    scored.sort(key=lambda x: x[1], reverse=True)
    seed_ids = {s[0] for s in scored[:20]}

    adj: dict = {}
    for e in edges:
        d = e.get("data", {})
        s_n, t_n = d.get("source"), d.get("target")
        if s_n and t_n:
            adj.setdefault(s_n, []).append(t_n)
            adj.setdefault(t_n, []).append(s_n)

    expanded = set(seed_ids)
    for sid in seed_ids:
        for neighbor in adj.get(sid, []):
            expanded.add(neighbor)
            for n2 in adj.get(neighbor, [])[:3]:
                expanded.add(n2)

    focused_nodes = [n for n in nodes if n["data"].get("id") in expanded]
    focused_edges = [
        e for e in edges
        if e["data"].get("source") in expanded and e["data"].get("target") in expanded
    ]

    if not focused_nodes:
        return full_ctx

    focused_node_str = "\n".join([
        f"  - {n['data'].get('label', n['data'].get('id'))} [{n['data'].get('type', '?')}]"
        for n in focused_nodes[:40]
    ])
    focused_edge_str = "\n".join([
        f"  {e['data'].get('source')} --[{e['data'].get('label', e['data'].get('relation', '?'))}]--> {e['data'].get('target')}"
        for e in focused_edges[:60]
    ])

    query_ctx = f"""
─── CONTEXTO FOCADO NA PERGUNTA ("{query[:80]}") ───
Entidades relevantes encontradas:
{focused_node_str}

Relações relevantes:
{focused_edge_str}
"""

    if client and query:
        struct_ctx = _get_structural_context(query, client)
        if struct_ctx:
            query_ctx += f"\n\n─── CONTEXTO TEXTUAL/VISUAL DO DOCUMENTO (CHUNKS) ───\n{struct_ctx}\n"

        # Adiciona contexto semântico (entidades)
        sem_ctx = _get_semantic_context(query, client)
        if sem_ctx:
            query_ctx += f"\n\n─── CONTEXTO SEMÂNTICO (ENTIDADES E CONCEITOS) ───\n{sem_ctx}\n"

    return full_ctx + query_ctx


def _generate_document_summary(nodes, edges, job_id: str, job: dict) -> str:
    existing = job.get("results", {}).get("document_summary", "")
    if existing:
        return existing

    entity_types = {}
    for n in nodes:
        ntype = n["data"].get("type", "?")
        label = n["data"].get("label", "")
        entity_types.setdefault(ntype, []).append(label)

    entity_overview = "\n".join([
        f"- {t}: {', '.join(labels[:10])}" for t, labels in entity_types.items()
    ])

    edge_sample = "\n".join([
        f"- {e['data'].get('source')} --[{e['data'].get('label', e['data'].get('relation', '?'))}]--> {e['data'].get('target')}"
        for e in edges[:100]
    ])

    prompt = f"""Você é um analista que acabou de processar um documento e extraiu um Grafo de Conhecimento.
Com base nas entidades e relações abaixo, escreva um RESUMO ANALÍTICO do documento em português.

O resumo deve:
- Explicar o TEMA PRINCIPAL do documento (1 parágrafo)
- Identificar as entidades mais importantes e seus papéis (2-3 parágrafos)
- Destacar as relações e descobertas mais relevantes (2 parágrafos)
- Total: no máximo 5 parágrafos, linguagem técnica mas acessível.

ENTIDADES POR TIPO:
{entity_overview}

AMOSTRA DE RELAÇÕES ({len(edges)} no total):
{edge_sample}

Escreva o resumo analítico:"""

    @retry_with_exponential_backoff()
    def _call_llm_summary(prompt, model):
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800
        )

    try:
        response = _call_llm_summary(prompt, settings.OPENAI_MODEL)
        summary = response.choices[0].message.content or ""
        job["results"]["document_summary"] = summary
        logger.info(f"Document summary generated for job {job_id}: {len(summary)} chars")
        return summary
    except Exception as e:
        logger.error(f"Failed to generate document summary: {e}")
        return ""

# ─── Routes ────────────────────────────────────────────────────────────────────

@router.post("/chat")
async def chat(req: ChatRequest):
    job_id = req.job_id
    messages = req.messages
    logger.info(f"Nadia Chat: job_id={job_id}, messages={len(messages)}")

    cytoscape_direct = req.cytoscape
    job_obj = None
    nodes, edges, stats = [], [], {}

    if cytoscape_direct:
        cytoscape = cytoscape_direct
        stats = req.stats
        nodes = cytoscape.get("elements", {}).get("nodes", [])
        edges = cytoscape.get("elements", {}).get("edges", [])
        logger.info(f"Nadia: Lite Mode — {len(nodes)} nodes, {len(edges)} edges")
    elif job_id:
        job_obj = orchestrator.get_job_status(job_id)
        if not job_obj or job_obj.get("status") != "completed":
            raise HTTPException(status_code=404, detail="Graph not found or not completed")
        stats = job_obj["results"].get("graph_stats", {})
        cytoscape = job_obj["results"].get("cytoscape", {})
        nodes = cytoscape.get("elements", {}).get("nodes", [])
        edges = cytoscape.get("elements", {}).get("edges", [])
        logger.info(f"Nadia: Job Mode — {len(nodes)} nodes, {len(edges)} edges from {job_id}")
        
        if job_id and job_obj and not job_obj.get("results", {}).get("document_summary"):
            live_job = orchestrator.jobs.get(job_id, job_obj)
            _generate_document_summary(nodes, edges, job_id, live_job)
            job_obj = orchestrator.get_job_status(job_id)
    else:
        raise HTTPException(status_code=400, detail="job_id or cytoscape data is required")

    query = messages[-1].content if messages else ""


    # Use the new NadiaAgent for agentic reasoning and tool use
    # We use job_id as thread_id to maintain session memory
    thread_id = job_id or "default_session"
    
    try:
        # Initialize the agent
        from app.api.nadia_agent import Nadia
        nadia_instance = Nadia(client)
        answer = await nadia_instance.ask(query, thread_id=thread_id)
    except Exception as e:
        logger.error(f"Nadia failed: {e}. Falling back to simple context.")
        # Fallback to simple context building if agent fails
        try:
            document_context = _build_query_context(nodes, edges, stats, query, job_obj, client)
        except Exception as e_ctx:
            logger.error(f"Context building failed: {e_ctx}")
            document_context = "(Erro ao construir o contexto.)"

        system_content = NADIA_SYSTEM_PROMPT.replace("{document_context}", f"CONTEXTO DO DOCUMENTO:\n{document_context}")
        api_messages = [{"role": "system", "content": system_content}]
        for msg in messages[-8:]:
            api_messages.append({"role": msg.role, "content": msg.content})

        @retry_with_exponential_backoff()
        def _call_llm_chat(msgs, model, temperature=0.4, max_tokens=700):
            return client.chat.completions.create(model=model, messages=msgs, temperature=temperature, max_tokens=max_tokens)
        
        fallback_res = _call_llm_chat(api_messages, settings.OPENAI_MODEL)
        answer = fallback_res.choices[0].message.content or ""

    # --- Audio and Voice Handling ---
    voice_mode = req.voice_mode
    audio_base64 = None
    model_info = f"{settings.OPENAI_MODEL} (Agentic)"
    total_cost = 0.0

    # Pricing estimation (rough)
    pricing = settings.MODEL_PRICING.get(settings.OPENAI_MODEL, (0.15, 0.60)) # Default to 4o-mini-like
    # We don't have usage directly from agent.ask yet, so we estimate or log later
    text_cost = 0.001 # Placeholder for agentic cost

    if voice_mode == "local":
        clean_for_tts = _clean_for_tts(answer)
        audio_base64 = local_audio.generate_audio_base64(clean_for_tts)
        model_info += " + Kokoro (Local)"
        usage_tracker.log_usage(text_cost, is_local_voice=True)

    elif voice_mode == "none":
        usage_tracker.log_usage(text_cost, is_local_voice=False)

    else: # Default or "premium" falls back to tts-1-hd for text-based agent
        clean_for_tts = _clean_for_tts(answer)
        try:
            @retry_with_exponential_backoff()
            def _call_audio_speech(model, voice, input_text):
                return client.audio.speech.create(model=model, voice=voice, input=input_text)
            
            audio_res = _call_audio_speech("tts-1-hd", "nova", clean_for_tts[:4096])
            audio_base64 = base64.b64encode(audio_res.content).decode('utf-8')
            tts_cost = (len(clean_for_tts) * 30.0) / 1_000_000
            total_cost = text_cost + tts_cost
            model_info += " + TTS-1-HD"
            usage_tracker.log_usage(total_cost, is_local_voice=False)
        except Exception as tts_err:
            logger.warning(f"TTS failed: {tts_err}")
            audio_base64 = None
            usage_tracker.log_usage(text_cost, is_local_voice=False)

    return {
        "answer": answer,
        "audio_base64": audio_base64,
        "model_used": model_info,
        "cost_usd": total_cost or text_cost,
        "voice_type": voice_mode
    }


def _clean_for_tts(text: str) -> str:
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\*', '', text)
    text = re.sub(r'[\(\[]?ID:\s*[\w\-]+[\)\]]?', '', text)
    return text.strip()


@router.post("/audio")
async def audio(req: AudioRequest):
    text = req.text
    voice_mode = req.voice_mode

    if not text:
        raise HTTPException(status_code=400, detail="No text provided")

    try:
        @retry_with_exponential_backoff()
        def _call_audio_speech(model, voice, input_text):
            return client.audio.speech.create(
                model=model, voice=voice, input=input_text
            )
            
        if voice_mode == "local":
            audio_base64 = local_audio.generate_audio_base64(text)
            if audio_base64:
                return Response(content=base64.b64decode(audio_base64), media_type="audio/wav")
            logger.warning("Local TTS failed, falling back to OpenAI")

        response = _call_audio_speech("tts-1-hd", "nova", text[:4096])
        return Response(content=response.content, media_type="audio/mpeg")

    except Exception as e:
        logger.error(f"TTS Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/usage")
async def get_usage():
    return usage_tracker.get_stats()
