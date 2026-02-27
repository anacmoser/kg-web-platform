import logging
import numpy as np
from openai import OpenAI
import chromadb
import faiss
from typing import Optional, List, Dict, Any

from app.config import settings, NodeType
from app.pipeline.stages.structural_extractor import FaissIndex
from app.graph.knowledge_graph import KnowledgeGraph
from app.utils import retry_with_exponential_backoff

logger = logging.getLogger(__name__)

def _format_context(nodes: list[dict]) -> str:
    """Formats the multimodal context block for the LLM."""
    blocks = []
    for i, node in enumerate(nodes, 1):
        meta     = node.get("metadata", {})
        ntype    = meta.get("node_type", "")
        doc      = meta.get("doc_id", "Desconhecido")
        page     = meta.get("page_num", "?")
        text     = node.get("text", "").strip()

        if not text:
            continue

        if ntype == NodeType["CHUNK"]:
            header = f"[{i}] 📄 Trecho — {doc} · Pág {page}"
        elif ntype == NodeType["IMAGE"]:
            header = f"[{i}] 🖼️  Descrição de Figura — {doc} · Pág {page}"
        elif ntype == NodeType["TABLE"]:
            header = f"[{i}] 📊 Descrição de Tabela — {doc} · Pág {page}"
        elif ntype == NodeType["SECTION"]:
            header = f"[{i}] 📑 Seção — {meta.get('section_title', '')} · {doc}"
        else:
            header = f"[{i}] 📌 {ntype} — {doc}"

        blocks.append(f"{header}\n{text}")

    return "\n\n---\n\n".join(blocks) if blocks else "Nenhum contexto relevante encontrado."

class GraphRAGSystem:
    """
    GraphRAG Query Engine:
      FAISS     → Semantic seeds
      NetworkX  → Contextual expansion
      ChromaDB  → Content retrieval
    """
    def __init__(self, client: OpenAI):
        self.openai = client

        # Load FAISS index
        if not FaissIndex.exists():
            logger.warning("FAISS index not found.")
            self.faiss = None
        else:
            self.faiss = FaissIndex.load()

        # Load Structural Graph
        self.kg = KnowledgeGraph.load(settings.STORAGE_DIR)
        
        # ChromaDB setup
        self.chroma_client = chromadb.PersistentClient(path=str(settings.CHROMA_PATH))
        self.collection = self.chroma_client.get_collection(name=settings.COLLECTION_NAME)

    @retry_with_exponential_backoff()
    def _embed_text(self, text: str) -> np.ndarray:
        resp = self.openai.embeddings.create(
            model="text-embedding-3-small",
            input=text[:8000],
        )
        return np.array(resp.data[0].embedding, dtype=np.float32)

    def query(
        self,
        question: str,
        top_k_faiss: int = 5,
        hop_depth: int = 2,
        max_context: int = 20,
    ) -> dict:
        """Executes the full GraphRAG pipeline."""
        if not self.faiss or self.kg.is_empty():
            return {
                "response": "Sistema GraphRAG ainda não processou documentos.",
                "context": ""
            }

        # 1. Embed query
        query_vec = self._embed_text(question).reshape(1, -1)
        faiss.normalize_L2(query_vec)

        # 2. FAISS search
        k = min(top_k_faiss, len(self.faiss.id_map))
        D, I = self.faiss.index.search(query_vec, k)
        
        seed_ids = []
        for i in I[0]:
            if i != -1:
                node_id = self.faiss.id_map[i]
                if node_id not in seed_ids:
                    seed_ids.append(node_id)

        if not seed_ids:
            return {"response": "Nenhum documento relevante encontrado.", "context": ""}

        # 3. Graph expansion
        expanded_ids = self.kg.expand_seeds(
            seed_ids,
            hop_depth=hop_depth,
            max_nodes=max_context,
            priority_types=[NodeType["CHUNK"], NodeType["TABLE"], NodeType["IMAGE"]],
        )

        # 4. ChromaDB retrieval
        results = self.collection.get(ids=expanded_ids)
        ids = results.get("ids", [])
        docs = results.get("documents", [])
        metas = results.get("metadatas", [])

        nodes = []
        for i in range(len(ids)):
            nodes.append({
                "id": ids[i],
                "text": docs[i],
                "metadata": metas[i]
            })

        # Filter and sort (seeds first)
        nodes = [n for n in nodes if n["text"].strip()]
        seed_set = set(seed_ids)
        nodes.sort(key=lambda n: (0 if n["id"] in seed_set else 1))
        nodes = nodes[:max_context]

        # 5. Format context
        context = _format_context(nodes)
        
        return {
            "context": context,
            "nodes_used": [n["id"] for n in nodes]
        }
