import os
import sys
from pathlib import Path

# Add backend to path
sys.path.append(str(Path(__file__).parent / "backend"))

from app.pipeline.stages.extraction import DocumentExtractor
from app.pipeline.stages.kg_extraction import KGExtractor
from app.pipeline.stages.normalization import NormalizationStage

def test_extraction():
    extractor = DocumentExtractor()
    # Create a dummy markdown file to test Docling (or just check if it initializes)
    print("Testing Docling initialization...")
    try:
        # Just check if converter is there
        print(f"Converter: {extractor.converter}")
        print("✅ Docling initialized.")
    except Exception as e:
        print(f"❌ Docling failed: {e}")

def test_normalization():
    norm = NormalizationStage()
    triples = [
        {"source": "PIB", "source_type": "ECONOMIA", "target": "Brasil", "target_type": "LOCAL", "relation": "calculado_em"},
        {"source": "Produto Interno Bruto", "source_type": "ECONOMIA", "target": "BR", "target_type": "LOCAL", "relation": "medido_em"},
        {"source": "PIB", "source_type": "ORGANIZACAO", "target": "IBGE", "target_type": "ORG", "relation": "calculado_por"}
    ]
    normalized = norm.normalize(triples)
    print("\nTesting Normalization (Type-Aware):")
    for t in normalized:
        print(f"  {t['source']} ({t.get('source_type')}) -> {t['relation']} -> {t['target']} ({t.get('target_type')})")
    
    # Check if PIB (ECONOMIA) and Produto Interno Bruto (ECONOMIA) merged
    # but PIB (ORGANIZACAO) stayed separate or merged correctly if types allowed.
    print(f"\nFinal triple count: {len(normalized)}")

if __name__ == "__main__":
    test_extraction()
    test_normalization()
