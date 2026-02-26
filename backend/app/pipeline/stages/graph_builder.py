import networkx as nx
from typing import List, Dict, Any
import logging
from app.graph.serializers import GraphSerializer

logger = logging.getLogger(__name__)

class GraphBuilder:
    def __init__(self):
        self.serializer = GraphSerializer()

    def build_graph(self, triples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Constructs a NetworkX Directed Graph from triples.
        Returns both the graph and serialized formats.
        """
        G = nx.DiGraph()
        
        logger.info(f"Building graph from {len(triples)} triples...")
        
        for triple in triples:
            src = triple.get("source")
            tgt = triple.get("target")
            rel = triple.get("relation")
            
            if not src or not tgt or not rel:
                continue
                
            # Add nodes with types, descriptions and dynamic attributes
            src_desc = triple.get("source_desc", "")
            tgt_desc = triple.get("target_desc", "")
            src_attrs = triple.get("source_attributes", {})
            tgt_attrs = triple.get("target_attributes", {})
            
            def add_or_update_node(node_id: str, ntype: str, ndesc: str, nattrs: dict):
                if node_id not in G:
                    G.add_node(node_id, type=ntype, description=ndesc, **nattrs)
                else:
                    # Update description if it's better/longer
                    existing_desc = G.nodes[node_id].get("description", "")
                    if len(ndesc) > len(existing_desc):
                        G.nodes[node_id]["description"] = ndesc
                    
                    # Merge attributes
                    for k, v in nattrs.items():
                        if k not in G.nodes[node_id] or not G.nodes[node_id][k]:
                            G.nodes[node_id][k] = v

            add_or_update_node(src, triple.get("source_type", "Unknown"), src_desc, src_attrs)
            add_or_update_node(tgt, triple.get("target_type", "Unknown"), tgt_desc, tgt_attrs)
                
            # Add edge (update weight if exists)
            if G.has_edge(src, tgt):
                edge_data = G.get_edge_data(src, tgt)
                if edge_data.get("relation") == rel:
                    G[src][tgt]['weight'] = edge_data.get('weight', 1) + 1
            else:
                G.add_edge(src, tgt, relation=rel, weight=1)
                
        logger.info(f"Graph built: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges.")
        
        # Serialize graph for frontend
        cytoscape_data = self.serializer.to_cytoscape(G)
        graph_stats = self.serializer.get_graph_stats(G)
        
        return {
            "graph": G,  # NetworkX graph object
            "cytoscape": cytoscape_data,  # Cytoscape.js format
            "stats": graph_stats  # Graph statistics
        }

