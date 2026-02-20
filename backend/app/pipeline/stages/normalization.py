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
        Groups similar entities and updates triples, considering entity types.
        """
        if not triples:
            return []
            
        logger.info(f"Normalizing {len(triples)} triples...")
        
        # 1. Collect all unique entity names and their types (Case-insensitive initial grouping)
        entity_info = {} # lower_name -> { "names": set(original_names), "types": set(types) }
        for t in triples:
            for side, type_side in [("source", "source_type"), ("target", "target_type")]:
                name = str(t[side]).strip()
                etype = t.get(type_side, "UNKNOWN")
                lower_name = name.lower()
                if lower_name not in entity_info:
                    entity_info[lower_name] = {"names": set(), "types": set()}
                entity_info[lower_name]["names"].add(name)
                entity_info[lower_name]["types"].add(etype)
            
        # Select best representative for each identical-but-case-different group
        entity_list = []
        canonical_map = {} # lower_name -> best_original_name
        
        for lower_name, info in entity_info.items():
            # Heuristic: prefer names with more uppercase or no special chars
            best_name = sorted(list(info["names"]), key=lambda x: (len([c for c in x if c.isupper()]), -len(x)))[-1]
            entity_list.append(best_name)
            canonical_map[lower_name] = best_name
            
        entity_list.sort()
        
        # 2. Entity Resolution (Fuzzy/Acronym/Substring)
        processed = set()
        final_canonical = {} # original_name -> final_name

        for entity in entity_list:
            if entity in processed:
                continue
            
            processed.add(entity)
            current_canonical = entity
            final_canonical[entity] = current_canonical
            
            # Find candidates for merging
            candidates = [e for e in entity_list if e not in processed]
            if not candidates:
                continue
                
            matches = process.extract(
                entity, 
                candidates, 
                scorer=fuzz.WRatio, 
                limit=20
            )
            
            entity_types = entity_info[entity.lower()]["types"]
            
            for match_name, score, _ in matches:
                is_match = score >= self.threshold
                if not is_match:
                    is_match = self._is_acronym_match(entity, match_name)
                if not is_match and len(entity) > 10 and len(match_name) > 10:
                    if entity.lower() in match_name.lower() or match_name.lower() in entity.lower():
                        is_match = True

                if is_match:
                    match_types = entity_info[match_name.lower()]["types"]
                    is_compatible = len(entity_types.intersection(match_types)) > 0 or "UNKNOWN" in entity_types or "UNKNOWN" in match_types
                    
                    if is_compatible:
                        final_canonical[match_name] = current_canonical
                        processed.add(match_name)
        
        # 3. Update triples
        normalized_triples = []
        seen_triples = set()
        
        for t in triples:
            src = str(t["source"]).strip()
            tgt = str(t["target"]).strip()
            
            # Map original name -> case-normalized -> fuzzy-canonical
            new_source = final_canonical.get(canonical_map.get(src.lower(), src), src)
            new_target = final_canonical.get(canonical_map.get(tgt.lower(), tgt), tgt)
            
            if new_source.lower() == new_target.lower():
                continue
                
            triple_key = (new_source.lower(), new_target.lower(), str(t["relation"]).lower())
            if triple_key not in seen_triples:
                normalized_t = t.copy()
                normalized_t["source"] = new_source
                normalized_t["target"] = new_target
                normalized_triples.append(normalized_t)
                seen_triples.add(triple_key)
                
        logger.info(f"Normalization complete. Reduced {len(triples)} to {len(normalized_triples)} triples.")
        return normalized_triples

    def _is_acronym_match(self, name1: str, name2: str) -> bool:
        """Checks if one name could be an acronym of the other."""
        # Normalize: remove common connecting words in PT
        stop_words = {"da", "de", "do", "das", "dos", "e", "para", "com"}
        
        def get_acronym(text: str) -> str:
            words = [w for w in text.split() if w.lower() not in stop_words]
            if len(words) < 2: return ""
            return "".join([w[0] for w in words]).upper()

        n1, n2 = name1.strip().upper(), name2.strip().upper()
        # If one is short (acronym) and the other is long
        if 2 <= len(n1) <= 6 and len(n2) > 10:
            return n1 == get_acronym(name2)
        if 2 <= len(n2) <= 6 and len(n1) > 10:
            return n2 == get_acronym(name1)
        
        return False
