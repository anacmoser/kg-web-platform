import networkx as nx
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)

class GraphSerializer:
    """
    Converts NetworkX graphs to various formats for frontend consumption.
    Primary format: Cytoscape.js
    """
    
    def to_cytoscape(self, graph: nx.DiGraph) -> Dict[str, Any]:
        """
        Convert NetworkX graph to Cytoscape.js format.
        
        Returns:
            {
                "elements": {
                    "nodes": [{"data": {"id": "...", "label": "...", "type": "..."}}],
                    "edges": [{"data": {"id": "...", "source": "...", "target": "...", "relation": "..."}}]
                }
            }
        """
        logger.info(f"Converting graph to Cytoscape format: {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges")
        
        nodes = []
        edges = []
        
        # Convert nodes
        for node_id, node_data in graph.nodes(data=True):
            node_element = {
                "data": {
                    "id": str(node_id),
                    "label": str(node_id),
                    "type": node_data.get("type", "Unknown"),
                    "degree": graph.degree(node_id)
                }
            }
            nodes.append(node_element)
        
        # Convert edges
        edge_counter = 0
        for source, target, edge_data in graph.edges(data=True):
            edge_element = {
                "data": {
                    "id": f"edge_{edge_counter}",
                    "source": str(source),
                    "target": str(target),
                    "relation": edge_data.get("relation", "related_to"),
                    "weight": edge_data.get("weight", 1)
                }
            }
            edges.append(edge_element)
            edge_counter += 1
        
        return {
            "elements": {
                "nodes": nodes,
                "edges": edges
            }
        }
    
    def to_node_link(self, graph: nx.DiGraph) -> Dict[str, Any]:
        """
        Convert to standard node-link format (D3.js compatible).
        """
        return nx.node_link_data(graph)
    
    def get_graph_stats(self, graph: nx.DiGraph) -> Dict[str, Any]:
        """
        Extract graph statistics and metadata.
        """
        # Count entity types
        entity_types = {}
        for _, node_data in graph.nodes(data=True):
            node_type = node_data.get("type", "Unknown")
            entity_types[node_type] = entity_types.get(node_type, 0) + 1
        
        # Count relation types
        relation_types = {}
        for _, _, edge_data in graph.edges(data=True):
            relation = edge_data.get("relation", "unknown")
            relation_types[relation] = relation_types.get(relation, 0) + 1
        
        return {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
            "entity_types": entity_types,
            "relation_types": relation_types,
            "density": nx.density(graph),
            "is_connected": nx.is_weakly_connected(graph) if graph.number_of_nodes() > 0 else False
        }
