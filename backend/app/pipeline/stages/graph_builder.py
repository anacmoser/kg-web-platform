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
                
            # Add nodes with types and descriptions
            src_desc = triple.get("source_desc", "")
            tgt_desc = triple.get("target_desc", "")
            
            if src not in G:
                G.add_node(src, type=triple.get("source_type", "Unknown"), description=src_desc)
            else:
                # Update description if it's better/longer
                existing_desc = G.nodes[src].get("description", "")
                if len(src_desc) > len(existing_desc):
                    G.nodes[src]["description"] = src_desc
            
            if tgt not in G:
                G.add_node(tgt, type=triple.get("target_type", "Unknown"), description=tgt_desc)
            else:
                existing_desc = G.nodes[tgt].get("description", "")
                if len(tgt_desc) > len(existing_desc):
                    G.nodes[tgt]["description"] = tgt_desc
                
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

