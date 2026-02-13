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
        
        self._stages_initialized = False
        self.extractor = None
        self.chunker = None
        self.ontology_builder = None
        self.kg_extractor = None
        self.normalizer = None
        self.graph_builder = None

    def _ensure_initialized(self):
        if self._stages_initialized:
            return
            
        logger.info("Initializing Pipeline Stages (Lazy Load)...")
        # Initialize stages
        self.extractor = DocumentExtractor()
        self.chunker = ChunkingEngine()
        self.ontology_builder = OntologyBuilder()
        self.kg_extractor = KGExtractor()
        self.normalizer = NormalizationStage()
        self.graph_builder = GraphBuilder()
        self._stages_initialized = True
        logger.info("Pipeline Stages Initialized.")

    def start_job(self, document_paths: List[Any], config: Dict[str, Any] = None) -> str:
        self._ensure_initialized()
        job_id = str(uuid.uuid4())
        
        self.jobs[job_id] = {
            "id": job_id,
            "status": "queued",
            "progress": 0.0,
            "current_stage": "queued",
            "results": {},
            "usage": {"input_tokens": 0, "output_tokens": 0, "total_cost": 0.0},
            "error": None,
            "filenames": [str(p.name) for p in document_paths]
        }
        
        # Submit to thread pool
        self.executor.submit(self._run_pipeline, job_id, document_paths, config or {})
        
        return job_id

    def get_job_status(self, job_id: str) -> Dict[str, Any]:
        job = self.jobs.get(job_id)
        
        # If not in memory, try disk storage first (most reliable)
        if not job:
            import json
            # Try to find by UUID suffix (glob)
            matches = list(settings.RESULTS_DIR.glob(f"*_{job_id}.json"))
            if not matches and (settings.RESULTS_DIR / f"{job_id}.json").exists():
                matches = [settings.RESULTS_DIR / f"{job_id}.json"]
                
        if matches:
            try:
                with open(matches[0], 'r', encoding='utf-8') as f:
                    job = json.load(f)
                    # Cache it back to memory for speed
                    self.jobs[job_id] = job
            except Exception as e:
                logger.error(f"Error loading job from disk {job_id}: {e}")

        # If still not found, try Redis cache
        if not job:
            from app.cache.strategies.redis_cache import cache
            cache_key = f"job_full_state_{job_id}"
            job = cache.get(cache_key)
            
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
        import time
        start_time = time.time()
        
        try:
            job["status"] = "processing"
            job["start_time"] = start_time
            job["estimated_total_time"] = 30.0 + (len(doc_paths) * 10.0) # Heuristic
            
            # STAGE 1: Extraction
            job["current_stage"] = "extraction"
            extracted_docs = []
            for i, path in enumerate(doc_paths):
                # Update progress within stage
                job["progress"] = (i / len(doc_paths)) * 0.15
                res = self.extractor.extract(path, config)
                extracted_docs.append(res)
            job["progress"] = 0.15
            
            # STAGE 2: Chunking
            job["current_stage"] = "chunking"
            all_chunks = []
            for i, doc in enumerate(extracted_docs):
                job["progress"] = 0.15 + (i / len(extracted_docs)) * 0.10
                chunks = self.chunker.chunk(doc)
                all_chunks.extend(chunks)
            job["progress"] = 0.25
            
            # STAGE 3: Ontology
            job["current_stage"] = "ontology"
            ontology_res = self.ontology_builder.build(all_chunks)
            ontology = ontology_res.get("ontology", ontology_res)
            self._update_job_usage(job, ontology_res.get("usage", {}))
            
            job["results"]["ontology"] = ontology
            job["progress"] = 0.40
            
            # STAGE 4: KG Extraction
            job["current_stage"] = "kg_extraction"
            all_triples = []
            total = len(all_chunks)
            
            # Refined estimation
            initial_heuristic = 3.0 + (len(doc_paths) * 5.0) + (total * 0.5)
            
            for i, chunk in enumerate(all_chunks):
                kg_res = self.kg_extractor.extract_triples(
                    chunk, 
                    ontology, 
                    user_instructions=config.get("user_instructions", "")
                )
                triples = kg_res.get("triples", [])
                self._update_job_usage(job, kg_res.get("usage", {}))
                
                all_triples.extend(triples)
                # Granular updates: 0.40 to 0.85
                job["progress"] = 0.40 + (0.45 * (i / total if total > 0 else 1))
                
                # Smoother time estimation: 
                # Combine initial heuristic with actual speed, weighted by progress
                elapsed = time.time() - start_time
                if job["progress"] > 0:
                    real_time_est = elapsed / job["progress"]
                    # As progress increases, we trust real-time data more
                    weight = job["progress"]
                    job["estimated_total_time"] = (real_time_est * weight) + (initial_heuristic * (1 - weight))
            
            # STAGE 5: Normalization
            job["current_stage"] = "normalization"
            normalized_triples = self.normalizer.normalize(all_triples)
            job["progress"] = 0.90
            
            # STAGE 6: Graph Building
            job["current_stage"] = "graph_building"
            graph_result = self.graph_builder.build_graph(normalized_triples)
            
            # Store NetworkX graph (internal) and serialized formats (public)
            job["results"]["_graph"] = graph_result["graph"]
            job["results"]["cytoscape"] = graph_result["cytoscape"]
            job["results"]["graph_stats"] = graph_result["stats"]
            
            # --- Result Caching ---
            from app.cache.strategies.redis_cache import cache
            cache_key_base = f"job_result_{job_id}"
            cache.set(f"{cache_key_base}_ontology", ontology)
            cache.set(f"{cache_key_base}_cytoscape", graph_result["cytoscape"])
            cache.set(f"{cache_key_base}_stats", graph_result["stats"])
            
            job["progress"] = 1.0
            job["status"] = "completed"
            job["end_time"] = time.time()
            job["duration"] = job["end_time"] - start_time
            
        except Exception as e:
            logger.exception(f"Job {job_id} failed")
            job["status"] = "failed"
            job["error"] = str(e)
        finally:
            # --- ALWAYS SAVE STATE FOR PERSISTENCE ---
            import json
            from app.cache.strategies.redis_cache import cache
            
            # 1. Disk (backend/app/storage/results)
            # Use primary filename + UUID for easier manual lookup
            primary_name = job.get("filenames", ["result"])[0]
            # Sanitize name
            import re
            safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', primary_name)
            
            result_path = settings.RESULTS_DIR / f"{safe_name}_{job_id}.json"
            try:
                # Filter out the NetworkX graph object for JSON serialization
                serializable_job = job.copy()
                if "results" in job:
                    serializable_job["results"] = {k: v for k, v in job["results"].items() if k != "_graph"}
                
                with open(result_path, 'w', encoding='utf-8') as f:
                    json.dump(serializable_job, f, indent=2, ensure_ascii=False)
                logger.info(f"💾 Job {job_id} state persisted to {result_path} (Status: {job['status']})")
            except Exception as e_save:
                logger.error(f"❌ Critical failure saving job {job_id}: {e_save}")

            # 2. Redis Cache
            try:
                cache.set(f"job_full_state_{job_id}", job)
            except:
                pass
            # ----------------------------------------

# Global instance
orchestrator = PipelineOrchestrator()
