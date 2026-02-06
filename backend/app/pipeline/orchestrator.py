import uuid
import threading
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, List
from app.config import settings

# Stages
from app.pipeline.stages.extraction import DocumentExtractor
from app.pipeline.stages.chunking import ChunkingEngine
from app.pipeline.stages.ontology import OntologyBuilder
from app.pipeline.stages.kg_extraction import KGExtractor
from app.pipeline.stages.normalization import NormalizationStage
from app.pipeline.stages.graph_builder import GraphBuilder

logger = logging.getLogger(__name__)

class PipelineOrchestrator:
    def __init__(self):
        # In-memory job store (replace with Redis in prod)
        self.jobs: Dict[str, Dict[str, Any]] = {}
        # Thread pool for async execution
        self.executor = ThreadPoolExecutor(max_workers=settings.MAX_WORKERS)
        
        # Initialize stages
        self.extractor = DocumentExtractor()
        self.chunker = ChunkingEngine()
        self.ontology_builder = OntologyBuilder()
        self.kg_extractor = KGExtractor()
        self.normalizer = NormalizationStage()
        self.graph_builder = GraphBuilder()

    def start_job(self, document_paths: List[Any], config: Dict[str, Any] = None) -> str:
        job_id = str(uuid.uuid4())
        
        self.jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "progress": 0.0,
            "current_stage": "queued",
            "results": {},
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_cost": 0.0},
            "error": None
        }
        
        # Submit to thread pool
        self.executor.submit(self._run_pipeline, job_id, document_paths, config or {})
        
        return job_id

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        job = self.jobs.get(job_id)
        if not job:
            return {"status": "not_found"}
        
        # Create a copy and filter out non-serializable/internal items (starting with _)
        public_job = job.copy()
        public_job["results"] = {k: v for k, v in job.get("results", {}).items() if not k.startswith("_")}
        
        return public_job

    def _update_job_usage(self, job: Dict[str, Any], usage: Dict[str, Any]):
        """
        Updates job token usage and calculates cumulative cost.
        """
        if not usage:
            return
            
        job["usage"]["input_tokens"] += usage.get("prompt_tokens", 0)
        job["usage"]["output_tokens"] += usage.get("completion_tokens", 0)
        
        # Calculate cost
        model = settings.OPENAI_MODEL
        pricing = settings.MODEL_PRICING.get(model, (0.0, 0.0))
        
        input_cost = (job["usage"]["input_tokens"] / 1_000_000) * pricing[0]
        output_cost = (job["usage"]["output_tokens"] / 1_000_000) * pricing[1]
        
        job["usage"]["total_cost"] = round(input_cost + output_cost, 6)

    def _run_pipeline(self, job_id: str, doc_paths: List[Any], config: Dict[str, Any]):
        job = self.jobs[job_id]
        
        try:
            job["status"] = "processing"
            
            # STAGE 1: Extraction
            job["current_stage"] = "extraction"
            extracted_docs = []
            for path in doc_paths:
                res = self.extractor.extract(path)
                extracted_docs.append(res)
            job["progress"] = 0.2
            
            # STAGE 2: Chunking
            job["current_stage"] = "chunking"
            all_chunks = []
            for doc in extracted_docs:
                chunks = self.chunker.chunk(doc)
                all_chunks.extend(chunks)
            job["progress"] = 0.4
            
            # STAGE 3: Ontology
            job["current_stage"] = "ontology"
            ontology_res = self.ontology_builder.build(all_chunks)
            ontology = ontology_res.get("ontology", ontology_res) # Handle both formats
            self._update_job_usage(job, ontology_res.get("usage", {}))
            
            job["results"]["ontology"] = ontology
            job["progress"] = 0.6
            
            # STAGE 4: KG Extraction
            job["current_stage"] = "kg_extraction"
            all_triples = []
            total = len(all_chunks)
            for i, chunk in enumerate(all_chunks):
                kg_res = self.kg_extractor.extract_triples(chunk, ontology)
                triples = kg_res.get("triples", [])
                self._update_job_usage(job, kg_res.get("usage", {}))
                
                all_triples.extend(triples)
                # Granular updates
                job["progress"] = 0.6 + (0.2 * (i / total))
            
            # STAGE 5: Normalization
            job["current_stage"] = "normalization"
            normalized_triples = self.normalizer.normalize(all_triples)
            job["progress"] = 0.9
            
            # STAGE 6: Graph Building
            job["current_stage"] = "graph_building"
            graph_result = self.graph_builder.build_graph(normalized_triples)
            
            # Store NetworkX graph (internal) and serialized formats (public)
            job["results"]["_graph"] = graph_result["graph"]
            job["results"]["cytoscape"] = graph_result["cytoscape"]
            job["results"]["graph_stats"] = graph_result["stats"]
            
            job["progress"] = 1.0
            job["status"] = "completed"
            
        except Exception as e:
            logger.exception(f"Job {job_id} failed")
            job["status"] = "failed"
            job["error"] = str(e)

# Global instance
orchestrator = PipelineOrchestrator()
