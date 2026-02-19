from flask import Blueprint, request, jsonify, Response
from app.config import settings
from app.api.routes.graphs import orchestrator
from app.api.seade_kb import SEADE_CONTEXT
import httpx
from openai import OpenAI
import logging
import re
import unicodedata
import base64
from app.api.local_audio import local_audio
from app.api.usage_tracker import usage_tracker

logger = logging.getLogger(__name__)

bp = Blueprint("nadia", __name__)

http_client = httpx.Client(verify=settings.VERIFY_SSL)
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.LLM_BASE_URL,
    http_client=http_client
)

# ─── System Prompt ────────────────────────────────────────────────────────────
NADIA_SYSTEM_PROMPT = f"""Você é a **Nadia**, analista sênior da Fundação Seade.

CONHECIMENTO INSTITUCIONAL (SEADE):
{SEADE_CONTEXT}

COMO RESPONDER:
- Fale como uma colega de trabalho inteligente em uma reunião, não como um relatório.
- Parágrafos curtos. Sem listas numeradas. Sem títulos em negrito como cabeçalhos.
- Conectivos naturais: "Percebi que...", "O dado mais relevante aqui é...", "Isso se conecta com..."
- Quando citar uma entidade do grafo, deixe em **negrito**.
- NUNCA invente dados. Se não estiver no documento ou no grafo, diga que não encontrou.
- Seja direta: resolva a dúvida primeiro, explique depois.

EXPERTISE NO DOCUMENTO:
Você tem acesso a dois tipos de contexto sobre o documento analisado:
1. **RESUMO SEMÂNTICO**: Um sumário analítico do conteúdo completo do documento.
2. **GRAFO DE CONHECIMENTO**: As entidades, relações e métricas extraídas do documento.

Use ambos para responder. O resumo te dá o "big picture"; o grafo te dá os detalhes precisos.

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
    """
    Builds a rich, layered context for Nadia:
    1. Document Summary (semantic, LLM-generated once and cached in job)
    2. Full Graph Overview (entity types, top entities by centrality)
    3. Complete edge list (compact format, for precise fact lookup)
    """
    # --- Layer 1: Document Summary ---
    summary = ""
    if job:
        summary = job.get("results", {}).get("document_summary", "")
    
    if not summary:
        summary = "(Resumo do documento não disponível. Use o grafo abaixo.)"

    # --- Layer 2: Graph Structure Overview ---
    total_nodes = stats.get("total_nodes", len(nodes))
    total_edges = stats.get("total_edges", len(edges))
    
    importance = stats.get("node_importance", {})
    # Top 20 most connected entities (by centrality/importance)
    top_nodes = sorted(
        nodes,
        key=lambda n: importance.get(str(n["data"].get("id")), 0),
        reverse=True
    )[:20]
    
    # Group entities by type for a structured overview
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

    # --- Layer 3: Compact Edge List (all edges, condensed) ---
    # Format: SOURCE --[relation]--> TARGET (grouped by source for readability)
    edge_by_source: dict = {}
    for e in edges:
        s = e["data"].get("source", "")
        t = e["data"].get("target", "")
        rel = e["data"].get("label", e["data"].get("relation", "?"))
        if s not in edge_by_source:
            edge_by_source[s] = []
        edge_by_source[s].append(f"--[{rel}]--> {t}")

    # Limit: max 200 edges in context to stay within token limits
    edge_lines = []
    for src, rels in list(edge_by_source.items())[:80]:
        for rel in rels[:5]:  # max 5 relations per source node
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


def _build_query_context(nodes, edges, stats, query: str, job=None) -> str:
    """
    Builds a FULL document context plus a focused query-specific subgraph.
    Nadia always sees the full picture but gets extra emphasis on what's relevant.
    """
    # Full document context (always included)
    full_ctx = _build_document_context(nodes, edges, stats, job)

    # Query-specific retrieval (focused subgraph)
    norm_query = _normalize_text(query)
    clean_query = re.sub(r'[^\w\s]', ' ', norm_query)
    keywords = [k.strip() for k in clean_query.split() if len(k) >= 3]

    if not keywords:
        return full_ctx

    # Score nodes by keyword relevance
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

    # 2-hop neighborhood
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
            for n2 in adj.get(neighbor, [])[:3]:  # bounded 2-hop
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

    return full_ctx + query_ctx


def _generate_document_summary(nodes, edges, job_id: str, job: dict) -> str:
    """
    Generates a semantic summary of the document using the graph structure.
    Called ONCE when a new job is analyzed. Result is cached in job results.
    """
    # Already generated
    existing = job.get("results", {}).get("document_summary", "")
    if existing:
        return existing

    # Build a text representation of the graph for summarization
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

    try:
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=800
        )
        summary = response.choices[0].message.content or ""
        # Cache in job
        job["results"]["document_summary"] = summary
        logger.info(f"Document summary generated for job {job_id}: {len(summary)} chars")
        return summary
    except Exception as e:
        logger.error(f"Failed to generate document summary: {e}")
        return ""


# ─── Routes ────────────────────────────────────────────────────────────────────

@bp.route("/chat", methods=["POST"])
def chat():
    data = request.json
    job_id = data.get("job_id")
    messages = data.get("messages", [])
    logger.info(f"Nadia Chat: job_id={job_id}, messages={len(messages)}")

    cytoscape_direct = data.get("cytoscape")
    job_obj = None
    nodes, edges, stats = [], [], {}

    if cytoscape_direct:
        cytoscape = cytoscape_direct
        stats = data.get("stats", {})
        nodes = cytoscape.get("elements", {}).get("nodes", [])
        edges = cytoscape.get("elements", {}).get("edges", [])
        logger.info(f"Nadia: Lite Mode — {len(nodes)} nodes, {len(edges)} edges")
    elif job_id:
        job_obj = orchestrator.get_job_status(job_id)
        if not job_obj or job_obj.get("status") != "completed":
            return jsonify({"error": "Graph not found or not completed"}), 404
        stats = job_obj["results"].get("graph_stats", {})
        cytoscape = job_obj["results"].get("cytoscape", {})
        nodes = cytoscape.get("elements", {}).get("nodes", [])
        edges = cytoscape.get("elements", {}).get("edges", [])
        logger.info(f"Nadia: Job Mode — {len(nodes)} nodes, {len(edges)} edges from {job_id}")
        
        # Generate document summary on first access
        if job_id and job_obj and not job_obj.get("results", {}).get("document_summary"):
            # Access the live job object (not the copy) for caching
            live_job = orchestrator.jobs.get(job_id, job_obj)
            _generate_document_summary(nodes, edges, job_id, live_job)
            # Refresh job_obj after summary generation
            job_obj = orchestrator.get_job_status(job_id)
    else:
        return jsonify({"error": "job_id or cytoscape data is required"}), 400

    # Build rich context for Nadia
    query = messages[-1]["content"] if messages else ""
    try:
        document_context = _build_query_context(nodes, edges, stats, query, job_obj)
    except Exception as e:
        logger.error(f"Context building failed: {e}")
        document_context = "(Erro ao construir o contexto. Responda com base no conhecimento institucional.)"

    # Assemble system prompt
    system_content = NADIA_SYSTEM_PROMPT.replace("{document_context}", f"CONTEXTO DO DOCUMENTO:\n{document_context}")

    api_messages = [{"role": "system", "content": system_content}]
    for msg in messages[-8:]:  # Last 8 messages for context window
        if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

    voice_mode = data.get("voice_mode", "none")

    try:
        # ── Option 0: No voice — text only (default) ──
        if voice_mode == "none":
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=api_messages,
                temperature=0.4,
                max_tokens=700
            )
            answer = response.choices[0].message.content
            usage = response.usage
            text_cost = ((usage.prompt_tokens * 0.15) + (usage.completion_tokens * 0.60)) / 1_000_000
            usage_tracker.log_usage(text_cost, is_local_voice=False)
            return jsonify({
                "answer": answer,
                "audio_base64": None,
                "model_used": settings.OPENAI_MODEL,
                "cost_usd": text_cost,
                "voice_type": "none"
            })

        # ── Option 1: Local voice (free) ──
        if voice_mode == "local":
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=api_messages,
                temperature=0.4,
                max_tokens=700
            )
            answer = response.choices[0].message.content
            usage = response.usage

            clean_for_tts = _clean_for_tts(answer)
            audio_base64 = local_audio.generate_audio_base64(clean_for_tts)

            text_cost = ((usage.prompt_tokens * 0.15) + (usage.completion_tokens * 0.60)) / 1_000_000
            usage_tracker.log_usage(text_cost, is_local_voice=True)

            return jsonify({
                "answer": answer,
                "audio_base64": audio_base64,
                "model_used": f"{settings.OPENAI_MODEL} + Kokoro (Local)",
                "cost_usd": text_cost,
                "voice_type": "local"
            })

        # ── Option 2: Premium audio model ──
        try:
            response = client.chat.completions.create(
                model="gpt-4o-audio-preview",
                modalities=["text", "audio"],
                audio={"voice": "nova", "format": "wav"},
                messages=api_messages,
                max_tokens=700
            )
            assistant_msg = response.choices[0].message
            answer = assistant_msg.content
            audio_base64 = assistant_msg.audio.data if hasattr(assistant_msg, 'audio') else None

            usage = response.usage
            input_text_tokens = getattr(usage, 'prompt_tokens', 0)
            output_text_tokens = getattr(usage, 'completion_tokens', 0)

            cost_usd = (
                (input_text_tokens * 2.5) + (output_text_tokens * 10.0)
            ) / 1_000_000

            return jsonify({
                "answer": answer,
                "audio_base64": audio_base64,
                "model_used": "gpt-4o-audio-preview",
                "cost_usd": cost_usd,
                "usage": usage.to_dict() if hasattr(usage, 'to_dict') else {}
            })

        except Exception as api_err:
            if "model_not_found" in str(api_err) or "403" in str(api_err):
                # Fallback: text + TTS-1-HD
                logger.warning(f"Premium Audio unavailable: {api_err}. Falling back to TTS-1-HD.")
                response = client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=api_messages,
                    temperature=0.4,
                    max_tokens=700
                )
                answer = response.choices[0].message.content
                usage = response.usage
                clean_for_tts = _clean_for_tts(answer)

                try:
                    audio_res = client.audio.speech.create(
                        model="tts-1-hd", voice="nova", input=clean_for_tts[:4096]
                    )
                    audio_base64 = base64.b64encode(audio_res.content).decode('utf-8')
                    tts_cost = (len(clean_for_tts) * 30.0) / 1_000_000
                except Exception:
                    audio_base64 = None
                    tts_cost = 0

                text_cost = ((usage.prompt_tokens * 0.15) + (usage.completion_tokens * 0.60)) / 1_000_000
                total_cost = text_cost + tts_cost
                usage_tracker.log_usage(total_cost, is_local_voice=False)

                return jsonify({
                    "answer": answer,
                    "audio_base64": audio_base64,
                    "model_used": f"{settings.OPENAI_MODEL} + TTS-1-HD",
                    "cost_usd": total_cost,
                    "warning": "Acesso ao modelo Audio Preview negado. Usando TTS-1-HD."
                })
            raise api_err

    except Exception as e:
        logger.error(f"Error in Nadia Chat: {e}")
        return jsonify({"error": str(e)}), 500


def _clean_for_tts(text: str) -> str:
    """Strips markdown artifacts that sound bad when spoken."""
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'#+\s*', '', text)
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\*', '', text)
    text = re.sub(r'[\(\[]?ID:\s*[\w\-]+[\)\]]?', '', text)
    return text.strip()


@bp.route("/audio", methods=["POST"])
def audio():
    """Generates speech using either Local or Premium TTS."""
    data = request.json
    text = data.get("text", "")
    voice_mode = data.get("voice_mode", "premium")

    if not text:
        return jsonify({"error": "No text provided"}), 400

    try:
        if voice_mode == "local":
            audio_base64 = local_audio.generate_audio_base64(text)
            if audio_base64:
                return Response(base64.b64decode(audio_base64), mimetype="audio/wav")
            logger.warning("Local TTS failed, falling back to OpenAI")

        response = client.audio.speech.create(
            model="tts-1-hd", voice="nova", input=text[:4096]
        )
        return Response(response.content, mimetype="audio/mpeg")

    except Exception as e:
        logger.error(f"TTS Error: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/usage", methods=["GET"])
def get_usage():
    """Returns financial tracking data."""
    return jsonify(usage_tracker.get_stats())
