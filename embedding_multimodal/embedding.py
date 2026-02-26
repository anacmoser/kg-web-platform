"""
embedding.py — Pipeline de ingestão multimodal (versão máxima)

Fluxo por PDF:
  1. test_pdf_access()       → diagnóstico antes de processar
  2. PyMuPDF extrai texto, imagens e tabelas de cada página
  3. Chunks de texto criados por parágrafo/bloco conceitual
  4. GPT-4o Vision descreve:
       a) imagens individuais extraídas da página
       b) tabelas renderizadas como imagem + pandas markdown
       c) página inteira como fallback (quando pouco texto + sem elementos)
  5. Nodes criados no ChromaDB (conteúdo + metadados enriquecidos)
  6. Embeddings gerados em lote para chunks, individualmente para imagens/tabelas
  7. FaissIndex: vetores com L2-norm + Inner Product
  8. NetworkX: grafo de relações estruturais e semânticas

Diferenciais:
  - Resume mode: pula páginas já processadas (consulta ChromaDB antes)
  - test_pdf_access / test_chromadb_connection: diagnóstico pré-execução
  - describe_page_full: fallback para páginas com layout visual sem elementos
  - FaissIndex.search_with_scores: retorna scores de similaridade
  - Metadados enriquecidos: word_count, has_numbers, char_count
  - validate_collection: verifica integridade pós-ingestão

Camadas:
  ChromaDB  → conteúdo (texto, metadados, descrições visuais)
  FAISS     → vetores (apenas nodes embeddable)
  NetworkX  → relações estruturais e semânticas
"""

import io
import json
import logging
import base64
import hashlib
import sys
import re
from pathlib import Path
from typing import Optional

import fitz           # PyMuPDF
import numpy as np
from PIL import Image
import faiss
import chromadb
from openai import OpenAI

from config import (
    OPENAI_API_KEY, EMBEDDING_MODEL, EMBEDDING_DIMENSION, LLM_MODEL,
    DATA_PATH, CHROMA_PATH, FAISS_INDEX_FILE, FAISS_MAP_FILE, CACHE_PATH,
    COLLECTION_NAME, CHUNK_SIZE, CHUNK_OVERLAP, CHUNK_MIN_LENGTH,
    NodeType, EdgeType, EMBEDDABLE_NODE_TYPES,
    GRAPH_HTML_FILE, GRAPH_PNG_FILE,
    ensure_dirs,
)
from utils import (
    retry_with_exponential_backoff,
    make_doc_id, make_section_id, make_page_id, make_chunk_id,
    make_image_id, make_table_id,
    clean_text, split_into_chunks, detect_section_title, truncate,
)
from graph_builder import KnowledgeGraph

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

openai_client = OpenAI(api_key=OPENAI_API_KEY)

# Limiar: se página tem menos que N chars de texto E nenhum elemento extraído,
# ativa descrição da página inteira.
PAGE_FULL_VISION_THRESHOLD = 150

# DPI para renderização da página inteira (usado no fallback de visão)
PAGE_RENDER_DPI = 200

# Tamanho mínimo de imagem individual para ser processada (pixels)
IMG_MIN_SIZE = 80

# Tamanho máximo de imagem antes de redimensionar (pixels)
IMG_MAX_SIZE = 1024


# ══════════════════════════════════════════════════════════════
# FAISS — índice vetorial
# ══════════════════════════════════════════════════════════════

class FaissIndex:
    """
    Wrapper do índice FAISS com mapeamento faiss_idx → node_id.
    Usa IndexFlatIP (Inner Product) com vetores L2-normalizados
    para busca por cosine similarity eficiente.
    """

    def __init__(self):
        self.index = faiss.IndexFlatIP(EMBEDDING_DIMENSION)
        self.id_map: list[str] = []  # posição i → node_id

    def add(self, node_id: str, vector: np.ndarray):
        """Adiciona um vetor normalizado ao índice."""
        vec = vector.astype(np.float32).reshape(1, -1)
        faiss.normalize_L2(vec)
        self.index.add(vec)
        self.id_map.append(node_id)

    def save(self):
        ensure_dirs()
        faiss.write_index(self.index, str(FAISS_INDEX_FILE))
        with open(FAISS_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(self.id_map, f, ensure_ascii=False)
        logger.info(f"FAISS salvo: {self.index.ntotal} vetores → '{FAISS_INDEX_FILE}'")

    @classmethod
    def load(cls) -> "FaissIndex":
        fi = cls()
        fi.index = faiss.read_index(str(FAISS_INDEX_FILE))
        with open(FAISS_MAP_FILE, "r", encoding="utf-8") as f:
            fi.id_map = json.load(f)
        logger.info(f"FAISS carregado: {fi.index.ntotal} vetores")
        return fi

    @classmethod
    def exists(cls) -> bool:
        return FAISS_INDEX_FILE.exists() and FAISS_MAP_FILE.exists()

    def search(self, vector: np.ndarray, top_k: int) -> list[str]:
        """Retorna top_k node_ids mais próximos."""
        vec = vector.astype(np.float32).reshape(1, -1)
        faiss.normalize_L2(vec)
        _, indices = self.index.search(vec, top_k)
        return [self.id_map[i] for i in indices[0] if 0 <= i < len(self.id_map)]

    def search_with_scores(self, vector: np.ndarray, top_k: int) -> list[tuple[str, float]]:
        """
        Retorna lista de (node_id, score) ordenada por relevância decrescente.
        Score é cosine similarity (0–1 para vetores positivos).
        """
        vec = vector.astype(np.float32).reshape(1, -1)
        faiss.normalize_L2(vec)
        scores, indices = self.index.search(vec, top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if 0 <= idx < len(self.id_map):
                results.append((self.id_map[idx], float(score)))
        return results


# ══════════════════════════════════════════════════════════════
# CHROMADB — repositório de conteúdo
# ══════════════════════════════════════════════════════════════

def get_chroma_collection():
    """
    Retorna (ou cria) a coleção ChromaDB do Pipeline 1.
    SEM embedding function — gerenciamos embeddings via FAISS externamente.
    """
    ensure_dirs()
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def chroma_upsert(collection, node_id: str, text: str, metadata: dict):
    """Insere ou atualiza um node no ChromaDB."""
    collection.upsert(
        ids=[node_id],
        documents=[text],
        metadatas=[metadata],
    )


def chroma_get(collection, node_ids: list[str]) -> list[dict]:
    """
    Recupera nodes do ChromaDB por IDs.
    Retorna lista de dicts com id, text, metadata.
    """
    if not node_ids:
        return []
    result = collection.get(ids=node_ids, include=["documents", "metadatas"])
    nodes  = []
    for i, nid in enumerate(result["ids"]):
        nodes.append({
            "id":       nid,
            "text":     result["documents"][i],
            "metadata": result["metadatas"][i],
        })
    return nodes


def node_exists_in_chroma(collection, node_id: str) -> bool:
    """Verifica se um node_id já existe no ChromaDB (usado no resume mode)."""
    try:
        result = collection.get(ids=[node_id], include=[])
        return len(result["ids"]) > 0
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════
# DIAGNÓSTICOS — test_pdf_access / test_chromadb_connection
# ══════════════════════════════════════════════════════════════

def test_pdf_access(pdf_path: Path) -> bool:
    """
    Testa se um PDF pode ser aberto, tem texto extraível e pode ser renderizado.
    Executa antes da ingestão para evitar falhas silenciosas no meio do processo.
    """
    try:
        logger.info(f"Testando acesso ao PDF: {pdf_path.name}")
        doc = fitz.open(pdf_path)

        if doc.page_count == 0:
            logger.error(f"  PDF sem páginas: {pdf_path.name}")
            doc.close()
            return False

        page    = doc[0]
        text    = page.get_text()
        pix     = page.get_pixmap(dpi=72)  # resolução baixa só para teste
        img     = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

        logger.info(
            f"  OK: {doc.page_count} páginas | "
            f"{len(text)} chars pág1 | "
            f"render {img.width}x{img.height}"
        )
        doc.close()
        return True

    except Exception as e:
        logger.error(f"  Falha ao testar PDF '{pdf_path.name}': {e}")
        return False


def test_chromadb_connection(chroma_path: str, collection_name: str) -> bool:
    """
    Testa a conexão com o ChromaDB fazendo um ciclo completo:
    create → add → query → delete.
    Garante que a instância está funcional antes de iniciar a ingestão.
    """
    test_col = f"test_connection_{collection_name}"
    try:
        logger.info(f"Testando conexão ChromaDB em '{chroma_path}'...")
        ensure_dirs()

        cc  = chromadb.PersistentClient(path=str(chroma_path))
        col = cc.get_or_create_collection(name=test_col, metadata={"hnsw:space": "cosine"})

        col.add(
            ids=["__ping__"],
            documents=["teste de conexão"],
            metadatas=[{"test": True}],
        )
        result = col.get(ids=["__ping__"], include=["documents"])
        assert result["documents"][0] == "teste de conexão", "Dado não recuperado"

        cc.delete_collection(test_col)
        logger.info("  ChromaDB OK — ciclo completo (add/get/delete) funcionando")
        return True

    except Exception as e:
        logger.error(f"  ChromaDB FALHOU: {e}")
        try:
            cc.delete_collection(test_col)
        except Exception:
            pass
        return False


def validate_collection(collection, min_docs: int = 1) -> dict:
    """
    Verifica integridade da coleção pós-ingestão:
    - Conta documentos
    - Executa query de teste
    - Verifica metadados básicos
    Retorna dict com resultado da validação.
    """
    result = {"ok": False, "count": 0, "query_ok": False, "error": ""}
    try:
        count = collection.count()
        result["count"] = count

        if count < min_docs:
            result["error"] = f"Coleção com apenas {count} documento(s)"
            return result

        # Query de teste com texto genérico
        qr = collection.query(
            query_texts=["documento"],
            n_results=min(3, count),
            include=["documents", "metadatas"],
        )
        if qr["documents"] and qr["documents"][0]:
            result["query_ok"] = True

        result["ok"] = result["query_ok"]
        return result

    except Exception as e:
        result["error"] = str(e)
        return result


# ══════════════════════════════════════════════════════════════
# EMBEDDINGS
# ══════════════════════════════════════════════════════════════

@retry_with_exponential_backoff()
def embed_text(text: str) -> np.ndarray:
    """Gera embedding para um texto via OpenAI (single)."""
    resp = openai_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text[:8000],
    )
    return np.array(resp.data[0].embedding, dtype=np.float32)


def embed_texts_batch(texts: list[str]) -> list[np.ndarray]:
    """
    Gera embeddings em lote via OpenAI (até 50 por requisição).
    Mais eficiente que chamadas individuais para chunks de texto.
    """
    vectors    = []
    batch_size = 50
    for i in range(0, len(texts), batch_size):
        batch = [t[:8000] for t in texts[i : i + batch_size]]
        resp  = openai_client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        vectors.extend([np.array(d.embedding, dtype=np.float32) for d in resp.data])
    return vectors


# ══════════════════════════════════════════════════════════════
# METADADOS ENRIQUECIDOS
# ══════════════════════════════════════════════════════════════

def _enrich_metadata(text: str, base_meta: dict) -> dict:
    """
    Adiciona campos calculados ao metadado de um node:
    - char_count: comprimento em caracteres
    - word_count: contagem aproximada de palavras
    - has_numbers: booleano se o texto contém sequências numéricas
    """
    base_meta["char_count"]  = str(len(text))
    base_meta["word_count"]  = str(len(text.split()))
    base_meta["has_numbers"] = str(bool(re.search(r"\d+[.,]?\d*", text)))
    return base_meta


# ══════════════════════════════════════════════════════════════
# GPT-4o VISION — helpers de imagem
# ══════════════════════════════════════════════════════════════

def _cache_path(content_hash: str) -> Path:
    return CACHE_PATH / f"{content_hash}.json"


def _image_to_base64(img: Image.Image, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def _hash_image(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return hashlib.sha256(buf.getvalue()).hexdigest()[:16]


def _resize_if_needed(img: Image.Image, max_size: int = IMG_MAX_SIZE) -> Image.Image:
    """Redimensiona imagem para não exceder max_size em nenhuma dimensão."""
    if img.width > max_size or img.height > max_size:
        img = img.copy()
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return img


# ══════════════════════════════════════════════════════════════
# GPT-4o VISION — descrições com cache
# ══════════════════════════════════════════════════════════════

@retry_with_exponential_backoff()
def describe_visual(img: Image.Image, element_type: str = "image") -> str:
    """
    Usa GPT-4o Vision para descrever um elemento visual (imagem ou tabela).
    Resultados são cacheados por hash de conteúdo para evitar chamadas redundantes.

    element_type: "image" | "table"
    """
    ensure_dirs()
    img_hash   = _hash_image(img)
    cache_file = _cache_path(f"{element_type}_{img_hash}")

    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))["description"]
        except Exception:
            pass  # cache corrompido → regenerar

    if element_type == "image":
        prompt = (
            "Descreva detalhadamente o conteúdo desta imagem para um sistema de busca. "
            "Inclua: dados numéricos visíveis, títulos, legendas, tendências, "
            "unidades de medida e qualquer informação textual presente. "
            "Seja objetivo e completo. Responda em português."
        )
        max_tokens = 1024
    else:  # table
        prompt = (
            "Descreva esta tabela em detalhes para um sistema de busca. "
            "Inclua: cabeçalhos, valores numéricos, unidades, totais e qualquer nota presente. "
            "Transcreva os dados principais de forma estruturada. Responda em português."
        )
        max_tokens = 1024

    resp = openai_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text",      "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{_image_to_base64(img)}"
                }},
            ],
        }],
        max_tokens=max_tokens,
    )
    description = resp.choices[0].message.content

    try:
        cache_file.write_text(
            json.dumps({"description": description}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Erro ao salvar cache visual: {e}")

    return description


@retry_with_exponential_backoff()
def describe_page_full(page: fitz.Page, filename: str, page_num: int) -> str:
    """
    Renderiza a página inteira como imagem e descreve com GPT-4o Vision.

    Usado como FALLBACK para páginas com:
    - pouco texto extraído (< PAGE_FULL_VISION_THRESHOLD chars)
    - nenhuma imagem individual e nenhuma tabela detectada

    Captura conteúdo visual que não vira elemento isolado:
    anotações, layouts mistos, texto sobre gráficos, infográficos, etc.
    Resultados também são cacheados.
    """
    ensure_dirs()

    # Hash baseado em nome+página para cache determinístico
    cache_key  = hashlib.sha256(
        f"fullpage:{filename}:p{page_num}".encode()
    ).hexdigest()[:16]
    cache_file = _cache_path(f"fullpage_{cache_key}")

    if cache_file.exists():
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))["description"]
        except Exception:
            pass

    pix = page.get_pixmap(dpi=PAGE_RENDER_DPI)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    img = _resize_if_needed(img, max_size=IMG_MAX_SIZE)

    prompt = (
        f"Esta é a página {page_num} do documento '{filename}'. "
        "Descreva completamente todo o conteúdo visual desta página para um sistema de busca: "
        "gráficos, tabelas, infográficos, imagens, diagramas, textos destacados, "
        "títulos, legendas e qualquer informação relevante. "
        "Inclua todos os dados numéricos, percentuais e tendências visíveis. "
        "Responda em português, de forma objetiva e detalhada."
    )

    resp = openai_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text",      "text": prompt},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{_image_to_base64(img)}"
                }},
            ],
        }],
        max_tokens=2048,
    )
    description = resp.choices[0].message.content

    try:
        cache_file.write_text(
            json.dumps({"description": description}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Erro ao salvar cache de página completa: {e}")

    return description


# ══════════════════════════════════════════════════════════════
# PIPELINE DE INGESTÃO — por PDF
# ══════════════════════════════════════════════════════════════

def ingest_pdf(
    pdf_path: Path,
    collection,
    faiss_index: FaissIndex,
    kg: KnowledgeGraph,
    resume: bool = False,
) -> dict:
    """
    Ingere um PDF completo nas três camadas: ChromaDB, FAISS e NetworkX.

    Args:
        pdf_path:    caminho para o PDF
        collection:  coleção ChromaDB do Pipeline 1
        faiss_index: índice FAISS
        kg:          grafo NetworkX
        resume:      se True, pula páginas cujo page_id já existe no ChromaDB

    Retorna dict com contagens: chunks, images, tables, pages, sections, skipped_pages
    """
    filename  = pdf_path.name
    doc_id    = make_doc_id(filename)
    stats_out = {
        "chunks": 0, "images": 0, "tables": 0,
        "pages": 0, "sections": 0, "skipped_pages": 0,
        "full_page_visions": 0,
    }

    # ── Diagnóstico pré-ingestão ──────────────────────────────
    if not test_pdf_access(pdf_path):
        logger.error(f"Pulando '{filename}' — falha no teste de acesso")
        return stats_out

    logger.info(f"\nIngerindo: {filename}")

    # ── Node: DOCUMENT ────────────────────────────────────────
    if not (resume and node_exists_in_chroma(collection, doc_id)):
        chroma_upsert(collection, doc_id, filename, _enrich_metadata(filename, {
            "node_type": NodeType.DOCUMENT,
            "doc_id":    doc_id,
            "filename":  filename,
            "label":     filename,
        }))
    kg.add_node(doc_id, NodeType.DOCUMENT, doc_id, label=filename)

    # ── Abrir PDF ─────────────────────────────────────────────
    doc = fitz.open(pdf_path)
    current_section_id:    Optional[str] = None
    current_section_title: Optional[str] = None

    for page_num in range(doc.page_count):
        page       = doc[page_num]
        page_id    = make_page_id(doc_id, page_num + 1)
        page_label = f"Página {page_num + 1} — {filename}"

        # ── Resume mode: pula páginas já processadas ──────────
        if resume and node_exists_in_chroma(collection, page_id):
            logger.info(f"   [resume] Pág {page_num+1} já existe — pulando")
            stats_out["skipped_pages"] += 1
            # Ainda precisa repovoar o grafo (não persiste entre runs)
            kg.add_node(page_id, NodeType.PAGE, doc_id, label=page_label)
            kg.add_edge(doc_id, page_id, EdgeType.DOCUMENT_HAS_PAGE)
            continue

        # ── Node: PAGE ────────────────────────────────────────
        chroma_upsert(collection, page_id, page_label, _enrich_metadata(page_label, {
            "node_type": NodeType.PAGE,
            "doc_id":    doc_id,
            "page_num":  str(page_num + 1),
            "label":     page_label,
        }))
        kg.add_node(page_id, NodeType.PAGE, doc_id, label=page_label)
        kg.add_edge(doc_id, page_id, EdgeType.DOCUMENT_HAS_PAGE)
        stats_out["pages"] += 1

        # ── Texto bruto + seção ───────────────────────────────
        raw_text     = page.get_text()
        cleaned_text = clean_text(raw_text)
        section_title = detect_section_title(cleaned_text)

        if section_title and section_title != current_section_title:
            current_section_title = section_title
            section_id            = make_section_id(doc_id, section_title)
            section_label         = f"Seção: {section_title}"

            if not kg.G.has_node(section_id):
                chroma_upsert(collection, section_id, section_title, _enrich_metadata(section_title, {
                    "node_type":     NodeType.SECTION,
                    "doc_id":        doc_id,
                    "section_title": section_title,
                    "label":         section_label,
                }))
                kg.add_node(section_id, NodeType.SECTION, doc_id, label=section_label)
                kg.add_edge(doc_id, section_id, EdgeType.DOCUMENT_HAS_SECTION)
                stats_out["sections"] += 1

            current_section_id = section_id
            kg.add_edge(section_id, page_id, EdgeType.SECTION_HAS_PAGE)

        # ── Nodes: CHUNKs ────────────────────────────────────
        chunks = split_into_chunks(cleaned_text, CHUNK_SIZE, CHUNK_OVERLAP, CHUNK_MIN_LENGTH)
        prev_chunk_id: Optional[str] = None
        chunk_ids_texts: list[tuple[str, str]] = []

        for ci, chunk_text in enumerate(chunks):
            chunk_id = make_chunk_id(page_id, ci)
            chroma_upsert(collection, chunk_id, chunk_text, _enrich_metadata(chunk_text, {
                "node_type":   NodeType.CHUNK,
                "doc_id":      doc_id,
                "page_num":    str(page_num + 1),
                "chunk_index": str(ci),
                "section":     current_section_title or "",
                "label":       f"Chunk {ci} · Pág {page_num + 1} · {filename}",
                "preview":     truncate(chunk_text, 120),
            }))
            kg.add_node(chunk_id, NodeType.CHUNK, doc_id,
                        label=f"Chunk p{page_num+1}c{ci}")
            kg.add_edge(page_id, chunk_id, EdgeType.PAGE_HAS_CHUNK)

            if prev_chunk_id:
                kg.add_edge(prev_chunk_id, chunk_id, EdgeType.CHUNK_NEXT)
            prev_chunk_id = chunk_id

            chunk_ids_texts.append((chunk_id, chunk_text))
            stats_out["chunks"] += 1

        # Embeddings em lote para todos os chunks da página
        if chunk_ids_texts:
            try:
                vectors = embed_texts_batch([t for _, t in chunk_ids_texts])
                for (cid, _), vec in zip(chunk_ids_texts, vectors):
                    faiss_index.add(cid, vec)
            except Exception as e:
                logger.error(f"Erro embedding chunks pág {page_num+1}: {e}")

        # ── Nodes: IMAGENs individuais ────────────────────────
        img_list   = page.get_images(full=True)
        n_images   = 0

        for img_idx, img_info in enumerate(img_list):
            try:
                xref = img_info[0]
                pix  = fitz.Pixmap(doc, xref)
                if pix.n > 4:
                    pix = fitz.Pixmap(fitz.csRGB, pix)

                if pix.width < IMG_MIN_SIZE or pix.height < IMG_MIN_SIZE:
                    pix = None
                    continue

                pil_img   = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                pil_img   = _resize_if_needed(pil_img)
                img_id    = make_image_id(page_id, img_idx)
                desc      = describe_visual(pil_img, "image")
                img_label = f"Figura {img_idx+1} · Pág {page_num+1} · {filename}"

                chroma_upsert(collection, img_id, desc, _enrich_metadata(desc, {
                    "node_type":   NodeType.IMAGE,
                    "doc_id":      doc_id,
                    "page_num":    str(page_num + 1),
                    "image_index": str(img_idx),
                    "img_width":   str(pil_img.width),
                    "img_height":  str(pil_img.height),
                    "label":       img_label,
                    "preview":     truncate(desc, 120),
                }))
                kg.add_node(img_id, NodeType.IMAGE, doc_id, label=img_label)
                kg.add_edge(page_id, img_id, EdgeType.PAGE_HAS_IMAGE)

                if chunk_ids_texts:
                    kg.add_edge(chunk_ids_texts[0][0], img_id, EdgeType.CHUNK_REF_IMAGE)

                try:
                    vec = embed_text(desc)
                    faiss_index.add(img_id, vec)
                except Exception as e:
                    logger.warning(f"Embedding imagem {img_id}: {e}")

                stats_out["images"] += 1
                n_images += 1
                pix = None

            except Exception as e:
                logger.warning(f"Erro na imagem {img_idx} pág {page_num+1}: {e}")

        # ── Nodes: TABELAs ───────────────────────────────────
        try:
            tables  = page.find_tables()
            n_tables = 0

            for tbl_idx, table in enumerate(tables):
                try:
                    rect     = table.bbox
                    clip     = fitz.Rect(rect)
                    pix      = page.get_pixmap(clip=clip, dpi=150)
                    pil_img  = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                    table_id    = make_table_id(page_id, tbl_idx)
                    desc        = describe_visual(pil_img, "table")
                    table_label = f"Tabela {tbl_idx+1} · Pág {page_num+1} · {filename}"

                    # Texto estruturado da tabela via pandas markdown
                    try:
                        df       = table.to_pandas()
                        raw_md   = df.to_markdown(index=False)
                        full_desc = f"{desc}\n\nDados brutos:\n{raw_md}"
                    except Exception:
                        full_desc = desc

                    chroma_upsert(collection, table_id, full_desc, _enrich_metadata(full_desc, {
                        "node_type":   NodeType.TABLE,
                        "doc_id":      doc_id,
                        "page_num":    str(page_num + 1),
                        "table_index": str(tbl_idx),
                        "label":       table_label,
                        "preview":     truncate(desc, 120),
                    }))
                    kg.add_node(table_id, NodeType.TABLE, doc_id, label=table_label)
                    kg.add_edge(page_id, table_id, EdgeType.PAGE_HAS_TABLE)

                    if chunk_ids_texts:
                        kg.add_edge(chunk_ids_texts[0][0], table_id, EdgeType.CHUNK_EXPLAINS_TABLE)

                    try:
                        vec = embed_text(full_desc)
                        faiss_index.add(table_id, vec)
                    except Exception as e:
                        logger.warning(f"Embedding tabela {table_id}: {e}")

                    stats_out["tables"] += 1
                    n_tables += 1
                    pix = None

                except Exception as e:
                    logger.warning(f"Erro na tabela {tbl_idx} pág {page_num+1}: {e}")

        except Exception as e:
            n_tables = 0
            logger.warning(f"find_tables() falhou pág {page_num+1}: {e}")

        # ── FALLBACK: descrição da página inteira ─────────────
        # Ativa quando: texto curto + sem imagens extraídas + sem tabelas
        # Captura: infográficos, layouts mistos, texto-sobre-imagem, etc.
        if (
            len(cleaned_text) < PAGE_FULL_VISION_THRESHOLD
            and n_images == 0
            and n_tables == 0
        ):
            try:
                full_desc  = describe_page_full(page, filename, page_num + 1)
                fullpg_id  = make_image_id(page_id, 9999)  # ID especial para página completa
                full_label = f"Visão Completa Pág {page_num+1} · {filename}"

                chroma_upsert(collection, fullpg_id, full_desc, _enrich_metadata(full_desc, {
                    "node_type":      NodeType.IMAGE,
                    "doc_id":         doc_id,
                    "page_num":       str(page_num + 1),
                    "image_index":    "full_page",
                    "label":          full_label,
                    "preview":        truncate(full_desc, 120),
                    "is_full_page":   "true",
                }))
                kg.add_node(fullpg_id, NodeType.IMAGE, doc_id, label=full_label)
                kg.add_edge(page_id, fullpg_id, EdgeType.PAGE_HAS_IMAGE)

                try:
                    vec = embed_text(full_desc)
                    faiss_index.add(fullpg_id, vec)
                except Exception as e:
                    logger.warning(f"Embedding página completa pág {page_num+1}: {e}")

                stats_out["full_page_visions"] += 1
                logger.info(f"   Pág {page_num+1}: fallback visão completa ativado")

            except Exception as e:
                logger.warning(f"Erro no fallback de visão completa pág {page_num+1}: {e}")

        logger.info(
            f"   Pág {page_num+1}/{doc.page_count}: "
            f"{len(chunks)} chunks, "
            f"{n_images} imgs, "
            f"{n_tables} tabelas"
            + (" [skip]" if resume and stats_out["skipped_pages"] > 0 else "")
        )

    doc.close()
    return stats_out


# ══════════════════════════════════════════════════════════════
# ENTRY POINT — chamado por main.py --ingest
# ══════════════════════════════════════════════════════════════

def run_ingestion(data_path: Path = DATA_PATH, reset: bool = False, resume: bool = False):
    """
    Processa todos os PDFs de data_path e constrói as três camadas:
    ChromaDB, FAISS e NetworkX.

    Args:
        data_path: pasta com os PDFs
        reset:     se True, recria a coleção do zero (incompatível com resume)
        resume:    se True, pula páginas já presentes no ChromaDB
    """
    ensure_dirs()

    if reset and resume:
        logger.warning("--reset e --resume são incompatíveis. Usando --reset.")
        resume = False

    pdf_files = list(data_path.glob("*.pdf"))
    if not pdf_files:
        logger.error(f"Nenhum PDF encontrado em '{data_path}'")
        sys.exit(1)

    logger.info(f"{len(pdf_files)} PDF(s) encontrado(s) em '{data_path}'")

    # ── Diagnóstico: ChromaDB ─────────────────────────────────
    if not test_chromadb_connection(str(CHROMA_PATH), COLLECTION_NAME):
        logger.error("ChromaDB com problema. Abortando ingestão.")
        sys.exit(1)

    # ── ChromaDB ──────────────────────────────────────────────
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    if reset:
        try:
            chroma_client.delete_collection(COLLECTION_NAME)
            logger.info(f"Collection '{COLLECTION_NAME}' removida para reinicialização")
        except Exception:
            pass

    collection = get_chroma_collection()

    # ── FAISS ─────────────────────────────────────────────────
    faiss_index = FaissIndex()

    # ── NetworkX ──────────────────────────────────────────────
    kg = KnowledgeGraph()

    # ── Processar PDFs ────────────────────────────────────────
    total_stats = {
        "chunks": 0, "images": 0, "tables": 0,
        "pages": 0, "sections": 0, "skipped_pages": 0,
        "full_page_visions": 0,
    }

    for pdf_path in sorted(pdf_files):
        try:
            stats = ingest_pdf(pdf_path, collection, faiss_index, kg, resume=resume)
            for k in total_stats:
                total_stats[k] += stats.get(k, 0)
        except Exception as e:
            logger.error(f"Erro ao processar '{pdf_path.name}': {e}")
            continue

    # ── Persistir ─────────────────────────────────────────────
    faiss_index.save()
    kg.save()

    # Visualizações do grafo físico (apenas para debug interno)
    try:
        kg.visualize_static()
        kg.visualize_interactive()
    except Exception as e:
        logger.warning(f"Erro ao gerar visualizações do grafo físico: {e}")

    # ── Validação pós-ingestão ────────────────────────────────
    val = validate_collection(collection, min_docs=1)
    if val["ok"]:
        logger.info(f"Validação OK: {val['count']} docs, query funcionando")
    else:
        logger.warning(f"Validação com problema: {val.get('error','?')}")

    # ── Resumo ────────────────────────────────────────────────
    print("\n" + "=" * 58)
    print("  INGESTAO CONCLUIDA")
    print("=" * 58)
    print(f"  PDFs processados:       {len(pdf_files)}")
    print(f"  Páginas processadas:    {total_stats['pages']}")
    print(f"  Páginas ignoradas:      {total_stats['skipped_pages']}")
    print(f"  Seções detectadas:      {total_stats['sections']}")
    print(f"  Chunks:                 {total_stats['chunks']}")
    print(f"  Imagens:                {total_stats['images']}")
    print(f"  Tabelas:                {total_stats['tables']}")
    print(f"  Visões de pág completa: {total_stats['full_page_visions']}")
    print(f"  Vetores FAISS:          {faiss_index.index.ntotal}")
    print(f"  ChromaDB (total docs):  {val['count']}")
    kg.print_stats()
    print(f"\n  Próximo passo: python main.py --semantic")
    print("=" * 58)