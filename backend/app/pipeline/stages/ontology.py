from typing import List, Dict, Any
import json
from openai import OpenAI
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Updated prompt with user-requested limits (50 entities, 100 relations)
ONTOLOGY_PROMPT = """
Analyze the following text sample from a document collection and identify the best Ontology schema.

1. ENTITIES (max 50 - be comprehensive):
   - PERSON: Full names, authors, researchers
   - ORGANIZATION: Institutions, companies
   - CONCEPT: Diseases, treatments, theories
   - TERM: Technical terms, genes, molecules
   - LOCATION: Countries, cities, institutions
   - DATE: Periods, years, events
   - ADAPT: Create new types if the domain requires it (e.g. "PROTEIN", "LEGISLATION")

2. RELATIONS (max 100 - capture nuances):
   - CAUSAL: causes, leads_to, results_in
   - ASSOCIATIVE: associated_with, related_to, correlates_with
   - HIERARCHICAL: is_a, part_of, subclass_of
   - TEMPORAL: implies, precedes, follows
   - FUNCTIONAL: treats, targets, regulates, owns

FORMAT: JSON only.
{
  "entities": [
    {"name": "TypeName", "description": "Brief description"}
  ],
  "relations": [
    {"label": "RELATION_NAME", "source": "TypeName", "target": "TypeName", "description": "..."}
  ]
}
"""

class OntologyBuilder:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.LLM_BASE_URL
        )
        self.model = settings.OPENAI_MODEL

    def build(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Builds an ontology by analyzing a representative sample of chunks.
        """
        # Select representative chunks (e.g., first few and some from middle)
        sample_size = min(5, len(chunks))
        sample_text = "\n---\n".join([c["text"][:2000] for c in chunks[:sample_size]])
        
        logger.info(f"Generating ontology using {self.model} via Direct OpenAI...")
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": ONTOLOGY_PROMPT},
                    {"role": "user", "content": sample_text}
                ],
                temperature=0.1
            )
            
            raw_content = response.choices[0].message.content or ""
            ontology = self._parse_json(raw_content)
            usage = response.usage.model_dump() if hasattr(response, 'usage') else {}

            logger.info(f"Discovered {len(ontology.get('entities', []))} entities and {len(ontology.get('relations', []))} relations.")
            return {
                "ontology": ontology,
                "usage": usage
            }
            
        except Exception as e:
            logger.error(f"Ontology generation failed: {e}")
            return {"ontology": {"entities": [], "relations": []}, "usage": {}, "error": str(e)}

    def _parse_json(self, text: str) -> Dict[str, Any]:
        """
        Robustly parses JSON from text, handling potential markdown wrappers.
        """
        text = text.strip()
        if not text:
            logger.error("LLM returned empty response content.")
            return {"entities": [], "relations": []}

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract from markdown code blocks
        import re
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Last resort: find first { and last }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass

        logger.error(f"Failed to parse JSON from response: {text[:500]}...")
        return {"ontology": {"entities": [], "relations": []}, "usage": {}}
