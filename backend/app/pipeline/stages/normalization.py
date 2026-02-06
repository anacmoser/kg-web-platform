from typing import List, Dict, Any
from rapidfuzz import process, fuzz
import logging

logger = logging.getLogger(__name__)

class NormalizationStage:
    """
    Normalizes entities to reduce redundancy in the Knowledge Graph.
    Uses fuzzy matching to merge similar entities without heavy local models.
    """
    
    def __init__(self, threshold: int = 85):
        self.threshold = threshold

    def normalize(self, triples: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Groups similar entities and updates triples.
        """
        if not triples:
            return []
            
        logger.info(f"Normalizing {len(triples)} triples...")
        
        # 1. Collect all unique entity names
        entities = set()
        for t in triples:
            entities.add(t["source"])
            entities.add(t["target"])
            
        entity_list = sorted(list(entities))
        canonical_map = {}
        
        # 2. Simple Entity Resolution
        # We iterate and find clusters of similar names
        processed = set()
        for entity in entity_list:
            if entity in processed:
                continue
                
            # Find similar names that haven't been mapped yet
            matches = process.extract(
                entity, 
                [e for e in entity_list if e not in processed], 
                scorer=fuzz.WRatio, 
                limit=10
            )
            
            # Group them under the first (usually shortest or first alphabetical) name
            for match_name, score, _ in matches:
                if score >= self.threshold:
                    canonical_map[match_name] = entity
                    processed.add(match_name)
        
        # 3. Update triples with canonical names
        normalized_triples = []
        seen_triples = set()
        
        for t in triples:
            new_source = canonical_map.get(t["source"], t["source"])
            new_target = canonical_map.get(t["target"], t["target"])
            
            # Avoid self-loops created by normalization
            if new_source == new_target:
                continue
                
            triple_key = (new_source, new_target, t["relation"])
            if triple_key not in seen_triples:
                normalized_t = t.copy()
                normalized_t["source"] = new_source
                normalized_t["target"] = new_target
                normalized_triples.append(normalized_t)
                seen_triples.add(triple_key)
                
        logger.info(f"Normalization complete. Reduced {len(triples)} to {len(normalized_triples)} triples.")
        return normalized_triples
