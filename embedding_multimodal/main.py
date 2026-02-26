"""
main.py — Ponto de entrada do GraphRAG

Modos de operação:
  python main.py --ingest           → Pipeline 1: processa PDFs (ChromaDB + FAISS + grafo físico)
  python main.py --ingest --reset   → Pipeline 1: reinicia do zero
  python main.py --ingest --resume  → Pipeline 1: continua de onde parou (pula páginas já processadas)
  python main.py --semantic         → Pipeline 2: extrai grafo semântico dos chunks do P1
  python main.py --semantic --reset → Pipeline 2: recria collection semântica do zero
  python main.py --stats            → status de P1 e P2
  python main.py --visualize        → sobe servidor e exibe grafo semântico em localhost:8000/graph/view
  python main.py --api              → inicia servidor FastAPI completo
  python main.py                    → chat interativo (padrão)

Fluxo recomendado:
  1. Adicione PDFs em data/
  2. python main.py --ingest        (Pipeline 1)
  3. python main.py --semantic      (Pipeline 2)
  4. python main.py                 (chat) ou python main.py --api (servidor)
"""

import sys
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# MODOS
# ══════════════════════════════════════════════════════════════

def mode_ingest():
    """Pipeline 1: processa PDFs e constrói ChromaDB + FAISS + grafo físico."""
    from config import DATA_PATH
    from embedding import run_ingestion

    reset     = "--reset"  in sys.argv
    resume    = "--resume" in sys.argv
    data_path = Path(DATA_PATH)

    if reset:
        print("Modo --reset: base sera reconstruida do zero.")
    if resume:
        print("Modo --resume: paginas ja processadas serao puladas.")

    if not data_path.exists() or not list(data_path.glob("*.pdf")):
        print(f"Nenhum PDF encontrado em '{data_path}'.")
        print("Adicione PDFs na pasta data/ e execute novamente.")
        sys.exit(1)

    run_ingestion(data_path=data_path, reset=reset, resume=resume)
    print("\nPipeline 1 concluido.")
    print("Proximo passo: python main.py --semantic")


def mode_semantic():
    """Pipeline 2: extrai grafo semântico dos chunks do Pipeline 1."""
    from semantic_graph import run_semantic_pipeline, SemanticKnowledgeGraph
    import chromadb
    from config import CHROMA_PATH, COLLECTION_SEMANTIC_NAME

    reset = "--reset" in sys.argv
    if reset:
        print("Modo --reset: collection semantica sera removida.")
        try:
            cc = chromadb.PersistentClient(path=str(CHROMA_PATH))
            cc.delete_collection(COLLECTION_SEMANTIC_NAME)
            print(f"  Collection '{COLLECTION_SEMANTIC_NAME}' removida.")
        except Exception:
            pass

    print("\n" + "=" * 60)
    print("  PIPELINE 2 — EXTRACAO DO GRAFO SEMANTICO")
    print("=" * 60)
    print("\nEscolha o escopo da extracao:\n")
    print("  [1] Geral       — todos os chunks do corpus (mais completo)")
    print("  [2] Focado      — filtrar por tema/termo (menor custo de API)")
    print("  [3] Por documento — escolher um PDF especifico\n")

    while True:
        choice = input("Opcao (1/2/3) [padrao: 1]: ").strip() or "1"
        if choice in ("1", "2", "3"):
            break
        print("  Opcao invalida. Digite 1, 2 ou 3.")

    topic      = None
    doc_filter = None

    if choice == "2":
        topic = input("Tema ou termos-chave (ex: 'setor automotivo', 'PIB'): ").strip()
        if not topic:
            print("  Nenhum tema informado — usando escopo geral.")
            choice = "1"

    elif choice == "3":
        doc_filter = input("Nome (parcial) do arquivo PDF (ex: 'relatorio_2024'): ").strip()
        if not doc_filter:
            print("  Nenhum documento informado — usando escopo geral.")
            choice = "1"

    print()
    run_semantic_pipeline(scope=choice, topic=topic, doc_filter=doc_filter)

    print("\nPipeline 2 concluido.")
    print("Para visualizar: python main.py --visualize")
    print("Para iniciar API: python main.py --api")


def mode_stats():
    """Exibe status de P1 e P2."""
    import chromadb
    from config import CHROMA_PATH, COLLECTION_NAME, COLLECTION_SEMANTIC_NAME

    print("\n" + "=" * 60)
    print("  GRAPHRAG — STATUS DO SISTEMA")
    print("=" * 60)

    # Pipeline 1
    print("\n  PIPELINE 1 (RAG / chatbot):")
    try:
        from graph_builder import KnowledgeGraph
        if KnowledgeGraph.exists():
            kg = KnowledgeGraph.load()
            s  = kg.stats()
            print(f"    Grafo fisico:  {s['total_nodes']} nodes, {s['total_edges']} arestas")
        else:
            print("    Grafo fisico:  nao encontrado")
    except Exception as e:
        print(f"    Grafo fisico:  erro — {e}")

    try:
        from embedding import FaissIndex
        if FaissIndex.exists():
            fi = FaissIndex.load()
            print(f"    FAISS:         {fi.index.ntotal} vetores")
        else:
            print("    FAISS:         nao encontrado")
    except Exception as e:
        print(f"    FAISS:         erro — {e}")

    try:
        cc  = chromadb.PersistentClient(path=str(CHROMA_PATH))
        col = cc.get_collection(COLLECTION_NAME)
        print(f"    ChromaDB P1:   {col.count()} nodes")
    except Exception:
        print("    ChromaDB P1:   nao encontrado")

    # Pipeline 2
    print("\n  PIPELINE 2 (grafo semantico / visualizacao):")
    try:
        from semantic_graph import SemanticKnowledgeGraph
        if SemanticKnowledgeGraph.exists():
            skg = SemanticKnowledgeGraph.load()
            skg.print_stats()
        else:
            print("    Grafo semantico: nao encontrado")
            print("    Execute: python main.py --semantic")
    except Exception as e:
        print(f"    Grafo semantico: erro — {e}")

    try:
        cc  = chromadb.PersistentClient(path=str(CHROMA_PATH))
        col = cc.get_collection(COLLECTION_SEMANTIC_NAME)
        print(f"    ChromaDB P2:   {col.count()} entidades")
    except Exception:
        print("    ChromaDB P2:   nao encontrado")

    print("=" * 60)


def mode_visualize():
    """Gera visualizações do grafo semântico e sobe servidor em localhost:8000/graph/view."""
    import uvicorn
    from semantic_graph import SemanticKnowledgeGraph

    if not SemanticKnowledgeGraph.exists():
        print("Grafo semantico nao encontrado.")
        print("Execute primeiro: python main.py --semantic")
        sys.exit(1)

    print("Gerando visualizacoes do grafo semantico...")
    skg = SemanticKnowledgeGraph.load()
    skg.visualize_static()
    skg.visualize_interactive()
    skg.print_stats()

    print("\n  Servidor disponivel em: http://localhost:8000/graph/view")
    print("  Pressione Ctrl+C para encerrar.\n")

    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)


def mode_api():
    """Inicia o servidor FastAPI completo."""
    import uvicorn
    print("Iniciando GraphRAG API em http://0.0.0.0:8000")
    print("  Grafo semantico: http://localhost:8000/graph/view")
    print("  Docs:            http://localhost:8000/docs")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)


def mode_chat():
    """Chat interativo no terminal."""
    print("\nInicializando GraphRAG Agent...")
    from agent import GraphRAGAgent
    GraphRAGAgent().run_interactive()


# ══════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════

def main():
    args = sys.argv[1:]

    if "--ingest" in args:
        mode_ingest()
    elif "--semantic" in args:
        mode_semantic()
    elif "--stats" in args:
        mode_stats()
    elif "--visualize" in args:
        mode_visualize()
    elif "--api" in args:
        mode_api()
    else:
        mode_chat()


if __name__ == "__main__":
    main()