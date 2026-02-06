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
                
            # Add nodes with types
            if src not in G:
                G.add_node(src, type=triple.get("source_type", "Unknown"))
            
            if tgt not in G:
                G.add_node(tgt, type=triple.get("target_type", "Unknown"))
                
            # Add edge (update weight if exists)
            if G.has_edge(src, tgt):
                # Check if this specific relation exists
                edge_data = G.get_edge_data(src, tgt)
                # Simple weight increment for now
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

