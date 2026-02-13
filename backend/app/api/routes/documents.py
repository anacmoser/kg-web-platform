from flask import Blueprint, request, jsonify
from app.config import settings
import os
import logging
import shutil
from werkzeug.utils import secure_filename
from app.cache.strategies.redis_cache import cache
from app.pipeline.orchestrator import orchestrator

logger = logging.getLogger(__name__)

bp = Blueprint("documents", __name__)

ALLOWED_EXTENSIONS = {'pdf', 'csv', 'docx'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@bp.route("/upload", methods=["POST"])
def upload_document():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        if not filename:
             return jsonify({"error": "Invalid filename"}), 400
        save_path = settings.UPLOAD_DIR / filename
        logger.info(f"Saving uploaded file: {filename} to {save_path}")
        try:
            file.save(save_path)
            logger.info(f"Successfully saved {filename} ({file.content_length or 'unknown'} bytes)")
        except Exception as e:
            logger.error(f"Failed to save file {filename}: {e}")
            return jsonify({"error": f"Failed to save file: {str(e)}"}), 500
        
        return jsonify({
            "message": "File uploaded successfully",
            "filename": filename,
            "path": str(save_path)
        }), 201
        
    return jsonify({"error": "File type not allowed"}), 400

@bp.route("/", methods=["GET"])
def list_documents():
    files = []
    for f in settings.UPLOAD_DIR.glob("*"):
        if f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "created": f.stat().st_ctime
            })
    return jsonify(files)

@bp.route("/clear", methods=["POST"])
def clear_repository():
    """
    Clears all uploaded documents, cancels pending jobs, and flushes results cache.
    """
    logger.info("Clearing repository and cache...")
    
    # 1. Delete uploaded files
    deleted_files = 0
    try:
        for f in settings.UPLOAD_DIR.glob("*"):
            if f.is_file():
                os.remove(f)
                deleted_files += 1
        logger.info(f"Deleted {deleted_files} files from {settings.UPLOAD_DIR}")
    except Exception as e:
        logger.error(f"Error deleting files: {e}")
        return jsonify({"error": f"Failed to delete files: {str(e)}"}), 500

    # 2. Clear job orchestrator
    orchestrator.jobs.clear()
    
    # 3. Invalidate result cache
    cache.invalidate_pattern("job_result_*")
    
    return jsonify({
        "status": "success",
        "message": "Repository and cache cleared successfully",
        "deleted_files": deleted_files
    })
