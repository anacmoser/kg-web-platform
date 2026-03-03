from typing import List, Dict, Any, Optional
import logging
import fitz
import numpy as np
from PIL import Image
import faiss
import chromadb
from pathlib import Path

from app.config import settings, NodeType, EdgeType
from app.utils import (
    retry_with_exponential_backoff,
    make_doc_id, make_section_id, make_page_id, make_chunk_id,
    make_image_id, make_table_id,
    clean_text, split_into_chunks, detect_section_title, truncate,
)

logger = logging.getLogger(__name__)

# Constants from embedding_multimodal
PAGE_FULL_VISION_THRESHOLD = 150
PAGE_RENDER_DPI = 200
IMG_MIN_SIZE = 80
IMG_MAX_SIZE = 1024
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200
CHUNK_MIN_LENGTH = 100

class FaissIndex:
    def __init__(self):
        self.index = faiss.IndexFlatIP(1536) # Default OpenAI dimension
        self.id_map: List[str] = []

    def add(self, node_id: str, vector: np.ndarray):
        vec = vector.astype(np.float32).reshape(1, -1)
        faiss.normalize_L2(vec)
        self.index.add(vec)
        self.id_map.append(node_id)

    def save(self):
        faiss.write_index(self.index, str(settings.FAISS_INDEX_FILE))
        import json
        with open(settings.FAISS_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(self.id_map, f, ensure_ascii=False)

    @classmethod
    def load(cls) -> "FaissIndex":
        fi = cls()
        fi.index = faiss.read_index(str(settings.FAISS_INDEX_FILE))
        import json
        with open(settings.FAISS_MAP_FILE, "r", encoding="utf-8") as f:
            fi.id_map = json.load(f)
        return fi

    @classmethod
    def exists(cls) -> bool:
        return settings.FAISS_INDEX_FILE.exists() and settings.FAISS_MAP_FILE.exists()

class StructuralExtractor:
    """
    Extrator Multimodal e Estrutural baseado na biblioteca PyMuPDF.
    Migrado de embedding_multimodal/embedding.py.
    """
    def __init__(self, openai_client):
        self.client = openai_client
        self.chroma_client = chromadb.PersistentClient(path=str(settings.CHROMA_PATH))
        self.collection = self.chroma_client.get_or_create_collection(
            name=settings.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        if FaissIndex.exists():
            self.faiss_index = FaissIndex.load()
        else:
            self.faiss_index = FaissIndex()

    def chroma_upsert(self, node_id: str, text: str, metadata: dict):
        self.collection.upsert(
            ids=[node_id],
            documents=[text],
            metadatas=[metadata],
        )

    def embed_texts_batch(self, texts: List[str]) -> List[np.ndarray]:
        vectors = []
        batch_size = 50
        for i in range(0, len(texts), batch_size):
            batch = [t[:8000] for t in texts[i : i + batch_size]]
            resp = self.client.embeddings.create(model="text-embedding-3-small", input=batch)
            vectors.extend([np.array(d.embedding, dtype=np.float32) for d in resp.data])
        return vectors

    @retry_with_exponential_backoff()
    def embed_text(self, text: str) -> np.ndarray:
        resp = self.client.embeddings.create(
            model="text-embedding-3-small",
            input=text[:8000],
        )
        return np.array(resp.data[0].embedding, dtype=np.float32)

    def _enrich_metadata(self, text: str, base_meta: dict) -> dict:
        import re
        base_meta["char_count"] = str(len(text))
        base_meta["word_count"] = str(len(text.split()))
        base_meta["has_numbers"] = str(bool(re.search(r"\d+[.,]?\d*", text)))
        return base_meta

    def _image_to_base64(self, img: Image.Image, fmt: str = "PNG") -> str:
        import io, base64
        buf = io.BytesIO()
        img.save(buf, format=fmt)
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _resize_if_needed(self, img: Image.Image, max_size: int = IMG_MAX_SIZE) -> Image.Image:
        if img.width > max_size or img.height > max_size:
            img = img.copy()
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        return img

    @retry_with_exponential_backoff()
    def describe_visual(self, img: Image.Image, element_type: str = "image") -> str:
        if element_type == "image":
            prompt = (
                "Descreva detalhadamente o conteúdo desta imagem para um sistema de busca. "
                "Inclua: dados numéricos visíveis, títulos, legendas, tendências, "
                "unidades de medida e qualquer informação textual presente. "
                "Seja objetivo e completo. Responda em português."
            )
        else:
            prompt = (
                "Descreva esta tabela em detalhes para um sistema de busca. "
                "Inclua: cabeçalhos, valores numéricos, unidades, totais e qualquer nota presente. "
                "Transcreva os dados principais de forma estruturada. Responda em português."
            )

        resp = self.client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{self._image_to_base64(img)}"
                    }},
                ],
            }],
            max_tokens=1024,
        )
        return resp.choices[0].message.content

    @retry_with_exponential_backoff()
    def describe_page_full(self, page: fitz.Page, filename: str, page_num: int) -> str:
        pix = page.get_pixmap(dpi=PAGE_RENDER_DPI)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        img = self._resize_if_needed(img, max_size=IMG_MAX_SIZE)

        prompt = (
            f"Esta é a página {page_num} do documento '{filename}'. "
            "Descreva completamente todo o conteúdo visual desta página para um sistema de busca: "
            "gráficos, tabelas, infográficos, imagens, diagramas, textos destacados, "
            "títulos, legendas e qualquer informação relevante. "
            "Inclua todos os dados numéricos, percentuais e tendências visíveis. "
            "Responda em português, de forma objetiva e detalhada."
        )

        resp = self.client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/png;base64,{self._image_to_base64(img)}"
                    }},
                ],
            }],
            max_tokens=2048,
        )
        return resp.choices[0].message.content

    def ingest_pdf(self, pdf_path: Path, kg) -> List[Dict[str, Any]]:
        """
        Processa o PDF extraindo as estruturas e retorna uma lista de dicionarios dos chunks
        no formato que o orchestrator (OntologyBuilder) espera.
        """
        filename = pdf_path.name
        doc_id = make_doc_id(filename)
        all_returned_chunks = []
        
        self.chroma_upsert(doc_id, filename, self._enrich_metadata(filename, {
            "node_type": NodeType["DOCUMENT"],
            "doc_id": doc_id,
            "filename": filename,
            "label": filename,
        }))
        kg.add_node(doc_id, NodeType["DOCUMENT"], label=filename)
        
        try:
            doc = fitz.open(pdf_path)
        except Exception as e:
            logger.error(f"Failed to open PDF {pdf_path}: {e}")
            return []

        current_section_id: Optional[str] = None
        current_section_title: Optional[str] = None

        total_chunk_count = 0

        for page_num in range(doc.page_count):
            page = doc[page_num]
            page_id = make_page_id(doc_id, page_num + 1)
            page_label = f"Página {page_num + 1} — {filename}"

            self.chroma_upsert(page_id, page_label, self._enrich_metadata(page_label, {
                "node_type": NodeType["PAGE"],
                "doc_id": doc_id,
                "page_num": str(page_num + 1),
                "label": page_label,
            }))
            kg.add_node(page_id, NodeType["PAGE"], label=page_label)
            kg.add_edge(doc_id, page_id, EdgeType["CONTAINS"])

            raw_text = page.get_text()
            cleaned_text = clean_text(raw_text)
            section_title = detect_section_title(cleaned_text)

            if section_title and section_title != current_section_title:
                current_section_title = section_title
                section_id = make_section_id(doc_id, section_title)
                section_label = f"Seção: {section_title}"

                if not kg.exists(section_id):
                    self.chroma_upsert(section_id, section_title, self._enrich_metadata(section_title, {
                        "node_type": NodeType["SECTION"],
                        "doc_id": doc_id,
                        "section_title": section_title,
                        "label": section_label,
                    }))
                    kg.add_node(section_id, NodeType["SECTION"], label=section_label)
                    kg.add_edge(doc_id, section_id, EdgeType["CONTAINS"])

                current_section_id = section_id
                kg.add_edge(section_id, page_id, EdgeType["CONTAINS"])

            # Chunks
            chunks = split_into_chunks(cleaned_text, CHUNK_SIZE, CHUNK_OVERLAP, CHUNK_MIN_LENGTH)
            prev_chunk_id: Optional[str] = None
            chunk_ids_texts: List[tuple[str, str]] = []

            for ci, chunk_text in enumerate(chunks):
                chunk_id = make_chunk_id(page_id, ci)
                self.chroma_upsert(chunk_id, chunk_text, self._enrich_metadata(chunk_text, {
                    "node_type": NodeType["CHUNK"],
                    "doc_id": doc_id,
                    "page_num": str(page_num + 1),
                    "chunk_index": str(ci),
                    "section": current_section_title or "",
                    "label": f"Chunk {ci} · Pág {page_num + 1} · {filename}",
                    "preview": truncate(chunk_text, 120),
                }))
                kg.add_node(chunk_id, NodeType["CHUNK"], label=f"Chunk p{page_num+1}c{ci}")
                kg.add_edge(page_id, chunk_id, EdgeType["CONTAINS"])

                if prev_chunk_id:
                    kg.add_edge(prev_chunk_id, chunk_id, EdgeType["PRECEDES"])
                prev_chunk_id = chunk_id

                chunk_ids_texts.append((chunk_id, chunk_text))
                
                # Format required by the semantic part of the pipeline:
                all_returned_chunks.append({
                    "id": chunk_id,
                    "index": total_chunk_count,
                    "text": chunk_text,
                    "tokens": len(chunk_text.split()),
                    "metadata": {"doc_id": doc_id, "page_num": str(page_num + 1)},
                    "type": "text"
                })
                total_chunk_count += 1

            if chunk_ids_texts:
                try:
                    vectors = self.embed_texts_batch([t for _, t in chunk_ids_texts])
                    for (cid, _), vec in zip(chunk_ids_texts, vectors):
                        self.faiss_index.add(cid, vec)
                except Exception as e:
                    logger.error(f"Erro embedding chunks pág {page_num+1}: {e}")

            # Images
            n_images = 0
            img_list = page.get_images(full=True)
            for img_idx, img_info in enumerate(img_list):
                try:
                    xref = img_info[0]
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n > 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    if pix.width < IMG_MIN_SIZE or pix.height < IMG_MIN_SIZE:
                        continue

                    pil_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    pil_img = self._resize_if_needed(pil_img)
                    img_id = make_image_id(page_id, img_idx)
                    desc = self.describe_visual(pil_img, "image")
                    img_label = f"Figura {img_idx+1} · Pág {page_num+1} · {filename}"

                    self.chroma_upsert(img_id, desc, self._enrich_metadata(desc, {
                        "node_type": NodeType["IMAGE"],
                        "doc_id": doc_id,
                        "page_num": str(page_num + 1),
                        "image_index": str(img_idx),
                        "img_width": str(pil_img.width),
                        "img_height": str(pil_img.height),
                        "label": img_label,
                        "preview": truncate(desc, 120),
                    }))
                    kg.add_node(img_id, NodeType["IMAGE"], label=img_label)
                    kg.add_edge(page_id, img_id, EdgeType["CONTAINS"])
                    
                    if chunk_ids_texts:
                        kg.add_edge(chunk_ids_texts[0][0], img_id, EdgeType["SIMILAR_TO"])

                    try:
                        vec = self.embed_text(desc)
                        self.faiss_index.add(img_id, vec)
                    except Exception as e:
                        logger.warning(f"Embedding imagem {img_id}: {e}")
                        
                    n_images += 1
                except Exception as e:
                    logger.warning(f"Erro imagem {img_idx} pag {page_num+1}: {e}")
            
            # Tables
            n_tables = 0
            try:
                tables = page.find_tables()
                for tbl_idx, table in enumerate(tables):
                    try:
                        clip = fitz.Rect(table.bbox)
                        pix = page.get_pixmap(clip=clip, dpi=150)
                        pil_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                        table_id = make_table_id(page_id, tbl_idx)
                        desc = self.describe_visual(pil_img, "table")
                        table_label = f"Tabela {tbl_idx+1} · Pág {page_num+1} · {filename}"

                        try:
                            df = table.to_pandas()
                            raw_md = df.to_markdown(index=False)
                            full_desc = f"{desc}\n\nDados brutos:\n{raw_md}"
                        except Exception:
                            full_desc = desc

                        self.chroma_upsert(table_id, full_desc, self._enrich_metadata(full_desc, {
                            "node_type": NodeType["TABLE"],
                            "doc_id": doc_id,
                            "page_num": str(page_num + 1),
                            "table_index": str(tbl_idx),
                            "label": table_label,
                            "preview": truncate(desc, 120),
                        }))
                        kg.add_node(table_id, NodeType["TABLE"], label=table_label)
                        kg.add_edge(page_id, table_id, EdgeType["CONTAINS"])
                        
                        if chunk_ids_texts:
                            kg.add_edge(chunk_ids_texts[0][0], table_id, EdgeType["SIMILAR_TO"])

                        try:
                            vec = self.embed_text(full_desc)
                            self.faiss_index.add(table_id, vec)
                        except Exception as e:
                            logger.warning(f"Embedding tabela {table_id}: {e}")
                            
                        n_tables += 1
                    except Exception as e:
                        logger.warning(f"Erro na tabela {tbl_idx}: {e}")
            except Exception as e:
                pass
            
            # Fallback
            if len(cleaned_text) < PAGE_FULL_VISION_THRESHOLD and n_images == 0 and n_tables == 0:
                try:
                    full_desc = self.describe_page_full(page, filename, page_num + 1)
                    fullpg_id = make_image_id(page_id, 9999) 
                    full_label = f"Visão Completa Pág {page_num+1} · {filename}"

                    self.chroma_upsert(fullpg_id, full_desc, self._enrich_metadata(full_desc, {
                        "node_type": NodeType["IMAGE"],
                        "doc_id": doc_id,
                        "page_num": str(page_num + 1),
                        "image_index": "full_page",
                        "label": full_label,
                        "preview": truncate(full_desc, 120),
                        "is_full_page": "true",
                    }))
                    kg.add_node(fullpg_id, NodeType["IMAGE"], label=full_label)
                    kg.add_edge(page_id, fullpg_id, EdgeType["CONTAINS"])

                    try:
                        vec = self.embed_text(full_desc)
                        self.faiss_index.add(fullpg_id, vec)
                    except Exception:
                        pass
                except Exception:
                    pass

        self.faiss_index.save()
        doc.close()
        logger.info(f"Structural Pipeline completed for {filename}. Returning {len(all_returned_chunks)} chunks.")
        return all_returned_chunks
