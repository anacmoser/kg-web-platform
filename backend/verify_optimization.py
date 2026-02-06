import os
import sys
from pathlib import Path

# Add app to path
sys.path.append(str(Path(__file__).parent))

def verify():
    print("--- Knowledge Graph Optimization Verification ---")
    
    # 1. Check imports
    try:
        import fitz
        print("[OK] PyMuPDF (fitz) is installed.")
    except ImportError:
        print("[FAIL] PyMuPDF is NOT installed.")
        
    try:
        import rapidfuzz
        print("[OK] RapidFuzz is installed.")
    except ImportError:
        print("[FAIL] RapidFuzz is NOT installed.")
        
    try:
        from app.pipeline.stages.extraction import DocumentExtractor
        from app.pipeline.stages.chunking import ChunkingEngine
        from app.pipeline.stages.normalization import NormalizationStage
        print("[OK] Pipeline stages imported correctly.")
    except Exception as e:
        print(f"[FAIL] Failed to import pipeline stages: {e}")
        
    # 2. Check configuration
    from app.config import settings
    print(f"[OK] MAX_WORKERS set to: {settings.MAX_WORKERS}")
    if settings.MAX_WORKERS > 1:
        print("[WARNING] MAX_WORKERS is higher than 1. This might be heavy for low-resource machines.")
    
    # 3. Quick test of Normalization
    try:
        norm = NormalizationStage(threshold=80)
        triples = [
            {"source": "USA", "target": "China", "relation": "trades_with"},
            {"source": "United States", "target": "China", "relation": "trades_with"}
        ]
        result = norm.normalize(triples)
        print(f"[OK] Normalization test: Reduced {len(triples)} to {len(result)} triples.")
        if len(result) == 1:
            print("   (Successfully merged USA and United States)")
    except Exception as e:
        print(f"[FAIL] Normalization test failed: {e}")

    print("--- Verification Finished ---")

if __name__ == "__main__":
    verify()
