from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from app.pipeline.orchestrator import orchestrator
from app.config import settings
from pathlib import Path

router = APIRouter()

class PipelineStartRequest(BaseModel):
    filenames: List[str]
    config: Optional[Dict[str, Any]] = {}

@router.post("/start", status_code=202)
def start_pipeline(req: PipelineStartRequest):
    if not req.filenames:
        raise HTTPException(status_code=400, detail="No filenames provided")
        
    # Convert filenames to absolute paths
    doc_paths = [settings.UPLOAD_DIR / f for f in req.filenames]
    
    # Start async job
    job_id = orchestrator.start_job(doc_paths, req.config)
    
    return {
        "job_id": job_id,
        "status": "queued",
        "message": "Pipeline started successfully"
    }

@router.get("/status/{job_id}")
def get_status(job_id: str):
    status = orchestrator.get_job_status(job_id)
    if status.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Job not found")
        
    return status
