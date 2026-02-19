from flask import Blueprint, request, jsonify, Response
from app.config import settings
from app.api.routes.graphs import orchestrator # To get graph data
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

# Use httpx client for robust SSL handling on Windows
http_client = httpx.Client(verify=settings.VERIFY_SSL)
client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    base_url=settings.LLM_BASE_URL,
    http_client=http_client
)

NADIA_SYSTEM_PROMPT = f"""
VOCÊ É A **NADIA**, A ANALISTA SÊNIOR DA FUNDAÇÃO SEADE.

Sua missão é conversar com o usuário sobre o documento analisado, cruzando as informações extraídas com seu conhecimento institucional.

CONTEXTO INSTITUCIONAL (SEADE):
{SEADE_CONTEXT}

DIRETRIZES DE PERSONALIDADE (CONVERSA NATURAL E DIRETA):
1. **Pense em Diálogo, não em Documento**: Responda como uma pessoa em uma reunião de trabalho. Evite listas numeradas ("1. X, 2. Y") ou repetir títulos como "Análise de Dados: ...".
2. **Seja Fluida e Concisa**: Use parágrafos curtos e conectivos naturais ("Percebi também que...", "Isso se conecta com..."). Se a resposta for longa, quebre-a em pensamentos lógicos.
3. **Evite Repetições**: Não repita a pergunta do usuário. Vá direto ao ponto.
4. **Proatividade Inteligente**: Use o contexto do SEADE (acima) para enriquecer a resposta, mas apenas quando agregar valor real à análise do documento do usuário.
5. **Integração Visual**: Quando citar uma entidade do grafo, use seu nome em **negrito**.

ESTRUTURA DE RESPOSTA:
- **Resposta Direta**: Comece resolvendo a dúvida.
- **Contextualização**: Explique o "porquê" usando os dados do grafo.
- **Conclusão**: Um fechamento breve que convide à continuação da conversa.

CONTEXTO DO GRAFO (Sua Fonte Primária):
{{graph_context}}

Nadia, converse com o usuário. Seja profissional, mas natural.
"""

@bp.route("/chat", methods=["POST"])
def chat():
    data = request.json
    job_id = data.get("job_id")
    messages = data.get("messages", [])
    logger.info(f"Nadia Chat Start: job_id={job_id}, messages_count={len(messages)}")
    
    # PRIORITY: If cytoscape data is sent directly, use it (Lite Mode)
    # This takes precedence over job_id to ensure fresh data
    cytoscape_direct = data.get("cytoscape")
    
    nodes = []
    edges = []
    stats = {}

    if cytoscape_direct:
        # Lite/Manual mode with direct data
        cytoscape = cytoscape_direct
        stats = data.get("stats", {})
        nodes = cytoscape.get("elements", {}).get("nodes", [])
        edges = cytoscape.get("elements", {}).get("edges", [])
        logger.info(f"Nadia: Lite Mode (Direct Data) loaded {len(nodes)} nodes, {len(edges)} edges.")
    elif job_id:
        # Job mode - fetch from cache
        job = orchestrator.get_job_status(job_id)
        if not job or job.get("status") != "completed":
            logger.error(f"Job {job_id} not found or not completed.")
            return jsonify({"error": "Graph not found or not completed"}), 404
            
        stats = job["results"].get("graph_stats", {})
        cytoscape = job["results"].get("cytoscape", {})
        nodes = cytoscape.get("elements", {}).get("nodes", [])
        edges = cytoscape.get("elements", {}).get("edges", [])
        logger.info(f"Nadia: Job Mode loaded {len(nodes)} nodes, {len(edges)} edges from {job_id}")
    else:
        return jsonify({"error": "job_id or cytoscape data is required"}), 400
    
    # Initialize variables to prevent UnboundLocalError
    keywords = []
    relevant_ids = set()
    graph_context = ""

    try:
        # --- IMPROVED ADVANCED GRAPHRAG CONTEXT EXTRACTION ---
        def normalize_text(text: str) -> str:
            if not text: return ""
            return "".join(
                c for c in unicodedata.normalize('NFD', text.lower())
                if unicodedata.category(c) != 'Mn'
            )

        query = messages[-1]["content"] if messages else ""
        norm_query = normalize_text(query)
        clean_query = re.sub(r'[^\w\s]', ' ', norm_query)
        keywords = [k.strip() for k in clean_query.split() if len(k) >= 3]
        print(f"Keywords extracted: {keywords}")

        # --- EMERGENCY HEURISTIC & DATA PATCHING ---
        # 1. Patch FIPE vs SEADE anomaly
        # If user asks about SEADE, ensure we look for FIPE if it exists in the graph (data anomaly)
        if any(k in ["seade", "fundacao"] for k in keywords):
            keywords.append("fipe")
            keywords.append("instituto") 
            keywords.append("pesquisas")

        # 2. Heuristic for "Calculo" / "Como" / "Processo"
        # Force injection of calculation-related nodes
        heuristic_nodes = set()
        if any(k in ["calculo", "calcular", "como", "metodo", "metodologia", "processo", "explique"] for k in keywords):
            logger.info("Nadia: Heuristic 'Calculation' triggered. Injecting Methodology nodes.")
            # Target specific types known to be relevant for PIB calculation
            target_types = ["VALOR_ADICIONADO", "METODO", "CATEGORIA_DE_DEMANDA", "IMPOSTO", "SUBSIDIO"]
            for n in nodes:
                ntype = normalize_text(str(n.get("data", {}).get("type", ""))).upper()
                if any(t in ntype for t in target_types):
                    heuristic_nodes.add(n["data"]["id"])
            
            # Also inject neighbors of "PIB" specifically
            pib_nodes = [n for n in nodes if "PIB" in str(n.get("data", {}).get("label", "")).upper()]
            for pn in pib_nodes:
                heuristic_nodes.add(pn["data"]["id"])

        expanded_ids = set()
        if heuristic_nodes:
            expanded_ids.update(heuristic_nodes)
            print(f">>> HEURISTIC TRIGGERED: Injected {len(heuristic_nodes)} nodes")
        
        # Log nodes available for matching
        print(f"Matching keywords {keywords} against {len(nodes)} nodes...")

        matches_found = []

        # 1. Prioritized Matching
        for n in nodes:
            data = n.get("data", {})
            nid = normalize_text(str(data.get("id", "")))
            label = normalize_text(str(data.get("label", "")))
            ntype = normalize_text(str(data.get("type", "")))
            
            score = 0
            if any(kw == nid or kw == label for kw in keywords): score += 15
            elif any(kw in label for kw in keywords): score += 7
            elif any(kw in ntype for kw in keywords): score += 3
            
            if score > 0:
                relevant_id = data.get("id")
                expanded_ids.add(relevant_id)
                matches_found.append((relevant_id, score))

        # Sort and take top 30 relevant nodes as seeds
        matches_found.sort(key=lambda x: x[1], reverse=True)
        seeds = [m[0] for m in matches_found[:30]]
        
        # 2. Multi-Hop expansion
        adj = {}
        for e in edges:
            d = e.get("data", {})
            s, t = d.get("source"), d.get("target")
            if s and t:
                if s not in adj: adj[s] = []
                if t not in adj: adj[t] = []
                adj[s].append(t)
                adj[t].append(s)
            
        hop1 = set(seeds)
        for s in seeds:
            if s in adj:
                for neighbor in adj[s]:
                    hop1.add(neighbor)
                    
        high_priority_seeds = seeds[:5]
        hop2 = set(hop1)
        for s in high_priority_seeds:
            if s in adj:
                for n1 in adj[s]:
                    if n1 in adj:
                        for n2 in adj[n1]:
                            hop2.add(n2)
        
        expanded_ids.update(hop2)

        # 3. Global Context
        importance = stats.get("node_importance", {})
        top_global = sorted(nodes, key=lambda x: importance.get(str(x["data"].get("id")), 0), reverse=True)[:15]
        for n in top_global:
            expanded_ids.add(n["data"].get("id"))
            
        # 4. Final selection
        final_nodes = [n for n in nodes if n["data"].get("id") in expanded_ids][:120]
        final_expanded_ids = set(n["data"].get("id") for n in final_nodes)
        
        final_edges = [e for e in edges if e["data"]["source"] in final_expanded_ids and e["data"]["target"] in final_expanded_ids][:180]

        logger.info(f"Nadia Retrieval: {len(seeds)} matches, expanded to {len(final_nodes)} nodes, {len(final_edges)} edges.")

        node_summaries = []
        for n in final_nodes:
            nid, label, ntype = n["data"].get("id"), n["data"].get("label"), n["data"].get("type")
            node_summaries.append(f"- {label} (Tipo: {ntype})") # Removed ID from context to avoid leakage
            
        relation_summaries = []
        for e in final_edges:
            s, t = e["data"]["source"], e["data"]["target"]
            l = e["data"].get("label", e["data"].get("relation", "unknown"))
            relation_summaries.append(f"- {s} --[{l}]--> {t}")
        
        graph_context = f"""
        ESTATÍSTICAS DO GRAFO: {stats.get('total_nodes', len(nodes)) if stats else len(nodes)} nós, {stats.get('total_edges', len(edges)) if stats else len(edges)} relações.
        
        ENTIDADES RELEVANTES ENCONTRADAS:
        {chr(10).join(node_summaries)}
        
        CONEXÕES E FLUXOS:
        {chr(10).join(relation_summaries)}
        """
        
        if not node_summaries:
            logger.warning(f"Nadia Retrieval: No nodes found for keywords {keywords}")
            graph_context = "Nenhuma informação relevante foi encontrada no grafo para esta pergunta específica. Use seu Conhecimento Institucional (Seade) se aplicável, ou peça mais detalhes."
        if len(seeds) == 0 and len(heuristic_nodes) == 0:
            logger.warning(f"No relevant nodes found for keywords: {keywords}")
            
    except Exception as e:
        logger.error(f"Retrieval Error in Nadia: {e}")
        # Fallback to minimal context if retrieval fails
        graph_context = "Erro na recuperação do grafo. Responda com base no seu conhecimento geral/institucional."

    try:
        # Use manual replacement to avoid .format() errors with curly braces in graph data
        # If graph_context wasn't set due to retrieval error, it will use the fallback set in the except block
        system_content = NADIA_SYSTEM_PROMPT.replace("{graph_context}", graph_context)
        
        api_messages = [
            {"role": "system", "content": system_content}
        ]
        
        # Filter and add history
        for msg in messages[-6:]:
            if isinstance(msg, dict) and 'role' in msg and 'content' in msg:
                api_messages.append({"role": msg["role"], "content": msg["content"]})
        
        voice_mode = data.get("voice_mode", "premium") # 'premium' or 'local'
        
        # 1. OPTION: LOCAL VOICE (FREE)
        if voice_mode == "local":
            response = client.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=api_messages,
                temperature=0.5,
                max_tokens=600
            )
            answer = response.choices[0].message.content
            usage = response.usage
            
            # Clean for TTS
            clean_for_tts = re.sub(r'```json.*?```', '', answer, flags=re.DOTALL)
            clean_for_tts = re.sub(r'#+\s*', '', clean_for_tts)
            clean_for_tts = re.sub(r'\*\*', '', clean_for_tts)
            clean_for_tts = re.sub(r'[\(\[]?ID:\s*[\w\-]+[\)\]]?', '', clean_for_tts).strip()

            # Generate COMPLETE audio here (not per-segment) to avoid stuttering
            logger.info(f"Generating complete audio for {len(clean_for_tts)} characters...")
            audio_base64 = local_audio.generate_audio_base64(clean_for_tts)
            logger.info(f"Audio generation complete: {len(audio_base64) if audio_base64 else 0} bytes")
            
            # GPT-4o-mini Text Price (Feb 2025): $0.15 / $0.60 per 1M (Local Audio is FREE)
            text_cost = ((usage.prompt_tokens * 0.15) + (usage.completion_tokens * 0.60)) / 1000000.0
            
            # LOG USAGE (For the box the user requested)
            usage_tracker.log_usage(text_cost, is_local_voice=True)
            logger.info(f"Nadia Usage: Local Audio, Tokens={usage.total_tokens}, Cost=${text_cost:.6f}")
            
            return jsonify({
                "answer": answer,
                "audio_base64": audio_base64,
                "model_used": f"{settings.OPENAI_MODEL} + Kokoro (Local)",
                "cost_usd": text_cost, # Audio cost is $0.00
                "voice_type": "local"
            })

        # 2. OPTION: PREMIUM VOICE (FORCE Large Model)
        try:
            model_name = "gpt-4o-audio-preview"
            response = client.chat.completions.create(
                model=model_name,
                modalities=["text", "audio"],
                audio={"voice": "nova", "format": "wav"},
                messages=api_messages,
                max_tokens=600
            )
            
            assistant_msg = response.choices[0].message
            answer = assistant_msg.content
            audio_base64 = assistant_msg.audio.data if hasattr(assistant_msg, 'audio') else None

            # --- PRECISE COST CALCULATION (Large Model Pricing) ---
            usage = response.usage
            input_text_tokens = usage.prompt_tokens - usage.get('prompt_tokens_details', {}).get('audio_tokens', 0)
            input_audio_tokens = usage.get('prompt_tokens_details', {}).get('audio_tokens', 0)
            output_text_tokens = usage.completion_tokens - usage.get('completion_tokens_details', {}).get('audio_tokens', 0)
            output_audio_tokens = usage.get('completion_tokens_details', {}).get('audio_tokens', 0)

            # GPT-4o Audio (Large) Pricing: $2.50 / $10.00 (Text), $40.00 / $80.00 (Audio) per 1M
            cost_usd = (
                (input_text_tokens * 2.5) + (input_audio_tokens * 40.0) +
                (output_text_tokens * 10.0) + (output_audio_tokens * 80.0)
            ) / 1000000.0

            return jsonify({
                "answer": answer,
                "audio_base64": audio_base64,
                "model_used": model_name,
                "cost_usd": cost_usd,
                "usage": usage.to_dict()
            })
        except Exception as api_err:
            # Handle the 403 / Access denied specifically
            if "model_not_found" in str(api_err) or "403" in str(api_err):
                logger.warning(f"Premium Audio Access Denied: {api_err}")
                # Fallback to standard Text + TTS-1-HD (Unified block)
                response = client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=api_messages,
                    temperature=0.5,
                    max_tokens=600
                )
                answer = response.choices[0].message.content
                usage = response.usage
                
                # TTS-1-HD Price: $30 per 1M characters
                clean_for_tts = re.sub(r'```json.*?```', '', answer, flags=re.DOTALL)
                clean_for_tts = re.sub(r'#+\s*', '', clean_for_tts)
                clean_for_tts = re.sub(r'\*\*', '', clean_for_tts)
                clean_for_tts = re.sub(r'[\(\[]?ID:\s*[\w\-]+[\)\]]?', '', clean_for_tts).strip()

                try:
                    audio_res = client.audio.speech.create(
                        model="tts-1-hd", voice="nova", input=clean_for_tts[:4096]
                    )
                    audio_base64 = base64.b64encode(audio_res.content).decode('utf-8')
                    tts_cost = (len(clean_for_tts) * 30.0) / 1000000.0
                except:
                    audio_base64 = None
                    tts_cost = 0

                # GPT-4o-mini Text Price: $0.15 / $0.60 per 1M
                text_cost = ((usage.prompt_tokens * 0.15) + (usage.completion_tokens * 0.60)) / 1000000.0
                
                total_cost = text_cost + tts_cost
                usage_tracker.log_usage(total_cost, is_local_voice=False)

                return jsonify({
                    "answer": answer,
                    "audio_base64": audio_base64,
                    "model_used": f"{settings.OPENAI_MODEL} + TTS-1-HD",
                    "cost_usd": total_cost,
                    "warning": "Acesso ao modelo Audio Preview negado. Usando TTS-1-HD de alta fidelidade como fallback."
                })
            else:
                raise api_err
        
    except Exception as e:
        logger.error(f"Error in Nadia Chat: {e}")
        return jsonify({"error": str(e)}), 500

@bp.route("/audio", methods=["POST"])
def audio():
    """Generates speech using either Local or Premium TTS."""
    data = request.json
    text = data.get("text", "")
    voice_mode = data.get("voice_mode", "premium")
    
    if not text:
        return jsonify({"error": "No text provided"}), 400
        
    try:
        # 1. LOCAL TTS
        if voice_mode == "local":
            audio_base64 = local_audio.generate_audio_base64(text)
            if audio_base64:
                return Response(base64.b64decode(audio_base64), mimetype="audio/wav")
            # Fallback if local fails
            logger.warning("Local TTS failed, falling back to OpenAI")

        # 2. PREMIUM TTS (OpenAI)
        response = client.audio.speech.create(
            model="tts-1-hd", 
            voice="nova", 
            input=text[:4096]
        )
        return Response(response.content, mimetype="audio/mpeg")
        
    except Exception as e:
        logger.error(f"TTS Error: {e}")
        return jsonify({"error": str(e)}), 500

@bp.route("/usage", methods=["GET"])
def get_usage():
    """Returns financial tracking data."""
    return jsonify(usage_tracker.get_stats())
