from flask import Blueprint, request, jsonify
from app.config import settings
import os
import logging
from werkzeug.utils import secure_filename

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
        save_path = settings.UPLOAD_DIR / filename
        logger.info(f"Saving uploaded file: {filename} to {save_path}")
        file.save(save_path)
        
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
