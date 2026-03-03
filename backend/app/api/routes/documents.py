from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import List, Dict, Any
from app.config import settings
import os
import logging
import shutil
from werkzeug.utils import secure_filename
from app.cache.strategies.redis_cache import cache
from app.pipeline.orchestrator import orchestrator

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_EXTENSIONS = {'pdf', 'csv', 'docx'}

def allowed_file(filename: str):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No selected file")
        
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        if not filename:
             raise HTTPException(status_code=400, detail="Invalid filename")
        save_path = settings.UPLOAD_DIR / filename
        logger.info(f"Saving uploaded file: {filename} to {save_path}")
        try:
            with open(save_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            logger.info(f"Successfully saved {filename} ({file.size or 'unknown'} bytes)")
        except Exception as e:
            logger.error(f"Failed to save file {filename}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
        
        return {
            "message": "File uploaded successfully",
            "filename": filename,
            "path": str(save_path)
        }
        
    raise HTTPException(status_code=400, detail="File type not allowed")


@router.get("/")
def list_documents():
    files = []
    for f in settings.UPLOAD_DIR.glob("*"):
        if f.is_file():
            files.append({
                "name": f.name,
                "size": f.stat().st_size,
                "created": f.stat().st_ctime
            })
    return files


@router.post("/clear")
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
        raise HTTPException(status_code=500, detail=f"Failed to delete files: {str(e)}")

    # 2. Clear job orchestrator
    orchestrator.jobs.clear()
    
    # 3. Invalidate result cache
    cache.invalidate_pattern("job_result_*")
    
    return {
        "status": "success",
        "message": "Repository and cache cleared successfully",
        "deleted_files": deleted_files
    }
