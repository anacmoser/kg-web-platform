import networkx as nx
import logging
import pickle
import json
from pathlib import Path
from typing import Optional
from app.config import settings, SemanticNodeType, SemanticEdgeType

logger = logging.getLogger(__name__)

class SemanticKnowledgeGraph:
    """
    Semantic Knowledge Graph representing entities, properties, and their relationships.
    Source: Pipeline 2 (Entity extraction and normalization).
    """
    def __init__(self, name: str = "semantic_graph"):
        self.name = name
        self.G = nx.DiGraph()

    def add_label(self, label_name: str) -> str:
        from app.utils import make_label_id
        lid = make_label_id(label_name)
        if not self.G.has_node(lid):
            self.G.add_node(lid,
                node_type=SemanticNodeType["LABEL"],
                label=label_name,
                name=label_name,
            )
        return lid

    def add_entity(self, entity: dict) -> str:
        from app.utils import make_entity_id
        label         = entity.get("label", "Conceito")
        canonical     = entity.get("canonical_name", entity.get("name", ""))
        eid           = make_entity_id(label, canonical)
        lid           = self.add_label(label)

        aliases       = entity.get("aliases", [])
        context       = entity.get("context_summary", "")
        source_docs   = entity.get("source_docs", [])
        source_chunks = entity.get("_all_source_chunk_ids", entity.get("source_chunk_ids", []))

        self.G.add_node(eid,
            node_type=SemanticNodeType["ENTITY"],
            label=canonical,
            name=canonical,
            category=label,
            aliases=", ".join(aliases) if isinstance(aliases, list) else aliases,
            context=context[:1000],
            source_docs=", ".join(source_docs) if isinstance(source_docs, list) else source_docs,
            source_chunks=", ".join(source_chunks[:5]) if isinstance(source_chunks, list) else source_chunks,
        )
        self.G.add_edge(lid, eid, edge_type=SemanticEdgeType["LABEL_HAS_ENTITY"])
        return eid

    def add_property(self, entity_id: str, key: str, value: str):
        from app.utils import make_property_id
        pid = make_property_id(entity_id, key)
        label_text = f"{key}: {value}"
        self.G.add_node(pid,
            node_type=SemanticNodeType["PROPERTY"],
            label=label_text,
            name=label_text,
            prop_key=key,
            prop_value=value,
        )
        self.G.add_edge(entity_id, pid, edge_type=SemanticEdgeType["ENTITY_HAS_PROPERTY"])

    def add_relationship(self, src_entity_id: str, rel_type: str, target_name: str,
                          target_label: str = "Conceito"):
        """Adds a semantic edge between two entities."""
        from app.utils import make_entity_id
        # Ensure target existence
        target_eid = make_entity_id(target_label, target_name)
        if not self.G.has_node(target_eid):
            lid = self.add_label(target_label)
            self.G.add_node(target_eid,
                node_type=SemanticNodeType["ENTITY"],
                label=target_name,
                name=target_name,
                category=target_label,
                aliases="",
                context="Entidade referenciada por relacao.",
                source_docs="",
                source_chunks="",
            )
            self.G.add_edge(lid, target_eid, edge_type=SemanticEdgeType["LABEL_HAS_ENTITY"])

        # Mapping rel_type to SemanticEdgeType
        rel_map = {
            "impacta":        SemanticEdgeType["IMPACTA"] if "IMPACTA" in SemanticEdgeType else "IMPACTA",
            "mede":           SemanticEdgeType["MEDE"] if "MEDE" in SemanticEdgeType else "MEDE",
            "pertence_a":     SemanticEdgeType["PERTENCE_A"] if "PERTENCE_A" in SemanticEdgeType else "PERTENCE_A",
            "produz":         SemanticEdgeType["PRODUZ"] if "PRODUZ" in SemanticEdgeType else "PRODUZ",
            "cresce_em":      SemanticEdgeType["CRESCE_EM"] if "CRESCE_EM" in SemanticEdgeType else "CRESCE_EM",
            "declina_em":     SemanticEdgeType["DECLINA_EM"] if "DECLINA_EM" in SemanticEdgeType else "DECLINA_EM",
            "comparado_com":  SemanticEdgeType["COMPARADO_COM"] if "COMPARADO_COM" in SemanticEdgeType else "COMPARADO_COM",
            "depende_de":     SemanticEdgeType["DEPENDE_DE"] if "DEPENDE_DE" in SemanticEdgeType else "DEPENDE_DE",
        }
        edge_type = rel_map.get(rel_type.lower(), SemanticEdgeType.get("RELACIONADO_COM", "RELACIONADO_COM"))

        if not self.G.has_edge(src_entity_id, target_eid):
            self.G.add_edge(src_entity_id, target_eid, edge_type=edge_type)

    def find_entity(self, query: str) -> list[str]:
        q = query.lower()
        return [
            nid for nid, data in self.G.nodes(data=True)
            if data.get("node_type") == SemanticNodeType["ENTITY"]
            and q in data.get("name", "").lower()
        ]

    def get_entity_context(self, entity_id: str) -> dict:
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

    def is_empty(self) -> bool:
        return self.G.number_of_nodes() == 0

    def stats(self) -> dict:
        type_counts = {}
        for _, d in self.G.nodes(data=True):
            t = d.get("node_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        edge_counts = {}
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

    def save(self, directory: Optional[str | Path] = None):
        if directory is None:
            directory = settings.STORAGE_DIR
        
        dir_path = Path(directory)
        dir_path.mkdir(parents=True, exist_ok=True)
        
        pkl_path = dir_path / f"{self.name}.pkl"
        with open(pkl_path, "wb") as f:
            pickle.dump(self.G, f)
            
        # Also save JSON for easier inspection
        json_path = dir_path / f"{self.name}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(nx.node_link_data(self.G), f, indent=2)
            
        logger.info(f"Semantic graph '{self.name}' saved to {dir_path}")

    @classmethod
    def load(cls, directory: Optional[str | Path] = None) -> "SemanticKnowledgeGraph":
        if directory is None:
            directory = settings.STORAGE_DIR
        
        skg = cls()
        pkl_path = Path(directory) / f"{skg.name}.pkl"
        
        if not pkl_path.exists():
            return skg
            
        try:
            with open(pkl_path, "rb") as f:
                skg.G = pickle.load(f)
            logger.info(f"Semantic graph loaded from {pkl_path}")
        except Exception as e:
            logger.error(f"Failed to load semantic graph: {e}")
            
        return skg

    @classmethod
    def exists(cls, directory: Optional[str | Path] = None) -> bool:
        if directory is None:
            directory = settings.STORAGE_DIR
        return (Path(directory) / "semantic_graph.pkl").exists()
