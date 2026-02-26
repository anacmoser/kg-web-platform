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
        
        # Detect communities for better coloring
        try:
            import networkx.algorithms.community as nx_comm
            # Use Louvain for better community structure
            communities = list(nx_comm.louvain_communities(graph, seed=42))
            
            # Map node -> community_id
            community_map = {}
            for i, comm in enumerate(communities):
                for node in comm:
                    community_map[node] = i
            
            num_communities = len(communities)
        except Exception as e:
            logger.warning(f"Community detection failed: {e}")
            community_map = {}
            num_communities = 0

        # Generate vibrant, distinct colors
        def get_community_color(comm_id, total):
            if total <= 1: return "#6366f1" # Default Indigo
            # Use a more spread out hue distribution
            hue = (comm_id * (360 / max(total, 6))) % 360
            return f"hsl({hue}, 85%, 55%)"

        # Convert nodes
        for node_id, node_data in graph.nodes(data=True):
            comm_id = community_map.get(node_id, 0)
            comm_color = get_community_color(comm_id, num_communities)
            
            # Base attributes
            node_data_payload = {
                "id": str(node_id),
                "label": str(node_id),
                "type": node_data.get("type", "Unknown"),
                "description": node_data.get("description", ""),
                "community": comm_id,
                "color": comm_color,
                "degree": graph.degree(node_id)
            }
            
            # Add dynamic attributes (excluding already mapped fields)
            for k, v in node_data.items():
                if k not in ["type", "description"]:
                    if k not in node_data_payload: # Don't overwrite calculated fields
                        node_data_payload[k] = v
            
            node_element = {
                "data": node_data_payload
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
        Extract graph statistics and metadata including requested indicators.
        """
        if graph.number_of_nodes() == 0:
            return {
                "node_count": 0,
                "edge_count": 0,
                "entity_types": {},
                "relation_types": {},
                "density": 0.0,
                "avg_degree": 0.0,
                "avg_betweenness": 0.0,
                "avg_property_sparsity": 0.0,
                "type_consistency": 0.0,
                "triples_entities_ratio": 0.0,
                "avg_fan_out": 0.0,
                "node_importance": {},
                "is_connected": False
            }

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

        # 1. Indicadores de Estrutura e Conectividade
        density = nx.density(graph)
        num_nodes = graph.number_of_nodes()
        num_edges = graph.number_of_edges()
        avg_degree = (2 * num_edges / num_nodes) if num_nodes > 0 else 0
        
        # Betweenness Centrality (normalized)
        try:
            betweenness = nx.betweenness_centrality(graph)
            avg_betweenness = sum(betweenness.values()) / num_nodes if num_nodes > 0 else 0
        except:
            avg_betweenness = 0
            betweenness = {}

        # 2. Indicadores de Qualidade e Completude
        # Property Sparsity (Average fill rate of properties per node)
        # Assuming common properties could be 'type', 'label', and any other keys in data
        property_counts = {}
        for _, data in graph.nodes(data=True):
            for key in data.keys():
                property_counts[key] = property_counts.get(key, 0) + 1
        
        property_sparsity = {k: (v / num_nodes) * 100 for k, v in property_counts.items()}
        avg_property_sparsity = sum(property_sparsity.values()) / len(property_sparsity) if property_sparsity else 0

        # Type Consistency
        valid_types_count = sum(1 for _, data in graph.nodes(data=True) if data.get("type") != "Unknown")
        type_consistency = (valid_types_count / num_nodes) if num_nodes > 0 else 0

        # 3. Indicadores de Semântica e Diversidade
        triples_entities_ratio = num_edges / num_nodes if num_nodes > 0 else 0
        
        # Fan-out Factor (Average Out-degree)
        out_degrees = dict(graph.out_degree())
        avg_fan_out = sum(out_degrees.values()) / num_nodes if num_nodes > 0 else 0

        # Node importance (based on degree and betweenness for coloring/sizing)
        node_importance = {}
        for node in graph.nodes():
            # Importance = (normalized degree + normalized betweenness) / 2
            deg = graph.degree(node)
            norm_deg = deg / (num_nodes - 1) if num_nodes > 1 else 0
            bet = betweenness.get(node, 0)
            node_importance[str(node)] = (norm_deg + bet) / 2

        return {
            "node_count": num_nodes,
            "edge_count": num_edges,
            "entity_types": entity_types,
            "relation_types": relation_types,
            "density": density,
            "avg_degree": avg_degree,
            "avg_betweenness": avg_betweenness,
            "avg_property_sparsity": avg_property_sparsity,
            "type_consistency": type_consistency,
            "triples_entities_ratio": triples_entities_ratio,
            "avg_fan_out": avg_fan_out,
            "node_importance": node_importance,
            "is_connected": nx.is_weakly_connected(graph) if num_nodes > 0 else False
        }
