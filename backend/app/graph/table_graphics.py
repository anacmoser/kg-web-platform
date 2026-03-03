import networkx as nx
from typing import Dict, Any, List
import logging

logger = logging.getLogger(__name__)

class GraphAnalyzer:
    """
    Analyzes the semantic or structural graph to produce dashboards 
    and interactive metrics for the frontend interface.
    """
    def __init__(self, G: nx.DiGraph):
        self.G = G

    def get_summary_table(self) -> str:
        """Returns summarizing HTML table of graph metrics."""
        if self.G.number_of_nodes() == 0:
            return "<p>Empty Graph</p>"
            
        density = f"{nx.density(self.G):.4f}"
        nodes = self.G.number_of_nodes()
        edges = self.G.number_of_edges()
        
        html = f"""
        <table border="1" style="border-collapse: collapse; width: 100%;">
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Total Nodes</td><td>{nodes}</td></tr>
            <tr><td>Total Edges</td><td>{edges}</td></tr>
            <tr><td>Graph Density</td><td>{density}</td></tr>
        </table>
        """
        return html

    def get_node_type_distribution(self) -> Dict[str, int]:
        """Count for D3 or chart.js."""
        types = {}
        for _, attr in self.G.nodes(data=True):
            t = attr.get('type', 'UNKNOWN')
            types[t] = types.get(t, 0) + 1
        return types
        
    def get_top_hubs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Identify hub nodes by degree centralities."""
        degrees = dict(self.G.degree())
        sorted_nodes = sorted(degrees.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        results = []
        for n_id, deg in sorted_nodes:
            results.append({
                "id": str(n_id),
                "type": self.G.nodes[n_id].get("type", "UNKNOWN"),
                "degree": deg
            })
        return results

    def get_connectivity_chart_data(self) -> Dict[str, Any]:
        """Provides data payload to render the graph in a dashboard viewer widget."""
        from app.graph.serializers.graph_serializer import GraphSerializer
        return GraphSerializer().to_cytoscape(self.G)
