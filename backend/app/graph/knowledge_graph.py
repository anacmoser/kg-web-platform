import networkx as nx
import logging
import pickle
import json
from pathlib import Path
from collections import deque
from app.config import NodeType, EdgeType

logger = logging.getLogger(__name__)

class KnowledgeGraph:
    """
    Structural Knowledge Graph representing the hierarchy and relationships within documents.
    Supports GraphRAG context expansion and multi-format persistence.
    """
    def __init__(self, name: str = "structural_graph"):
        self.name = name
        self.G = nx.DiGraph()

    def add_node(self, node_id: str, node_type: str, **kwargs):
        """Adds a node to the graph, merging attributes if it already exists."""
        if self.G.has_node(node_id):
            # Safe attribute merge
            for k, v in kwargs.items():
                if k not in self.G.nodes[node_id] or not self.G.nodes[node_id][k]:
                    self.G.nodes[node_id][k] = v
        else:
            self.G.add_node(node_id, type=node_type, **kwargs)

    def add_edge(self, source_id: str, target_id: str, edge_type: str, **kwargs):
        """Adds an edge to the graph, with consistency logging."""
        missing = []
        if not self.G.has_node(source_id): missing.append(source_id)
        if not self.G.has_node(target_id): missing.append(target_id)
        
        if missing:
            logger.warning(f"Inconsistent Edge! Missing nodes: {missing} for edge {source_id} -> {target_id}")
            # Autocreate missing nodes as Unknown type to prevent crash, but logged!
            for m in missing:
                self.G.add_node(m, type="UNKNOWN")

        self.G.add_edge(source_id, target_id, type=edge_type, **kwargs)

    def get_node_attr(self, node_id: str) -> dict:
        if self.G.has_node(node_id):
            return dict(self.G.nodes[node_id])
        return {}
        
    def get_neighbors(self, node_id: str, edge_type: str = None) -> list:
        if not self.G.has_node(node_id):
            return []
        
        if edge_type:
            return [n for n in self.G.successors(node_id) 
                   if self.G.get_edge_data(node_id, n).get('type') == edge_type]
        return list(self.G.successors(node_id))

    def nodes_by_type(self, node_type: str) -> list[str]:
        return [n for n, attr in self.G.nodes(data=True) if attr.get("type") == node_type]

    def expand_seeds(self, seed_ids: list[str], hop_depth: int = 2, max_nodes: int = 50, priority_types: list = None) -> list[str]:
        """BFS Expansion of context nodes starting from seed points."""
        if not seed_ids:
            return []
            
        visited = set(seed_ids)
        # Store as (node_id, depth)
        queue = deque([(sid, 0) for sid in seed_ids if self.G.has_node(sid)])
        expanded = list(seed_ids)
        
        while queue and len(expanded) < max_nodes:
            current_id, depth = queue.popleft()
            
            if depth >= hop_depth:
                continue
                
            # Both forward and backward navigation to find containing pages/docs
            neighbors = list(self.G.successors(current_id)) + list(self.G.predecessors(current_id))
            
            for neighbor in neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
                    expanded.append(neighbor)
                    if len(expanded) >= max_nodes:
                        break

        # Re-rank based on priority types if provided
        if priority_types:
            def sort_key(n_id):
                ntype = self.G.nodes[n_id].get("type", "UNKNOWN")
                try:
                    return priority_types.index(ntype)
                except ValueError:
                    return len(priority_types) # lowest priority
            expanded.sort(key=sort_key)
            
        return expanded

    def is_empty(self) -> bool:
        return self.G.number_of_nodes() == 0

    def print_stats(self):
        logger.info(f"--- Graph Stats: {self.name} ---")
        logger.info(f"Nodes: {self.G.number_of_nodes()}")
        logger.info(f"Edges: {self.G.number_of_edges()}")
        # Calculate types
        types = {}
        for _, attr in self.G.nodes(data=True):
            t = attr.get('type', 'UNKNOWN')
            types[t] = types.get(t, 0) + 1
        logger.info(f"Node Types: {types}")

    def save(self, directory: str | Path = None):
        """Persist graph in Pickle, JSON, and GML."""
        if directory is None:
            from app.config import settings
            directory = settings.STORAGE_DIR
        
        dir_path = Path(directory)
        dir_path.mkdir(parents=True, exist_ok=True)
        
        if self.is_empty():
            logger.warning("Attempted to save empty graph.")
            return

        # 1. Pickle (Primary Fast Reload)
        pkl_path = dir_path / f"{self.name}.pkl"
        with open(pkl_path, 'wb') as f:
            pickle.dump(self.G, f)
            
        # 2. GML (Standard)
        gml_path = dir_path / f"{self.name}.gml"
        nx.write_gml(self.G, gml_path)

        # 3. JSON Node-Link
        json_path = dir_path / f"{self.name}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(nx.node_link_data(self.G), f, indent=2)
            
        logger.info(f"Graph '{self.name}' saved to {dir_path}")

    @classmethod
    def load(cls, directory: str | Path = None) -> "KnowledgeGraph":
        """Load graph from Pickle (Primary)."""
        if directory is None:
            from app.config import settings
            directory = settings.STORAGE_DIR
            
        kg = cls()
        pkl_path = Path(directory) / f"{kg.name}.pkl"
        if not pkl_path.exists():
            return kg
            
        try:
            with open(pkl_path, 'rb') as f:
                kg.G = pickle.load(f)
            logger.info(f"Graph '{kg.name}' loaded from {pkl_path}")
            return kg
        except Exception as e:
            logger.error(f"Failed to load graph {kg.name}: {e}")
            return kg

    @classmethod
    def exists(cls, directory: str | Path = None) -> bool:
        if directory is None:
            from app.config import settings
            directory = settings.STORAGE_DIR
            
        # Use default name from cls()
        name = cls().name
        return (Path(directory) / f"{name}.pkl").exists()

    def visualize_static(self, output_path: str | Path):
        """Generates static PNG rendering using matplotlib."""
        if self.is_empty():
            return
            
        try:
            import matplotlib.pyplot as plt
            plt.figure(figsize=(12, 12))
            
            # Colors by type
            color_map = {
                NodeType['DOCUMENT']: '#ff9999',
                NodeType['PAGE']: '#66b3ff',
                NodeType['SECTION']: '#99ff99',
                NodeType['CHUNK']: '#ffcc99',
                NodeType['IMAGE']: '#c2c2f0',
                NodeType['TABLE']: '#ffb3e6',
                "UNKNOWN": '#cccccc'
            }
            
            colors = [color_map.get(data.get('type', 'UNKNOWN'), '#cccccc') for _, data in self.G.nodes(data=True)]
            
            # Sizes by degree
            sizes = [300 + (self.G.degree(n) * 100) for n in self.G.nodes()]
            
            pos = nx.spring_layout(self.G, seed=42)
            nx.draw(self.G, pos, node_color=colors, node_size=sizes, with_labels=False, alpha=0.8)
            
            plt.savefig(output_path, dpi=180, bbox_inches='tight')
            plt.close()
            logger.info(f"Static visualization saved to {output_path}")
        except ImportError:
            logger.warning("Matplotlib not installed for static visualization.")
        except Exception as e:
            logger.error(f"Error generating static visualization: {e}")
