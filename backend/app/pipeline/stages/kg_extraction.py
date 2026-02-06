from typing import List, Dict, Any
import json
from openai import OpenAI
from app.config import settings
import logging

logger = logging.getLogger(__name__)

class KGExtractor:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.LLM_BASE_URL
        )
        self.model = settings.OPENAI_MODEL

    def extract_triples(self, chunk: Dict[str, Any], ontology: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extracts triples from a chunk based on the provided ontology.
        """
        # Prepare context from ontology
        entities_str = ", ".join([e["name"] for e in ontology.get("entities", [])])
        relations_str = ", ".join([r["label"] for r in ontology.get("relations", [])])
        
        prompt = f"""
        Extract Knowledge Graph triples from the text based strictly on the provided schema.
        
        ALLOWED ENTITY TYPES: {entities_str}
        ALLOWED RELATIONS: {relations_str}
        
        TEXT:
        {chunk["text"]}
        
        OUTPUT FORMAT (JSON list):
        [
            {{"source": "Entity Name", "source_type": "TYPE", "target": "Entity Name", "target_type": "TYPE", "relation": "RELATION"}}
        ]
        
        Rules:
        1. Only use allowed types and relations.
        2. Resolve pronouns where possible.
        3. Ignore irrelevant information.
        """
        
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "You are a precise Knowledge Graph extractor."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.0
            )
            
            raw_content = response.choices[0].message.content or ""
            content = self._parse_json(raw_content)
            usage = response.usage.model_dump() if hasattr(response, 'usage') else {}
            
            # Handle variations in JSON structure
            triples = []
            if isinstance(content, list):
                triples = content
            elif isinstance(content, dict):
                if "triples" in content:
                    triples = content["triples"]
                elif "result" in content:
                    triples = content["result"]
                else:
                    # Try to find the first list value
                    for val in content.values():
                        if isinstance(val, list):
                            triples = val
                            break
            
            # Ensure each triple has expected keys
            validated_triples = []
            for t in triples:
                if isinstance(t, dict) and all(k in t for k in ["source", "target", "relation"]):
                    validated_triples.append(t)
            
            return {
                "triples": validated_triples,
                "usage": usage
            }
                
        except Exception as e:
            logger.error(f"KG extraction failed for chunk {chunk.get('index')}: {e}")
            raise e

    def _parse_json(self, text: str) -> Any:
        """
        Robustly parses JSON from text, handling potential markdown wrappers.
        """
        text = text.strip()
        if not text:
            logger.error("LLM returned empty response content.")
            return []

        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract from markdown code blocks
        import re
        # Check for list [ ] or object { }
        json_match = re.search(r'```(?:json)?\s*([\[\{].*?[\]\}])\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Last resort: find first [ or { and last ] or }
        start_idx = min([idx for idx in [text.find('['), text.find('{')] if idx != -1] or [None])
        end_idx = max([idx for idx in [text.rfind(']'), text.rfind('}')] if idx != -1] or [None])
        
        if start_idx is not None and end_idx is not None:
            try:
                return json.loads(text[start_idx:end_idx+1])
            except json.JSONDecodeError:
                pass

        logger.error(f"Failed to parse JSON from response: {text[:500]}...")
        return {"triples": [], "usage": {}}
