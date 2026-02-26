"""
config.py — Configurações centrais do GraphRAG Multimodal

Pipeline 1 (estrutural): ChromaDB[graphrag_docs] + FAISS + graph.pkl
  → fonte do chatbot, uso interno

Pipeline 2 (semântico):  ChromaDB[graphrag_semantic] + semantic_graph.pkl
  → fonte da visualização, análise, tabelas e ferramenta semântica do agente
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ══════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise EnvironmentError(
        "OPENAI_API_KEY nao encontrada.\n"
        "Crie um arquivo .env com: OPENAI_API_KEY=sk-..."
    )

# ══════════════════════════════════════════════════════════════
# MODELOS
# ══════════════════════════════════════════════════════════════
LLM_MODEL           = "gpt-4o"
LLM_MINI_MODEL      = "gpt-4o-mini"
EMBEDDING_MODEL     = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536

# ══════════════════════════════════════════════════════════════
# PATHS
# ══════════════════════════════════════════════════════════════
DATA_PATH    = Path("data")
CHROMA_PATH  = Path("chroma_db")
FAISS_PATH   = Path("faiss_index")
GRAPHS_PATH  = Path("graphs")
CACHE_PATH   = Path("cache")
VISUALS_PATH = Path("visualizations")

# ── Pipeline 1 — arquivos internos (chatbot) ──────────────────
FAISS_INDEX_FILE  = FAISS_PATH  / "index.faiss"
FAISS_MAP_FILE    = FAISS_PATH  / "id_map.json"
GRAPH_PICKLE_FILE = GRAPHS_PATH / "graph.pkl"
GRAPH_GML_FILE    = GRAPHS_PATH / "graph.gml"
GRAPH_JSON_FILE   = GRAPHS_PATH / "graph.json"

# ── Pipeline 2 — arquivos públicos (análise + visualização) ───
SEMANTIC_GRAPH_PICKLE = GRAPHS_PATH / "semantic_graph.pkl"
SEMANTIC_GRAPH_GML    = GRAPHS_PATH / "semantic_graph.gml"
GRAPH_HTML_FILE       = VISUALS_PATH / "semantic_graph_interactive.html"  # /graph/view
GRAPH_PNG_FILE        = VISUALS_PATH / "semantic_graph_static.png"
GRAPH_LANDING_FILE    = VISUALS_PATH / "graph_landing.html"

# ══════════════════════════════════════════════════════════════
# CHROMADB — duas collections
# ══════════════════════════════════════════════════════════════
COLLECTION_NAME          = "graphrag_docs"      # Pipeline 1 — chunks estruturais
COLLECTION_SEMANTIC_NAME = "graphrag_semantic"  # Pipeline 2 — textos contextuais de nodes

# ══════════════════════════════════════════════════════════════
# CHUNKING (Pipeline 1)
# ══════════════════════════════════════════════════════════════
CHUNK_SIZE       = 1200
CHUNK_OVERLAP    = 150
CHUNK_MIN_LENGTH = 80

# ══════════════════════════════════════════════════════════════
# TIPOS DE NODES — Pipeline 1 (estrutural, interno)
# ══════════════════════════════════════════════════════════════
class NodeType:
    DOCUMENT = "document"
    SECTION  = "section"
    PAGE     = "page"
    CHUNK    = "chunk"
    IMAGE    = "image"
    TABLE    = "table"

EMBEDDABLE_NODE_TYPES = {NodeType.CHUNK, NodeType.IMAGE, NodeType.TABLE}

# ══════════════════════════════════════════════════════════════
# TIPOS DE ARESTAS — Pipeline 1 (estrutural, interno)
# ══════════════════════════════════════════════════════════════
class EdgeType:
    DOCUMENT_HAS_SECTION  = "document_has_section"
    DOCUMENT_HAS_PAGE     = "document_has_page"
    SECTION_HAS_PAGE      = "section_has_page"
    PAGE_HAS_CHUNK        = "page_has_chunk"
    PAGE_HAS_IMAGE        = "page_has_image"
    PAGE_HAS_TABLE        = "page_has_table"
    CHUNK_NEXT            = "chunk_next"
    CHUNK_REF_IMAGE       = "chunk_ref_image"
    CHUNK_EXPLAINS_TABLE  = "chunk_explains_table"

# ══════════════════════════════════════════════════════════════
# TIPOS DE NODES — Pipeline 2 (semântico, público)
# Hierarquia: Label → Entity → Property
# ══════════════════════════════════════════════════════════════
class SemanticNodeType:
    LABEL    = "label"     # categoria: Empresa, Indicador, Data, Regiao...
    ENTITY   = "entity"    # instancia normalizada: "PIB Brasil 2024", "Volkswagen"
    PROPERTY = "property"  # atributo do entity: valor, unidade, fonte...

# ══════════════════════════════════════════════════════════════
# TIPOS DE ARESTAS — Pipeline 2 (semântico, público)
# ══════════════════════════════════════════════════════════════
class SemanticEdgeType:
    # Estruturais da hierarquia
    LABEL_HAS_ENTITY    = "label_has_entity"
    ENTITY_HAS_PROPERTY = "entity_has_property"
    # Relacionais (extraídas pelo LLM)
    IMPACTA             = "impacta"
    MEDE                = "mede"
    PERTENCE_A          = "pertence_a"
    PRODUZ              = "produz"
    CRESCE_EM           = "cresce_em"
    DECLINA_EM          = "declina_em"
    COMPARADO_COM       = "comparado_com"
    DEPENDE_DE          = "depende_de"
    RELACIONADO_COM     = "relacionado_com"  # fallback genérico

# ══════════════════════════════════════════════════════════════
# PARÂMETROS — Pipeline 2
# ══════════════════════════════════════════════════════════════
SEMANTIC_BATCH_SIZE        = 8   # chunks por chamada de extração LLM
SEMANTIC_NORMALIZE_BATCH   = 40  # entidades por chamada de normalização LLM
SEMANTIC_MIN_RECURRENCE    = 2   # entidade deve aparecer em >= N chunks p/ virar node

# ══════════════════════════════════════════════════════════════
# CONSULTA — Pipeline 1
# ══════════════════════════════════════════════════════════════
FAISS_TOP_K       = 8
GRAPH_HOP_DEPTH   = 2
CONTEXT_MAX_NODES = 20
RERANKER_MODEL    = "cross-encoder/ms-marco-MiniLM-L-6-v2"
ENABLE_RERANKING  = True

# ══════════════════════════════════════════════════════════════
# CORES — Pipeline 1 (grafo físico, interno)
# ══════════════════════════════════════════════════════════════
NODE_COLORS = {
    NodeType.DOCUMENT: "#E74C3C",
    NodeType.SECTION:  "#F39C12",
    NodeType.PAGE:     "#3498DB",
    NodeType.CHUNK:    "#2ECC71",
    NodeType.IMAGE:    "#9B59B6",
    NodeType.TABLE:    "#1ABC9C",
}

# ══════════════════════════════════════════════════════════════
# CORES — Pipeline 2 (grafo semântico, público)
# ══════════════════════════════════════════════════════════════
SEMANTIC_NODE_COLORS = {
    SemanticNodeType.LABEL:    "#E74C3C",  # vermelho — categoria
    SemanticNodeType.ENTITY:   "#3498DB",  # azul — entidade
    SemanticNodeType.PROPERTY: "#2ECC71",  # verde — propriedade
}

# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════
def ensure_dirs():
    for d in [DATA_PATH, CHROMA_PATH, FAISS_PATH, GRAPHS_PATH, CACHE_PATH, VISUALS_PATH]:
        d.mkdir(parents=True, exist_ok=True)