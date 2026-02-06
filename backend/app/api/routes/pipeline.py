from flask import Blueprint, jsonify, request
from app.pipeline.orchestrator import orchestrator
from app.config import settings
from pathlib import Path

bp = Blueprint("pipeline", __name__)

@bp.route("/start", methods=["POST"])
def start_pipeline():
    data = request.get_json()
    filenames = data.get("filenames", [])
    
    if not filenames:
        return jsonify({"error": "No filenames provided"}), 400
        
    # Convert filenames to absolute paths
    doc_paths = [settings.UPLOAD_DIR / f for f in filenames]
    
    # Start async job
    job_id = orchestrator.start_job(doc_paths, data.get("config", {}))
    
    return jsonify({
        "job_id": job_id,
        "status": "queued",
        "message": "Pipeline started successfully"
    }), 202

@bp.route("/status/<job_id>", methods=["GET"])
def get_status(job_id):
    status = orchestrator.get_job_status(job_id)
    if status.get("status") == "not_found":
        return jsonify({"error": "Job not found"}), 404
        
    return jsonify(status)
