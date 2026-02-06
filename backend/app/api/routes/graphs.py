from flask import Blueprint, jsonify
from app.pipeline.orchestrator import orchestrator

bp = Blueprint("graphs", __name__)

@bp.route("/<job_id>", methods=["GET"])
def get_graph(job_id):
    """
    Get graph data for a completed job in Cytoscape.js format.
    """
    job_status = orchestrator.get_job_status(job_id)
    
    if job_status.get("status") == "not_found":
        return jsonify({"error": "Job not found"}), 404
    
    if job_status.get("status") != "completed":
        return jsonify({
            "error": "Graph not ready",
            "status": job_status.get("status"),
            "progress": job_status.get("progress", 0)
        }), 202
    
    # Get serialized graph data
    results = job_status.get("results", {})
    cytoscape_data = results.get("cytoscape", {"elements": {"nodes": [], "edges": []}})
    graph_stats = results.get("graph_stats", {})
    
    return jsonify({
        "job_id": job_id,
        "graph": cytoscape_data,
        "stats": graph_stats
    })

