"""
rag_system.py — Motor de consulta GraphRAG

Pipeline de consulta:
  1. Embed da pergunta → FAISS → top_k seeds (node_ids)
  2. NetworkX BFS a partir dos seeds → conjunto expandido de node_ids
  3. ChromaDB.get(node_ids) → conteúdo textual dos nodes
  4. Reranking opcional com CrossEncoder
  5. Montagem de contexto multimodal (chunks + imagens + tabelas)
  6. GPT-4o gera a resposta final

ChromaDB: NUNCA é consultado por similaridade aqui.
FAISS:    ÚNICO responsável pela busca vetorial.
NetworkX: ÚNICO responsável pela expansão contextual.
"""

import logging
from typing import Optional

import numpy as np
from openai import OpenAI
import chromadb

from config import (
    OPENAI_API_KEY, LLM_MODEL, LLM_MINI_MODEL,
    CHROMA_PATH, COLLECTION_NAME,
    FAISS_TOP_K, GRAPH_HOP_DEPTH, CONTEXT_MAX_NODES,
    ENABLE_RERANKING, RERANKER_MODEL,
    NodeType,
)
from embedding import FaissIndex, embed_text, chroma_get
from graph_builder import KnowledgeGraph

logger = logging.getLogger(__name__)

# Reranker (opcional)
try:
    from sentence_transformers import CrossEncoder
    _RERANKER_AVAILABLE = True
except ImportError:
    _RERANKER_AVAILABLE = False
    logger.warning("sentence_transformers não disponível — reranking desativado.")


# ══════════════════════════════════════════════════════════════
# SISTEMA PROMPT
# ══════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """
Você é um assistente especializado em análise profunda de documentos.

Use **exclusivamente** os trechos, descrições de imagens e tabelas fornecidos abaixo para responder.
Nunca invente informações. Se os dados forem insuficientes, declare isso claramente.

Os materiais fornecidos podem conter:
1. **Texto** — trechos extraídos diretamente dos documentos.
2. **Descrição de Figura** — descrição textual gerada por IA de gráficos e imagens.
3. **Descrição de Tabela** — descrição e transcrição de tabelas.

Sua resposta deve:
- Ser clara, direta e bem estruturada.
- Citar fatos, números e fontes (documento, página) sempre que possível.
- Usar listas ou seções quando apropriado para clareza.
- Estar em português formal.
- Indicar quando a informação é limitada ou parcial.

Se a pergunta envolver cálculos (percentuais, somas, taxas, VPL, TIR), responda com os
passos matemáticos em LaTeX (use \\[ ... \\]) e inclua o resultado final.

Se os dados não forem suficientes:
"Não encontrei informações suficientes nos documentos disponíveis para responder isso.
Poderia reformular ou detalhar melhor a pergunta?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONTEXTO RECUPERADO:
{context}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


# ══════════════════════════════════════════════════════════════
# FORMATAÇÃO DO CONTEXTO
# ══════════════════════════════════════════════════════════════

def _format_context(nodes: list[dict]) -> str:
    """Monta o bloco de contexto multimodal para o LLM."""
    blocks = []
    for i, node in enumerate(nodes, 1):
        meta     = node.get("metadata", {})
        ntype    = meta.get("node_type", "")
        doc      = meta.get("doc_id", "")
        page     = meta.get("page_num", "?")
        text     = node.get("text", "").strip()

        if not text:
            continue

        if ntype == NodeType.CHUNK:
            header = f"[{i}] 📄 Trecho — {doc} · Pág {page}"
        elif ntype == NodeType.IMAGE:
            header = f"[{i}] 🖼️  Descrição de Figura — {doc} · Pág {page}"
        elif ntype == NodeType.TABLE:
            header = f"[{i}] 📊 Descrição de Tabela — {doc} · Pág {page}"
        elif ntype == NodeType.SECTION:
            header = f"[{i}] 📑 Seção — {meta.get('section_title', '')} · {doc}"
        else:
            header = f"[{i}] 📌 {ntype} — {doc}"

        blocks.append(f"{header}\n{text}")

    return "\n\n---\n\n".join(blocks) if blocks else "Nenhum contexto relevante encontrado."


# ══════════════════════════════════════════════════════════════
# CLASSE PRINCIPAL
# ══════════════════════════════════════════════════════════════

class GraphRAGSystem:
    """
    Motor de consulta GraphRAG com três camadas:
      FAISS     → seeds semânticos
      NetworkX  → expansão contextual
      ChromaDB  → recuperação de conteúdo
    """

    def __init__(self):
        self.openai = OpenAI(api_key=OPENAI_API_KEY)

        # Carregar índice FAISS
        if not FaissIndex.exists():
            raise RuntimeError(
                "Índice FAISS não encontrado. Execute: python main.py --ingest"
            )
        self.faiss = FaissIndex.load()

        # Carregar grafo NetworkX
        if not KnowledgeGraph.exists():
            raise RuntimeError(
                "Grafo não encontrado. Execute: python main.py --ingest"
            )
        self.kg = KnowledgeGraph.load()

        # ChromaDB — apenas para recuperação de conteúdo
        chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        self.collection = chroma_client.get_collection(name=COLLECTION_NAME)

        # Reranker
        self.reranker: Optional[object] = None
        if ENABLE_RERANKING and _RERANKER_AVAILABLE:
            try:
                self.reranker = CrossEncoder(RERANKER_MODEL)
                logger.info("✅ Reranker carregado.")
            except Exception as e:
                logger.warning(f"Reranker não carregado: {e}")

        logger.info(
            f"✅ GraphRAGSystem inicializado — "
            f"{self.faiss.index.ntotal} vetores, "
            f"{self.kg.G.number_of_nodes()} nodes no grafo"
        )

    # ── Pipeline de consulta ──────────────────────────────────

    def query(
        self,
        question: str,
        top_k_faiss: int  = FAISS_TOP_K,
        hop_depth: int    = GRAPH_HOP_DEPTH,
        max_context: int  = CONTEXT_MAX_NODES,
    ) -> dict:
        """
        Executa o pipeline completo de GraphRAG.

        Returns:
            dict com keys: response, seeds, expanded_ids, nodes_used, context
        """
        # 1. Embed da pergunta
        query_vec = embed_text(question)

        # 2. FAISS → seeds
        seed_ids = self.faiss.search(query_vec, top_k=top_k_faiss)
        logger.info(f"🔍 FAISS seeds: {seed_ids}")

        if not seed_ids:
            return {
                "response": "Nenhum documento relevante encontrado. Verifique se a ingestão foi realizada.",
                "seeds": [], "expanded_ids": [], "nodes_used": [], "context": "",
            }

        # 3. NetworkX → expandir contexto
        expanded_ids = self.kg.expand_seeds(
            seed_ids,
            hop_depth=hop_depth,
            max_nodes=max_context,
            priority_types=[NodeType.CHUNK, NodeType.TABLE, NodeType.IMAGE],
        )
        logger.info(f"🕸️  Nodes expandidos: {len(expanded_ids)}")

        # 4. ChromaDB → recuperar conteúdo
        nodes = chroma_get(self.collection, expanded_ids)

        # Filtrar nodes sem texto útil
        nodes = [n for n in nodes if n.get("text", "").strip()]

        # 5. Reranking (apenas sobre nodes embeddable)
        if self.reranker and nodes:
            embeddable_nodes = [
                n for n in nodes
                if n.get("metadata", {}).get("node_type") in {
                    NodeType.CHUNK, NodeType.IMAGE, NodeType.TABLE
                }
            ]
            other_nodes = [n for n in nodes if n not in embeddable_nodes]

            if embeddable_nodes:
                pairs  = [[question, n["text"]] for n in embeddable_nodes]
                scores = self.reranker.predict(pairs)
                for node, score in zip(embeddable_nodes, scores):
                    node["_rerank_score"] = float(score)
                embeddable_nodes.sort(key=lambda x: x.get("_rerank_score", 0), reverse=True)

            nodes = embeddable_nodes[:max_context] + other_nodes
        else:
            # Manter seeds no topo
            seed_set = set(seed_ids)
            nodes.sort(key=lambda n: (0 if n["id"] in seed_set else 1))

        nodes = nodes[:max_context]

        # 6. Montar contexto e gerar resposta
        context  = _format_context(nodes)
        response = self._generate(question, context)

        return {
            "response":     response,
            "seeds":        seed_ids,
            "expanded_ids": expanded_ids,
            "nodes_used":   [n["id"] for n in nodes],
            "context":      context,
        }

    def _generate(self, question: str, context: str) -> str:
        """Chama GPT-4o com o contexto montado."""
        try:
            resp = self.openai.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT.format(context=context)},
                    {"role": "user",   "content": question},
                ],
                temperature=0.2,
                max_tokens=2048,
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.error(f"Erro ao gerar resposta: {e}")
            return "Ocorreu um erro ao gerar a resposta. Tente novamente."

    def get_system_info(self) -> dict:
        """Status do sistema para health check e agente."""
        return {
            "ready":          True,
            "faiss_vectors":  self.faiss.index.ntotal,
            "graph_nodes":    self.kg.G.number_of_nodes(),
            "graph_edges":    self.kg.G.number_of_edges(),
            "chroma_docs":    self.collection.count(),
            "reranking":      self.reranker is not None,
            "llm_model":      LLM_MODEL,
        }
