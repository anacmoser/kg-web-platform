from fastapi import APIRouter, HTTPException
from app.pipeline.orchestrator import orchestrator

router = APIRouter()

@router.get("/{job_id}")
def get_ontology(job_id: str):
    """
    Get ontology data for a job.
    """
    job_status = orchestrator.get_job_status(job_id)
    
    if job_status.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Ontology is available after the ontology stage completes
    results = job_status.get("results", {})
    ontology = results.get("ontology", {"entities": [], "relations": []})
    
    # Add counts from graph stats if available
    graph_stats = results.get("graph_stats", {})
    entity_types = graph_stats.get("entity_types", {})
    relation_types = graph_stats.get("relation_types", {})
    
    # Enrich ontology with counts
    entities_with_counts = []
    for entity in ontology.get("entities", []):
        entity_copy = entity.copy()
        entity_copy["count"] = entity_types.get(entity.get("name"), 0)
        entities_with_counts.append(entity_copy)
    
    relations_with_counts = []
    for relation in ontology.get("relations", []):
        relation_copy = relation.copy()
        relation_copy["count"] = relation_types.get(relation.get("label"), 0)
        relations_with_counts.append(relation_copy)
    
    return {
        "job_id": job_id,
        "status": job_status.get("status"),
        "entities": entities_with_counts,
        "relations": relations_with_counts
    }
