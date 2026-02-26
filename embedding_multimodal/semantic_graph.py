"""
semantic_graph.py — Pipeline 2: Grafo Semântico

Responsabilidades:
  - Ler chunks já processados do ChromaDB[graphrag_docs] (Pipeline 1)
  - Extrair entidades estruturadas: Label → Entity → Property → Relationship
  - Normalizar entidades (agrupar aliases com contexto)
  - Filtrar nodes ambíguos (rebaixar a Property quando não autoexplicativo)
  - Persistir textos contextuais em ChromaDB[graphrag_semantic]
  - Construir SemanticKnowledgeGraph (NetworkX)
  - Gerar visualização interativa HTML (vis-network)

Este arquivo NÃO processa PDFs — usa apenas os chunks do Pipeline 1.
É a fonte de /graph/view, table_graphics e da ferramenta semântica do agente.
"""

import json
import logging
import pickle
import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

import chromadb
import networkx as nx
from openai import OpenAI

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config import (
    OPENAI_API_KEY, LLM_MODEL, LLM_MINI_MODEL,
    CHROMA_PATH, COLLECTION_NAME, COLLECTION_SEMANTIC_NAME,
    SEMANTIC_GRAPH_PICKLE, SEMANTIC_GRAPH_GML,
    GRAPH_HTML_FILE, GRAPH_PNG_FILE,
    SemanticNodeType, SemanticEdgeType,
    SEMANTIC_NODE_COLORS, SEMANTIC_BATCH_SIZE,
    SEMANTIC_NORMALIZE_BATCH, SEMANTIC_MIN_RECURRENCE,
    ensure_dirs,
)
from utils import (
    retry_with_exponential_backoff,
    make_label_id, make_entity_id, make_property_id,
    truncate, normalize_str,
)

logger = logging.getLogger(__name__)
client = OpenAI(api_key=OPENAI_API_KEY)


# ══════════════════════════════════════════════════════════════
# PARTE A — EXTRAÇÃO DE ENTIDADES
# Chamada determinística ao LLM por lote de chunks
# ══════════════════════════════════════════════════════════════

EXTRACTION_PROMPT = """Você é um extrator de entidades para construção de Knowledge Graph.

Analise os trechos de texto abaixo e extraia todas as entidades relevantes.

REGRAS OBRIGATÓRIAS:
1. Label deve ser uma categoria abstrata: Indicador, Empresa, Regiao, Data, Politica, Produto, Conceito, Organizacao, Pessoa
2. canonical_name deve ser o nome mais completo e não ambíguo da entidade
3. Properties são atributos mensuráveis: valores, unidades, datas, fontes
4. Relationships conectam esta entidade a outra entidade do texto
5. NÃO extraia entidades genéricas ou que só fazem sentido dentro da frase
6. Uma entidade deve ser compreensível isoladamente, sem o texto de origem

TIPOS DE RELACIONAMENTOS PERMITIDOS:
impacta, mede, pertence_a, produz, cresce_em, declina_em, comparado_com, depende_de, relacionado_com

Retorne APENAS JSON válido, sem markdown, sem explicações:
{{
  "entities": [
    {{
      "label": "Indicador",
      "name": "PIB",
      "canonical_name": "PIB Brasil 2024",
      "properties": {{
        "valor": "3.2%",
        "unidade": "percentual",
        "periodo": "2024",
        "fonte": "IBGE"
      }},
      "relationships": [
        {{"type": "mede", "target": "Crescimento Economico"}},
        {{"type": "impacta", "target": "Balanca Comercial"}}
      ],
      "context_summary": "O PIB brasileiro cresceu 3.2% em 2024 segundo o IBGE, impulsionado pelo setor de servicos."
    }}
  ]
}}

Se nenhuma entidade relevante for encontrada, retorne: {{"entities": []}}

TRECHOS PARA ANÁLISE:
{chunks_text}
"""

NORMALIZATION_PROMPT = """Você é um normalizador de entidades para Knowledge Graph.

Abaixo está uma lista de entidades extraídas de documentos. Sua tarefa é identificar
quais entidades representam o mesmo conceito e agrupá-las sob um nome canônico único.

REGRAS:
1. Use o contexto fornecido para decidir se são a mesma entidade
2. "VW", "Volkswagen", "Volkswagen do Brasil" podem ser a mesma OU entidades distintas — use o contexto
3. "PIB 2024" e "PIB 2023" são entidades DIFERENTES (períodos distintos)
4. Mantenha aliases como metadado, não os descarte
5. Se a entidade já está bem normalizada, mantenha-a como está

Retorne APENAS JSON válido:
{{
  "groups": [
    {{
      "canonical_name": "Volkswagen do Brasil",
      "label": "Empresa",
      "aliases": ["VW", "Volkswagen", "VW Brasil"],
      "entity_ids": ["id1", "id2", "id3"]
    }}
  ]
}}

ENTIDADES PARA NORMALIZAR:
{entities_json}
"""

FILTER_PROMPT = """Você é um filtro de qualidade para Knowledge Graph.

Para cada entidade abaixo, decida se ela deve ser:
- "keep": entidade válida, compreensível fora do contexto original
- "property": não é uma entidade independente, é um atributo de outra entidade
- "discard": muito genérica, ambígua ou sem significado independente

CRITÉRIOS para "keep":
- O nome faz sentido sem o texto de origem
- É uma entidade recorrente e referenciável
- Tem identidade própria no domínio

CRITÉRIOS para "property":
- É um valor ou atributo (ex: "3.2%", "R$ 50 bilhoes")
- Só faz sentido ligada a outra entidade

CRITÉRIOS para "discard":
- Pronomes, artigos, termos genéricos ("o setor", "a empresa")
- Nomes que só fazem sentido dentro da frase

Retorne APENAS JSON válido:
{{
  "decisions": [
    {{"entity_id": "id1", "decision": "keep", "reason": "empresa com nome proprio"}},
    {{"entity_id": "id2", "decision": "property", "reason": "e um valor numerico"}},
    {{"entity_id": "id3", "decision": "discard", "reason": "termo generico"}}
  ]
}}

ENTIDADES PARA AVALIAR:
{entities_json}
"""


@retry_with_exponential_backoff()
def _call_llm(prompt: str, model: str = LLM_MINI_MODEL) -> dict:
    """Chamada LLM determinística que retorna JSON."""
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=4096,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content
    return json.loads(raw)


def extract_entities_from_chunks(chunks: list[dict]) -> list[dict]:
    """
    Extrai entidades de um lote de chunks.
    Cada chunk: {"id": str, "text": str, "metadata": dict}
    Retorna lista de entidades com chunk_ids de origem.
    """
    chunks_text = ""
    for i, chunk in enumerate(chunks):
        meta = chunk.get("metadata", {})
        source = f"{meta.get('doc_id','?')} · Pág {meta.get('page_num','?')}"
        chunks_text += f"\n--- Trecho {i+1} [{source}] ---\n{chunk['text'][:1000]}\n"

    prompt = EXTRACTION_PROMPT.format(chunks_text=chunks_text)

    try:
        result = _call_llm(prompt, model=LLM_MINI_MODEL)
        entities = result.get("entities", [])
    except Exception as e:
        logger.warning(f"Erro na extracao de entidades: {e}")
        return []

    # Anotar chunk_ids de origem em cada entidade
    chunk_ids = [c["id"] for c in chunks]
    for ent in entities:
        ent["source_chunk_ids"] = chunk_ids
        ent["source_docs"] = list({
            c.get("metadata", {}).get("doc_id", "") for c in chunks
        })

    return entities


# ══════════════════════════════════════════════════════════════
# PARTE B — NORMALIZAÇÃO
# Agrupa aliases, elege nome canônico por lote
# ══════════════════════════════════════════════════════════════

def normalize_entities(all_entities: list[dict]) -> list[dict]:
    """
    Agrupa entidades que representam o mesmo conceito.
    Processa em lotes de SEMANTIC_NORMALIZE_BATCH entidades.
    Retorna lista de entidades com canonical_name definido.
    """
    if not all_entities:
        return []

    # Pré-agrupamento barato por similaridade de nome (sem LLM)
    # para reduzir o número de chamadas
    pre_groups: dict[str, list[dict]] = defaultdict(list)
    for ent in all_entities:
        key = normalize_str(ent.get("canonical_name", ent.get("name", "")))
        pre_groups[key].append(ent)

    # Para grupos com múltiplos membros, usar LLM para confirmar
    normalized: list[dict] = []

    batch: list[dict] = []
    batch_keys: list[str] = []

    for key, group in pre_groups.items():
        # Representa o grupo pelo primeiro membro + lista de aliases
        rep = dict(group[0])
        rep["_group_key"] = key
        rep["_aliases_found"] = [
            g.get("canonical_name", g.get("name", "")) for g in group[1:]
        ]
        rep["_all_source_chunk_ids"] = list({
            cid for g in group for cid in g.get("source_chunk_ids", [])
        })
        batch.append(rep)
        batch_keys.append(key)

        if len(batch) >= SEMANTIC_NORMALIZE_BATCH:
            normalized.extend(_normalize_batch(batch))
            batch = []
            batch_keys = []

    if batch:
        normalized.extend(_normalize_batch(batch))

    return normalized


def _normalize_batch(batch: list[dict]) -> list[dict]:
    """Chama LLM para normalizar um lote de entidades candidatas."""
    entities_for_prompt = [
        {
            "entity_id":      e.get("_group_key", ""),
            "label":          e.get("label", ""),
            "canonical_name": e.get("canonical_name", e.get("name", "")),
            "aliases":        e.get("_aliases_found", []),
            "context":        e.get("context_summary", "")[:200],
        }
        for e in batch
    ]

    prompt = NORMALIZATION_PROMPT.format(
        entities_json=json.dumps(entities_for_prompt, ensure_ascii=False, indent=2)
    )

    try:
        result  = _call_llm(prompt, model=LLM_MINI_MODEL)
        groups  = result.get("groups", [])
        key_map = {g["entity_ids"][0]: g for g in groups if g.get("entity_ids")}
    except Exception as e:
        logger.warning(f"Erro na normalizacao: {e} — usando entidades sem normalizar")
        return batch

    normalized = []
    for ent in batch:
        key   = ent.get("_group_key", "")
        group = key_map.get(key)
        if group:
            ent = dict(ent)
            ent["canonical_name"] = group.get("canonical_name", ent.get("canonical_name", ""))
            ent["label"]          = group.get("label", ent.get("label", ""))
            ent["aliases"]        = group.get("aliases", [])
        normalized.append(ent)

    return normalized


# ══════════════════════════════════════════════════════════════
# PARTE C — FILTRO DE QUALIDADE
# Remove ou rebaixa nodes ambíguos
# ══════════════════════════════════════════════════════════════

def filter_ambiguous_nodes(entities: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Filtra entidades em três categorias via LLM:
      - keep:     promovida a node no grafo semântico
      - property: rebaixada a atributo de outro node
      - discard:  descartada

    Retorna (kept, properties).
    """
    if not entities:
        return [], []

    entities_for_prompt = [
        {
            "entity_id":      make_entity_id(e.get("label",""), e.get("canonical_name","")),
            "label":          e.get("label", ""),
            "canonical_name": e.get("canonical_name", e.get("name", "")),
            "context":        e.get("context_summary", "")[:150],
        }
        for e in entities
    ]

    # Processar em lotes de 30
    decisions: dict[str, str] = {}
    batch_size = 30

    for i in range(0, len(entities_for_prompt), batch_size):
        batch = entities_for_prompt[i : i + batch_size]
        prompt = FILTER_PROMPT.format(
            entities_json=json.dumps(batch, ensure_ascii=False, indent=2)
        )
        try:
            result = _call_llm(prompt, model=LLM_MINI_MODEL)
            for dec in result.get("decisions", []):
                decisions[dec["entity_id"]] = dec["decision"]
        except Exception as e:
            logger.warning(f"Erro no filtro: {e} — mantendo todas as entidades do lote")
            for item in batch:
                decisions[item["entity_id"]] = "keep"

    kept, properties = [], []
    for ent in entities:
        eid      = make_entity_id(ent.get("label",""), ent.get("canonical_name",""))
        decision = decisions.get(eid, "keep")
        if decision == "keep":
            kept.append(ent)
        elif decision == "property":
            properties.append(ent)
        # discard: ignorado

    logger.info(f"Filtro: {len(kept)} mantidos, {len(properties)} rebaixados a property, "
                f"{len(entities)-len(kept)-len(properties)} descartados")
    return kept, properties


# ══════════════════════════════════════════════════════════════
# PARTE D — SemanticKnowledgeGraph
# NetworkX do grafo semântico público
# ══════════════════════════════════════════════════════════════

class SemanticKnowledgeGraph:
    """
    Grafo semântico público: Label → Entity → Property → Relationship.
    É a fonte de /graph/view, table_graphics e ferramenta do agente.
    """

    def __init__(self):
        self.G: nx.DiGraph = nx.DiGraph()

    # ── Construção ────────────────────────────────────────────

    def add_label(self, label_name: str) -> str:
        lid = make_label_id(label_name)
        if not self.G.has_node(lid):
            self.G.add_node(lid,
                node_type=SemanticNodeType.LABEL,
                label=label_name,
                name=label_name,
            )
        return lid

    def add_entity(self, entity: dict) -> str:
        label         = entity.get("label", "Conceito")
        canonical     = entity.get("canonical_name", entity.get("name", ""))
        eid           = make_entity_id(label, canonical)
        lid           = self.add_label(label)

        aliases       = entity.get("aliases", [])
        context       = entity.get("context_summary", "")
        source_docs   = entity.get("source_docs", [])
        source_chunks = entity.get("_all_source_chunk_ids", entity.get("source_chunk_ids", []))

        self.G.add_node(eid,
            node_type=SemanticNodeType.ENTITY,
            label=canonical,
            name=canonical,
            category=label,
            aliases=", ".join(aliases),
            context=context[:300],
            source_docs=", ".join(source_docs),
            source_chunks=", ".join(source_chunks[:5]),
        )
        self.G.add_edge(lid, eid, edge_type=SemanticEdgeType.LABEL_HAS_ENTITY)
        return eid

    def add_property(self, entity_id: str, key: str, value: str):
        pid = make_property_id(entity_id, key)
        label_text = f"{key}: {value}"
        self.G.add_node(pid,
            node_type=SemanticNodeType.PROPERTY,
            label=label_text,
            name=label_text,
            prop_key=key,
            prop_value=value,
        )
        self.G.add_edge(entity_id, pid, edge_type=SemanticEdgeType.ENTITY_HAS_PROPERTY)

    def add_relationship(self, src_entity_id: str, rel_type: str, target_name: str,
                         target_label: str = "Conceito"):
        """Adiciona aresta semântica entre duas entidades."""
        # Garantir que o target existe como node (pode ser novo)
        target_eid = make_entity_id(target_label, target_name)
        if not self.G.has_node(target_eid):
            lid = self.add_label(target_label)
            self.G.add_node(target_eid,
                node_type=SemanticNodeType.ENTITY,
                label=target_name,
                name=target_name,
                category=target_label,
                aliases="",
                context="Entidade referenciada por relacao.",
                source_docs="",
                source_chunks="",
            )
            self.G.add_edge(lid, target_eid, edge_type=SemanticEdgeType.LABEL_HAS_ENTITY)

        # Mapear tipo de relação para EdgeType
        rel_map = {
            "impacta":        SemanticEdgeType.IMPACTA,
            "mede":           SemanticEdgeType.MEDE,
            "pertence_a":     SemanticEdgeType.PERTENCE_A,
            "produz":         SemanticEdgeType.PRODUZ,
            "cresce_em":      SemanticEdgeType.CRESCE_EM,
            "declina_em":     SemanticEdgeType.DECLINA_EM,
            "comparado_com":  SemanticEdgeType.COMPARADO_COM,
            "depende_de":     SemanticEdgeType.DEPENDE_DE,
        }
        edge_type = rel_map.get(rel_type.lower(), SemanticEdgeType.RELACIONADO_COM)

        if not self.G.has_edge(src_entity_id, target_eid):
            self.G.add_edge(src_entity_id, target_eid, edge_type=edge_type)

    # ── Consulta ─────────────────────────────────────────────

    def find_entity(self, query: str) -> list[str]:
        """Busca nodes de entidade cujo nome contenha o termo."""
        q = query.lower()
        return [
            nid for nid, data in self.G.nodes(data=True)
            if data.get("node_type") == SemanticNodeType.ENTITY
            and q in data.get("name", "").lower()
        ]

    def get_entity_context(self, entity_id: str, hop_depth: int = 1) -> dict:
        """Retorna node + vizinhos imediatos como contexto."""
        if not self.G.has_node(entity_id):
            return {}
        data = dict(self.G.nodes[entity_id])
        neighbors = []
        for nid in list(self.G.successors(entity_id)) + list(self.G.predecessors(entity_id)):
            ndata   = self.G.nodes[nid]
            et      = self.G.edges.get((entity_id, nid), self.G.edges.get((nid, entity_id), {}))
            neighbors.append({
                "id":        nid,
                "name":      ndata.get("name", ""),
                "node_type": ndata.get("node_type", ""),
                "edge_type": et.get("edge_type", ""),
            })
        data["neighbors"] = neighbors
        return data

    def stats(self) -> dict:
        type_counts: dict[str, int] = {}
        for _, d in self.G.nodes(data=True):
            t = d.get("node_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        edge_counts: dict[str, int] = {}
        for _, _, d in self.G.edges(data=True):
            et = d.get("edge_type", "unknown")
            edge_counts[et] = edge_counts.get(et, 0) + 1

        return {
            "total_nodes":   self.G.number_of_nodes(),
            "total_edges":   self.G.number_of_edges(),
            "nodes_by_type": type_counts,
            "edges_by_type": edge_counts,
            "density":       nx.density(self.G),
        }

    def is_empty(self) -> bool:
        return self.G.number_of_nodes() == 0

    # ── Persistência ─────────────────────────────────────────

    def save(self):
        ensure_dirs()
        with open(SEMANTIC_GRAPH_PICKLE, "wb") as f:
            pickle.dump(self.G, f)
        logger.info(f"Grafo semantico salvo: {self.G.number_of_nodes()} nodes")

        # GML (portável)
        try:
            G_s = nx.DiGraph()
            for nid, data in self.G.nodes(data=True):
                G_s.add_node(nid, **{k: str(v) for k, v in data.items()})
            for u, v, data in self.G.edges(data=True):
                G_s.add_edge(u, v, **{k: str(v) for k, v in data.items()})
            nx.write_gml(G_s, str(SEMANTIC_GRAPH_GML))
        except Exception as e:
            logger.warning(f"GML nao salvo: {e}")

    @classmethod
    def load(cls) -> "SemanticKnowledgeGraph":
        if not SEMANTIC_GRAPH_PICKLE.exists():
            raise FileNotFoundError(
                "Grafo semantico nao encontrado. Execute: python main.py --semantic"
            )
        skg = cls()
        with open(SEMANTIC_GRAPH_PICKLE, "rb") as f:
            skg.G = pickle.load(f)
        logger.info(f"Grafo semantico carregado: {skg.G.number_of_nodes()} nodes, "
                    f"{skg.G.number_of_edges()} arestas")
        return skg

    @classmethod
    def exists(cls) -> bool:
        return SEMANTIC_GRAPH_PICKLE.exists()

    # ── Visualização ─────────────────────────────────────────

    def visualize_interactive(self, caminho: Path = GRAPH_HTML_FILE):
        """
        Gera dois arquivos HTML para o Pipeline 2 (Semântico):
        1. graph_interactive.html: O grafo semântico interativo.
        2. graph_landing.html: A Dashboard Analítica com 12 abas x 4 gráficos + Tabela de Entidades + Chatbot.
        """
        ensure_dirs()
        G = self.G

        if G.number_of_nodes() == 0:
            logger.warning("Grafo semantico vazio — HTML ignorado.")
            return

        import json as _json
        from config import GRAPH_LANDING_FILE
        from table_graphics import GraphAnalyzer

        analyzer = GraphAnalyzer(G)
        nodes_table_data = analyzer.get_nodes_table_html()
        charts_data = analyzer.get_charts_data()

        # ── Construir listas de nodes e arestas ──────────────
        nodes_list = []
        for nid in G.nodes():
            data   = G.nodes[nid]
            ntype  = data.get("node_type", "")
            color  = SEMANTIC_NODE_COLORS.get(ntype, "#95A5A6")
            name   = data.get("name", nid)
            label  = name if len(name) <= 30 else name[:27] + "..."
            deg    = G.degree(nid)
            size   = {"label": 30, "entity": 20, "property": 12}.get(ntype, 15)
            size  += min(deg * 3, 20)
            
            shape = {"label": "diamond", "entity": "dot", "property": "square"}.get(ntype, "dot")
            
            nodes_list.append({
                "id":    nid,
                "label": label,
                "title": f"{name}<br>Tipo: {ntype}<br>Categoria: {data.get('category','')}<br>Conexoes: {deg}",
                "color": {
                    "background": color,
                    "border":     "#ffffff",
                    "highlight":  {"background": color, "border": "#ffff88"},
                    "hover":      {"background": color, "border": "#88ffff"},
                },
                "size":  size,
                "shape": shape,
                "font":  {"color": "#ffffff", "size": 11},
            })

        edges_list = []
        for i, (u, v, data) in enumerate(G.edges(data=True)):
            et = data.get("edge_type", "")
            edges_list.append({
                "id":     i,
                "from":   u,
                "to":     v,
                "label":  et,
                "title":  et,
                "color":  {"color": "#6666aa", "highlight": "#aaaaff", "hover": "#8888cc"},
                "arrows": {"to": {"enabled": True, "scaleFactor": 0.6}},
                "font":   {"color": "#999999", "size": 9, "align": "middle", "strokeWidth": 0},
                "smooth": {"type": "curvedCW", "roundness": 0.15},
            })

        nodes_json = _json.dumps(nodes_list, ensure_ascii=False)
        edges_json = _json.dumps(edges_list, ensure_ascii=False)

        # ── Legenda ──────────────────────────────────────────
        legend_html = ""
        for ntype, color in SEMANTIC_NODE_COLORS.items():
            legend_html += (
                f'<div style="display:flex;align-items:center;gap:8px;margin:5px 0">'
                f'<div style="width:13px;height:13px;border-radius:50%;'
                f'background:{color};flex-shrink:0;border:1px solid #fff4"></div>'
                f'<span>{ntype}</span></div>'
            )

        stats  = self.stats()
        n_nodes = stats["total_nodes"]
        n_edges = stats["total_edges"]
        density = stats["density"]

        # ── HTML 1: GRAFO INTERATIVO PURO ────────────────────
        html_graph = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GraphRAG — Semantic Graph</title>
  <script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{
      height: 100%; background: #0d0d1a; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; font-size: 13px;
    }}
    #app {{ display: flex; flex-direction: column; height: 100vh; }}
    #header {{ display: flex; align-items: center; justify-content: space-between; padding: 8px 16px; background: #12122a; border-bottom: 1px solid #2a2a4a; flex-shrink: 0; gap: 12px; }}
    #header h1 {{ font-size: 0.95em; font-weight: 600; color: #4ECDC4; white-space: nowrap; }}
    #stats-bar {{ font-size: 0.78em; color: #888; white-space: nowrap; }}
    #stats-bar b {{ color: #4ECDC4; }}
    #search-wrap {{ display: flex; align-items: center; gap: 6px; flex-shrink: 0; }}
    #search {{ padding: 5px 10px; background: #1e1e36; border: 1px solid #3a3a5a; border-radius: 4px; color: #e0e0e0; font-size: 0.82em; width: 160px; outline: none; }}
    #btn-reset {{ padding: 5px 10px; background: #1e1e36; border: 1px solid #3a3a5a; border-radius: 4px; color: #aaa; font-size: 0.78em; cursor: pointer; }}
    #body {{ display: flex; flex: 1; overflow: hidden; }}
    #graph-container {{ flex: 1; position: relative; background: #0d0d1a; }}
    #graph-canvas {{ width: 100%; height: 100%; }}
    #sidebar {{ width: 210px; background: #12122a; border-left: 1px solid #2a2a4a; padding: 14px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px; }}
    .sidebar-section h3 {{ font-size: 0.7em; font-weight: 700; text-transform: uppercase; letter-spacing: 1.2px; color: #555577; margin-bottom: 8px; border-bottom: 1px solid #1e1e36; }}
    #legend {{ font-size: 0.8em; color: #ccc; }}
    #node-info {{ background: #0d0d1a; border-radius: 6px; padding: 10px; font-size: 0.78em; color: #999; border: 1px solid #1e1e36; }}
    #node-info .name  {{ color: #4ECDC4; font-weight: 600; }}
  </style>
</head>
<body>
<div id="app">
  <div id="header">
    <div style="display: flex; flex-direction: column; gap: 2px;">
      <h1>GraphRAG &mdash; Semantic Graph</h1>
      <a href="/graph" style="color: #666; text-decoration: none; font-size: 0.7em; letter-spacing: 0.5px; display: flex; align-items: center; gap: 4px;">
        &larr; VOLTAR PARA DASHBOARD
      </a>
    </div>
    <div id="stats-bar">
      <b>{n_nodes}</b> nodes &nbsp;|&nbsp; <b>{n_edges}</b> arestas &nbsp;|&nbsp; densidade: <b>{density:.4f}</b>
    </div>
    <div id="search-wrap">
      <input type="text" id="search" placeholder="Buscar entidade...">
      <div id="btn-reset" onclick="resetView()">RESET</div>
    </div>
  </div>
  <div id="body">
    <div id="graph-container"><div id="graph-canvas"></div></div>
    <div id="sidebar">
      <div class="sidebar-section"><h3>Legenda Semântica</h3><div id="legend">{legend_html}</div></div>
      <div class="sidebar-section"><h3>Detalhes Entidade</h3><div id="node-info">Clique em uma entidade.</div></div>
    </div>
  </div>
</div>
<script>
  var RAW_NODES={nodes_json}, RAW_EDGES={edges_json};
  var nodesDS=new vis.DataSet(RAW_NODES), edgesDS=new vis.DataSet(RAW_EDGES);
  var network=new vis.Network(document.getElementById("graph-canvas"),{{nodes:nodesDS,edges:edgesDS}},{{nodes:{{borderWidth:1.5,shadow:{{enabled:true,size:8,x:2,y:2,color:"rgba(0,0,0,0.5)"}}}},physics:{{solver:"barnesHut",barnesHut:{{gravitationalConstant:-12000,centralGravity:0.25,springLength:180,springConstant:0.04,damping:0.12,avoidOverlap:0.2}},stabilization:{{iterations:300}}}},layout:{{randomSeed:42}}}});
  network.on("click",function(p){{if(!p.nodes.length)return;var n=nodesDS.get(p.nodes[0]);document.getElementById("node-info").innerHTML='<div class="name">'+n.label+'</div>'+n.title;}});
  document.getElementById("search").addEventListener("input",function(){{var q=this.value.toLowerCase();nodesDS.update(RAW_NODES.map(function(n){{var h=n.label.toLowerCase().includes(q);return {{id:n.id,opacity:h?1:0.2,color:h?n.color:{{background:"#222",border:"#333"}}}};}}));}});
  function resetView(){{nodesDS.update(RAW_NODES.map(function(n){{return {{id:n.id,opacity:1,color:n.color}};}}));network.fit();}}
</script>
</body>
</html>"""

        # ── HTML 2: LANDING PAGE DE ORIENTAÇÃO (DASHBOARD ANALÍTICO COMPLETO) ──
        html_landing = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GraphRAG — Orientação e Analytics</title>
  <script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.min.css">
  <script src="https://code.jquery.com/jquery-3.7.0.js"></script>
  <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    html, body {{ min-height: 100%; background: #0d0d1a; color: #e0e0e0; font-family: 'Segoe UI', sans-serif; overflow-y: auto; scroll-behavior: smooth; }}
    ::-webkit-scrollbar {{ width: 10px; }}
    ::-webkit-scrollbar-track {{ background: #0d0d1a; }}
    ::-webkit-scrollbar-thumb {{ background: #1e1e36; border-radius: 10px; border: 3px solid #0d0d1a; }}
    ::-webkit-scrollbar-thumb:hover {{ background: #4ECDC4; }}
    #graph-background {{ position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 1; opacity: 0.15; filter: blur(4px); pointer-events: none; }}
    #dashboard {{ position: relative; width: 100%; min-height: 100vh; z-index: 5; display: flex; flex-direction: column; padding: 20px; gap: 20px; pointer-events: auto; }}
    .panel {{ background: rgba(20, 20, 40, 0.6); backdrop-filter: blur(12px); border-radius: 16px; border: 1px solid rgba(255,255,255,0.08); box-shadow: 0 8px 32px rgba(0,0,0,0.4); }}
    
    /* CHATBOT (EXPANSÍVEL) */
    #chat-box {{ height: 800px; overflow: hidden; transition: all 0.4s ease; flex-shrink: 0; }}
    #chat-box.collapsed {{ height: 45px; }}
    #chat-messages {{ flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding-right: 15px; scrollbar-width: thin; scrollbar-color: #4ECDC4 #1a1a2e; }}
    #chat-messages::-webkit-scrollbar {{ width: 6px; }}
    #chat-messages::-webkit-scrollbar-track {{ background: #1a1a2e; }}
    #chat-messages::-webkit-scrollbar-thumb {{ background: #4ECDC4; border-radius: 10px; }}

    /* TABELA DE NODES (EXPANSÍVEL) */
    #nodes-box {{ height: 45px; overflow: hidden; transition: all 0.4s ease; flex-shrink: 0; }}
    #nodes-box.expanded {{ height: 350px; }}
    .panel-header {{ padding: 12px 20px; display: flex; justify-content: space-between; align-items: center; cursor: pointer; background: rgba(255,255,255,0.03); }}
    .panel-header h2 {{ font-size: 0.9em; text-transform: uppercase; letter-spacing: 1px; color: #4ECDC4; }}
    .table-container {{ padding: 20px; height: 300px; overflow-y: auto; font-size: 0.85em; }}
    table.dataTable {{ color: #ccc !important; }}
    
    /* ANALYTICS SIDEBAR & TABS */
    #main-content {{ display: flex; flex: 1; gap: 20px; }}
    #sidebar-tabs {{ width: 260px; display: flex; flex-direction: column; gap: 8px; padding: 15px; flex-shrink: 0; overflow-y: auto; height: 100%; }}
    .tab-btn {{ padding: 12px 14px; background: rgba(255,255,255,0.02); border-radius: 8px; text-align: left; cursor: pointer; border: 1px solid transparent; font-size: 0.82em; color: #888; transition: 0.2s; font-weight: 600; }}
    .tab-btn:hover {{ background: rgba(255,255,255,0.05); color: #ccc; }}
    .tab-btn.active {{ border-color: #4ECDC4; color: #4ECDC4; background: rgba(78, 205, 196, 0.05); }}

    /* SUB-MENU INDICADORES */
    #indicator-selector {{ padding: 15px 20px; background: rgba(255,255,255,0.02); border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; gap: 10px; overflow-x: auto; white-space: nowrap; }}
    .ind-btn {{ padding: 6px 14px; background: #1e1e36; border: 1px solid #333; border-radius: 6px; color: #777; font-size: 0.75em; cursor: pointer; transition: 0.2s; }}
    .ind-btn:hover {{ border-color: #4ECDC4; color: #ccc; }}
    .ind-btn.active {{ background: #4ECDC4; color: #0d0d1a; border-color: #4ECDC4; font-weight: 700; }}

    #charts-area {{ flex: 1; padding: 20px; display: grid; grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; gap: 20px; }}
    .chart-container {{ background: rgba(0,0,0,0.2); border-radius: 12px; padding: 20px; display: flex; flex-direction: column; gap: 10px; min-height: 380px; }}
    .chart-title {{ font-size: 0.75em; color: #4ECDC4; text-transform: uppercase; font-weight: 700; border-left: 3px solid #4ECDC4; padding-left: 8px; }}
    .chart-wrapper {{ flex: 1; position: relative; width: 100%; height: 300px; }}

    /* ORIENTATION CARD */
    #orientation-card {{ position: fixed; top: 25px; right: 25px; z-index: 100; pointer-events: auto; }}
    .onboarding-card {{ background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.1); backdrop-filter: blur(15px); border-radius: 20px; padding: 30px; width: 380px; box-shadow: 0 20px 50px rgba(0,0,0,0.5); transition: 0.5s; }}
    .onboarding-card.minimized {{ width: 200px; height: 50px; padding: 0 15px; cursor: pointer; display: flex; align-items: center; }}
    .onboarding-card.minimized .full-content {{ display: none; }}
    .onboarding-card.minimized .mini-label {{ display: block; font-weight: 700; color: #4ECDC4; }}
    .mini-label {{ display: none; }}
    .onboarding-header h1 {{ font-size: 1.4em; color: #4ECDC4; margin-bottom: 5px; }}
    .onboarding-header p {{ font-size: 0.8em; color: #888; margin-bottom: 15px; }}
    .grid-features {{ display: grid; grid-template-columns: 1fr; gap: 10px; margin-bottom: 20px; }}
    .feature-item {{ background: rgba(255,255,255,0.02); padding: 10px; border-radius: 8px; border-left: 2px solid #4ECDC4; }}
    .feature-item h3 {{ font-size: 0.7em; color: #4ECDC4; margin-bottom: 4px; }}
    .feature-item p {{ font-size: 0.75em; color: #aaa; }}
    .btn-action {{ background: #4ECDC4; color: #0d0d1a; border: none; padding: 10px; border-radius: 8px; font-weight: 800; width: 100%; cursor: pointer; font-size: 0.8em; text-align: center; text-decoration: none; display: block; }}
  </style>
</head>
<body>
  <div id="graph-background"></div>
  <div id="dashboard">
    <!-- CHATBOT -->
    <div id="chat-box" class="panel">
      <div class="panel-header" onclick="toggleChat()">
        <h2>🤖 GraphRAG Chat (IA)</h2>
        <span id="chat-icon">▲</span>
      </div>
      <div id="chat-content" style="padding: 25px; height: 750px; display: flex; flex-direction: column; gap: 20px;">
        <div id="chat-messages">
          <div style="background: rgba(78, 205, 196, 0.1); padding: 15px 20px; border-radius: 12px; font-size: 0.9em; max-width: 80%; border-left: 4px solid #4ECDC4; line-height: 1.6;">
            Olá! Sou seu assistente GraphRAG Semântico. Como posso ajudar você a explorar as entidades e relações hoje?
          </div>
        </div>
        <div style="display: flex; gap: 15px; background: rgba(0,0,0,0.2); padding: 15px; border-radius: 12px; border: 1px solid rgba(255,255,255,0.05);">
          <input id="chat-input" type="text" placeholder="Digite sua pergunta..." style="flex: 1; background: #0d0d1a; border: 1px solid #333; border-radius: 8px; padding: 15px; color: white; outline: none; font-size: 0.9em;">
          <button onclick="sendMessage()" style="background: #4ECDC4; color: #0d0d1a; border: none; padding: 0 30px; border-radius: 8px; font-weight: 800; cursor: pointer; transition: 0.2s;">ENVIAR</button>
        </div>
      </div>
    </div>

    <!-- TABELA -->
    <div id="nodes-box" class="panel">
      <div class="panel-header" onclick="toggleNodes()">
        <h2>🧬 Grafo Semântico (Entidades)</h2>
        <span id="nodes-icon">▼</span>
      </div>
      <div class="table-container">
        <table id="nodesTable" class="display" style="width:100%">
          <thead><tr><th>ID</th><th>Tipo</th><th>Label</th><th>Doc</th><th>Grau</th></tr></thead>
        </table>
      </div>
    </div>

    <!-- ANALYTICS -->
    <div id="main-content">
      <div id="sidebar-tabs" class="panel">
        <h3 style="font-size: 0.7em; color: #555; margin-bottom: 10px; padding-left: 10px;">SEÇÕES DE REDE</h3>
        <button class="tab-btn active" onclick="switchTab(1)">1. General Topology</button>
        <button class="tab-btn" onclick="switchTab(2)">2. Degree Metrics</button>
        <button class="tab-btn" onclick="switchTab(3)">3. Connectivity</button>
        <button class="tab-btn" onclick="switchTab(4)">4. Paths & Distances</button>
        <button class="tab-btn" onclick="switchTab(5)">5. Centrality Analysis</button>
        <button class="tab-btn" onclick="switchTab(6)">6. Community Detection</button>
        <button class="tab-btn" onclick="switchTab(7)">7. Spectral Analysis</button>
        <button class="tab-btn" onclick="switchTab(8)">8. Robustness & Failures</button>
        <button class="tab-btn" onclick="switchTab(9)">9. Cycles & Motifs</button>
        <button class="tab-btn" onclick="switchTab(10)">10. Directed Dynamics</button>
        <button class="tab-btn" onclick="switchTab(11)">11. Node Distribution</button>
        <button class="tab-btn" onclick="switchTab(12)">12. Edge Distribution</button>
      </div>
      <div style="flex: 1; display: flex; flex-direction: column; gap: 20px;">
        <div id="indicator-selector" class="panel"></div>
        <div id="charts-area" class="panel">
          <div class="chart-container"><div class="chart-title" id="title1"></div><div class="chart-wrapper"><canvas id="chart1"></canvas></div></div>
          <div class="chart-container"><div class="chart-title" id="title2"></div><div class="chart-wrapper"><canvas id="chart2"></canvas></div></div>
          <div class="chart-container"><div class="chart-title" id="title3"></div><div class="chart-wrapper"><canvas id="chart3"></canvas></div></div>
          <div class="chart-container"><div class="chart-title" id="title4"></div><div class="chart-wrapper"><canvas id="chart4"></canvas></div></div>
        </div>
      </div>
    </div>
    <div style="height: 100px;"></div>
  </div>

  <!-- ORIENTATION CARD -->
  <div id="orientation-card">
    <div id="card-body" class="onboarding-card minimized" onclick="expandCard()">
      <div class="mini-label">VER GRAFOS 📖</div>
      <div class="full-content">
        <div class="onboarding-header"><h1>GraphRAG Navigation</h1><p>Visualização Semântica</p></div>
        <div class="grid-features">
          <div class="feature-item"><h3>Significado</h3><p>Nodes são Entidades ou Categorias.</p></div>
          <div class="feature-item"><h3>Caminhos</h3><p>Relacionamentos como mede, impacta, pertence_a.</p></div>
        </div>
        <a href="/graph/view" class="btn-action">ACESSAR VISUALIZAÇÃO DO GRAFO &rarr;</a>
        <button style="background:transparent; color:#555; border:none; margin-top:10px; cursor:pointer;" onclick="event.stopPropagation(); minimizeCard()">Fechar</button>
      </div>
    </div>
  </div>

  <script>
    var CHART_DATA = {charts_data};
    var currentGroup = 1, currentIndicator = "", charts = [];

    function toggleChat() {{
      const box = document.getElementById('chat-box');
      box.classList.toggle('collapsed');
      document.getElementById('chat-icon').innerText = box.classList.contains('collapsed') ? '▼' : '▲';
    }}

    async function sendMessage() {{
      const input = document.getElementById('chat-input');
      const container = document.getElementById('chat-messages');
      const question = input.value.trim();
      if (!question) return;

      const userDiv = document.createElement('div');
      userDiv.style = "background: rgba(255,255,255,0.05); padding: 10px 15px; border-radius: 12px; font-size: 0.85em; max-width: 80%; align-self: flex-end; color: #ccc;";
      userDiv.innerText = question;
      container.appendChild(userDiv);
      input.value = "";
      container.scrollTop = container.scrollHeight;

      const loadingDiv = document.createElement('div');
      loadingDiv.style = "background: rgba(78, 205, 196, 0.1); padding: 10px 15px; border-radius: 12px; font-size: 0.85em; max-width: 80%; border-left: 3px solid #4ECDC4; color: #888;";
      loadingDiv.innerText = "Pensando...";
      container.appendChild(loadingDiv);
      container.scrollTop = container.scrollHeight;

      try {{
        const response = await fetch('/query', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{ question: question, top_k: 8, hop_depth: 2, max_context: 20 }})
        }});
        const result = await response.json();
        loadingDiv.innerText = result.answer || result.response || "Sem resposta.";
        loadingDiv.style.color = "#fff";
      }} catch (err) {{
        loadingDiv.innerText = "Erro no servidor.";
        loadingDiv.style.color = "#FF6B6B";
      }}
      container.scrollTop = container.scrollHeight;
    }}

    document.getElementById('chat-input')?.addEventListener('keypress', (e) => {{ if (e.key === 'Enter') sendMessage(); }});
    function toggleNodes() {{
      const box = document.getElementById('nodes-box');
      box.classList.toggle('expanded');
      document.getElementById('nodes-icon').innerText = box.classList.contains('expanded') ? '▲' : '▼';
    }}
    function expandCard() {{ document.getElementById('card-body').classList.remove('minimized'); }}
    function minimizeCard() {{ document.getElementById('card-body').classList.add('minimized'); }}

    function switchTab(groupId) {{
      currentGroup = groupId;
      document.querySelectorAll('.tab-btn').forEach((b, idx) => b.classList.toggle('active', idx + 1 === groupId));
      const selector = document.getElementById('indicator-selector');
      const indicators = Object.keys(CHART_DATA[groupId]);
      selector.innerHTML = indicators.map(name => `<button class="ind-btn" onclick="selectIndicator('${{name}}')">${{name}}</button>`).join('');
      selectIndicator(indicators[0]);
    }}

    function selectIndicator(name) {{
      currentIndicator = name;
      document.querySelectorAll('.ind-btn').forEach(b => b.classList.toggle('active', b.innerText === name));
      const data = CHART_DATA[currentGroup][name];
      const types = ['bar', 'line', 'line', 'scatter'];
      charts.forEach(c => c.destroy()); charts = [];
      ['chart1', 'chart2', 'chart3', 'chart4'].forEach((ctxId, i) => {{
        const ctx = document.getElementById(ctxId).getContext('2d');
        document.getElementById('title' + (i+1)).innerText = name + ' (' + (['Bars', 'Trends', 'Area', 'Scatter'][i]) + ')';
        charts.push(new Chart(ctx, {{
          type: types[i],
          data: {{
            labels: data.labels,
            datasets: [{{
              label: name,
              data: types[i] === 'scatter' ? data.values.map((v, idx) => ({{x: idx, y: v}})) : data.values,
              backgroundColor: i === 2 ? 'rgba(78, 205, 196, 0.2)' : '#4ECDC4',
              borderColor: '#4ECDC4', fill: i === 2, tension: 0.4
            }}]
          }},
          options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ y: {{ grid: {{ color: '#222' }}, ticks: {{ color: '#888' }} }}, x: {{ grid: {{ display: false }}, ticks: {{ color: '#888', font: {{ size: 9 }} }} }} }} }}
        }}));
      }});
    }}

    $(document).ready(function() {{
      $('#nodesTable').DataTable({{
        data: {nodes_table_data},
        columns: [{{data:'ID'}}, {{data:'Tipo'}}, {{data:'Label'}}, {{data:'Doc'}}, {{data:'Grau'}}],
        pageLength: 5, language: {{ search: "_INPUT_", searchPlaceholder: "Buscar entidade..." }}
      }});
      switchTab(1);
      new vis.Network(document.getElementById("graph-background"), {{nodes:{nodes_json}, edges:{edges_json}}}, {{ interaction:{{dragView:false,zoomView:false}}, physics:{{stabilization:true}} }});
    }});
  </script>
</body>
</html>"""

        caminho.write_text(html_graph, encoding="utf-8")
        GRAPH_LANDING_FILE.write_text(html_landing, encoding="utf-8")
        logger.info(f"Visualizacao SEMANTICA salva em '{caminho}' e '{GRAPH_LANDING_FILE}'")

    def visualize_static(self, caminho: Path = GRAPH_PNG_FILE):
        """Gera PNG estático do grafo semântico."""
        ensure_dirs()
        G = self.G
        if G.number_of_nodes() == 0:
            return

        colors   = [SEMANTIC_NODE_COLORS.get(G.nodes[n].get("node_type",""), "#95A5A6") for n in G.nodes()]
        degrees  = dict(G.degree())
        max_deg  = max(degrees.values(), default=1)
        sizes    = [200 + (degrees[n] / max_deg) * 1200 for n in G.nodes()]
        fig_size = max(16, min(48, G.number_of_nodes() * 0.5))

        plt.figure(figsize=(fig_size, fig_size * 0.7), facecolor="#0d0d1a")
        pos = nx.spring_layout(G, k=3.0 / max(G.number_of_nodes() ** 0.3, 1), seed=42)
        nx.draw_networkx_edges(G, pos, edge_color="#444466", arrows=True,
                               arrowsize=10, alpha=0.4, width=0.7)
        nx.draw_networkx_nodes(G, pos, node_color=colors, node_size=sizes,
                               alpha=0.9, edgecolors="#ffffff", linewidths=0.5)
        labels = {n: G.nodes[n].get("name", n)[:22] for n in G.nodes()}
        nx.draw_networkx_labels(G, pos, labels, font_size=6, font_color="white")

        legend_elements = [
            plt.scatter([], [], c=color, s=80, label=ntype)
            for ntype, color in SEMANTIC_NODE_COLORS.items()
        ]
        plt.legend(handles=legend_elements, loc="upper left", fontsize=8,
                   title="Hierarquia", facecolor="#1a1a2e", labelcolor="white")
        plt.title("GraphRAG — Grafo Semantico", fontsize=14, color="white", pad=15)
        plt.tight_layout()
        plt.savefig(caminho, dpi=180, bbox_inches="tight", facecolor="#0d0d1a")
        plt.close()
        logger.info(f"PNG semantico salvo em '{caminho}'")

    def print_stats(self):
        s = self.stats()
        print("\n" + "=" * 52)
        print("  GRAFO SEMANTICO — ESTATISTICAS")
        print("=" * 52)
        print(f"  Nodes totais:   {s['total_nodes']}")
        print(f"  Arestas totais: {s['total_edges']}")
        print(f"  Densidade:      {s['density']:.5f}")
        print("\n  Nodes por tipo:")
        for t, c in sorted(s["nodes_by_type"].items()):
            print(f"    {t:12s} -> {c}")
        print("\n  Arestas por tipo:")
        for t, c in sorted(s["edges_by_type"].items()):
            print(f"    {t:30s} -> {c}")
        print("=" * 52)


# ══════════════════════════════════════════════════════════════
# CHROMADB — collection semântica
# Armazena textos contextuais longos que descrevem cada entity
# ══════════════════════════════════════════════════════════════

def get_semantic_collection():
    """Retorna a collection ChromaDB do Pipeline 2."""
    ensure_dirs()
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return chroma_client.get_or_create_collection(
        name=COLLECTION_SEMANTIC_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def store_entity_context(collection, entity_id: str, entity: dict):
    """
    Armazena o texto contextual longo de uma entidade no ChromaDB semântico.
    O texto é rico para garantir embeddings de qualidade — não o nome curto.
    """
    name      = entity.get("canonical_name", entity.get("name", ""))
    label     = entity.get("label", "")
    aliases   = ", ".join(entity.get("aliases", []))
    context   = entity.get("context_summary", "")
    props     = entity.get("properties", {})
    rels      = entity.get("relationships", [])
    src_docs  = ", ".join(entity.get("source_docs", []))

    # Texto contextual longo — base semântica de qualidade
    props_text = "; ".join(f"{k}={v}" for k, v in props.items()) if props else ""
    rels_text  = "; ".join(f"{r['type']} -> {r['target']}" for r in rels) if rels else ""

    full_text = (
        f"Entidade: {name}\n"
        f"Categoria: {label}\n"
        f"Aliases: {aliases}\n"
        f"Contexto: {context}\n"
        f"Atributos: {props_text}\n"
        f"Relacoes: {rels_text}\n"
        f"Fontes: {src_docs}"
    ).strip()

    metadata = {
        "node_type":      SemanticNodeType.ENTITY,
        "entity_id":      entity_id,
        "canonical_name": name,
        "label":          label,
        "aliases":        aliases,
        "source_docs":    src_docs,
    }

    collection.upsert(ids=[entity_id], documents=[full_text], metadatas=[metadata])


# ══════════════════════════════════════════════════════════════
# ENTRY POINT — chamado por main.py --semantic
# ══════════════════════════════════════════════════════════════

def run_semantic_pipeline(scope: str = "1", topic: Optional[str] = None,
                          doc_filter: Optional[str] = None):
    """
    Pipeline 2 completo:
      1. Lê chunks do ChromaDB[graphrag_docs]
      2. Extrai entidades por lote (LLM)
      3. Normaliza aliases (LLM)
      4. Filtra ambíguos (LLM)
      5. Popula ChromaDB[graphrag_semantic]
      6. Constrói SemanticKnowledgeGraph
      7. Salva grafo + visualizações
    """
    ensure_dirs()

    # ── 1. Carregar chunks do Pipeline 1 ─────────────────────
    chroma_client      = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        p1_collection  = chroma_client.get_collection(COLLECTION_NAME)
    except Exception:
        print("ERRO: ChromaDB do Pipeline 1 nao encontrado. Execute: python main.py --ingest")
        return

    all_results = p1_collection.get(
        include=["documents", "metadatas"],
        where={"node_type": "chunk"},
    )

    all_chunks = [
        {
            "id":       all_results["ids"][i],
            "text":     all_results["documents"][i],
            "metadata": all_results["metadatas"][i],
        }
        for i in range(len(all_results["ids"]))
        if all_results["documents"][i].strip()
    ]

    # ── Aplicar filtro de escopo ──────────────────────────────
    if scope == "2" and topic:
        topic_lower = topic.lower()
        all_chunks = [
            c for c in all_chunks
            if topic_lower in c["text"].lower()
            or topic_lower in c["metadata"].get("section", "").lower()
        ]
        print(f"  Escopo focado: {len(all_chunks)} chunks sobre '{topic}'")
    elif scope == "3" and doc_filter:
        all_chunks = [
            c for c in all_chunks
            if doc_filter in c["metadata"].get("doc_id", "")
        ]
        print(f"  Escopo por documento: {len(all_chunks)} chunks de '{doc_filter}'")
    else:
        print(f"  Escopo geral: {len(all_chunks)} chunks")

    if not all_chunks:
        print("ERRO: Nenhum chunk encontrado com os filtros aplicados.")
        return

    # ── 2. Extrair entidades por lote ────────────────────────
    print(f"\n[1/5] Extraindo entidades de {len(all_chunks)} chunks "
          f"(lotes de {SEMANTIC_BATCH_SIZE})...")
    all_entities: list[dict] = []

    for i in range(0, len(all_chunks), SEMANTIC_BATCH_SIZE):
        batch  = all_chunks[i : i + SEMANTIC_BATCH_SIZE]
        result = extract_entities_from_chunks(batch)
        all_entities.extend(result)
        print(f"  Lote {i//SEMANTIC_BATCH_SIZE + 1}: {len(result)} entidades extraidas")

    print(f"  Total bruto: {len(all_entities)} entidades")

    # ── 3. Normalizar aliases ────────────────────────────────
    print(f"\n[2/5] Normalizando {len(all_entities)} entidades...")
    all_entities = normalize_entities(all_entities)
    print(f"  Total apos normalizacao: {len(all_entities)} grupos unicos")

    # ── 4. Filtra ambíguos ───────────────────────────────────
    print(f"\n[3/5] Filtrando nodes ambiguos...")
    kept, promoted_properties = filter_ambiguous_nodes(all_entities)
    print(f"  {len(kept)} entidades validas para o grafo")

    # Filtrar por recorrência mínima
    # Contar quantos chunks distintos referenciaram cada entidade
    recurrence: dict[str, set] = defaultdict(set)
    for ent in all_entities:
        eid = make_entity_id(ent.get("label",""), ent.get("canonical_name",""))
        for cid in ent.get("source_chunk_ids", []):
            recurrence[eid].add(cid)

    kept = [
        e for e in kept
        if len(recurrence.get(
            make_entity_id(e.get("label",""), e.get("canonical_name","")), set()
        )) >= SEMANTIC_MIN_RECURRENCE
    ]
    print(f"  {len(kept)} entidades apos filtro de recorrencia (min={SEMANTIC_MIN_RECURRENCE} chunks)")

    if not kept:
        print("\nAVISO: Nenhuma entidade valida encontrada.")
        print("  Tente reduzir SEMANTIC_MIN_RECURRENCE em config.py ou use escopo mais amplo.")
        return

    # ── 5. Construir ChromaDB semântico e grafo ───────────────
    print(f"\n[4/5] Construindo ChromaDB semantico e grafo NetworkX...")
    sem_collection = get_semantic_collection()
    skg            = SemanticKnowledgeGraph()

    for ent in kept:
        # Grafo NetworkX
        entity_id = skg.add_entity(ent)

        # Properties → nodes filhos
        for key, val in ent.get("properties", {}).items():
            if val and str(val).strip():
                skg.add_property(entity_id, key, str(val))

        # Relationships → arestas semânticas
        for rel in ent.get("relationships", []):
            rel_type = rel.get("type", "relacionado_com")
            target   = rel.get("target", "")
            if target:
                skg.add_relationship(entity_id, rel_type, target)

        # ChromaDB semântico — texto contextual longo
        store_entity_context(sem_collection, entity_id, ent)

    # ── 6. Persistir ─────────────────────────────────────────
    print(f"\n[5/5] Salvando e gerando visualizacoes...")
    skg.save()
    skg.visualize_static()
    skg.visualize_interactive()

    # ── Resumo ────────────────────────────────────────────────
    skg.print_stats()
    print(f"\n  ChromaDB semantico: {sem_collection.count()} entidades armazenadas")
    print(f"  Grafo: {SEMANTIC_GRAPH_PICKLE}")
    print(f"  Visualizacao: {GRAPH_HTML_FILE}")
    print(f"\n  Acesse: python main.py --api  e abra http://localhost:8000/graph/view")
