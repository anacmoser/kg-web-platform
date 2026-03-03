import re
import math
import hashlib
import time
import logging
from functools import wraps
from app.config import NodeType, SemanticNodeType, EdgeType

logger = logging.getLogger(__name__)

def retry_with_exponential_backoff(
    initial_delay: float = 1.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    max_retries: int = 10,
    errors: tuple = (Exception,)
):
    """
    Retry a function with exponential backoff.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            num_retries = 0
            delay = initial_delay
            
            while True:
                try:
                    return func(*args, **kwargs)
                except errors as e:
                    num_retries += 1
                    if num_retries > max_retries:
                        logger.error(f"Max retries ({max_retries}) exceeded for {func.__name__}")
                        raise e
                    
                    import random
                    sleep_time = delay
                    if jitter:
                        sleep_time *= (1 + random.random() * 0.1)
                        
                    logger.warning(
                        f"Error in {func.__name__}: {e}. "
                        f"Retrying in {sleep_time:.2f}s (Attempt {num_retries}/{max_retries})"
                    )
                    
                    time.sleep(sleep_time)
                    delay *= exponential_base
        return wrapper
    return decorator

def make_doc_id(filename: str) -> str:
    hash_object = hashlib.sha256(filename.encode())
    return f"{NodeType['DOCUMENT']}_{hash_object.hexdigest()[:12]}"

def make_page_id(doc_id: str, page_num: int) -> str:
    return f"{doc_id}_{NodeType['PAGE']}_{page_num}"

def make_chunk_id(page_id: str, chunk_index: int) -> str:
    return f"{page_id}_{NodeType['CHUNK']}_{chunk_index}"

def make_section_id(doc_id: str, section_title: str) -> str:
    hash_object = hashlib.sha256(section_title.encode())
    return f"{doc_id}_{NodeType['SECTION']}_{hash_object.hexdigest()[:8]}"

def make_image_id(page_id: str, image_index: int) -> str:
    return f"{page_id}_{NodeType['IMAGE']}_{image_index}"

def make_table_id(page_id: str, table_index: int) -> str:
    return f"{page_id}_{NodeType['TABLE']}_{table_index}"

def make_label_id(entity_type_name: str) -> str:
    return f"{SemanticNodeType['ENTITY']}_{normalize_str(entity_type_name)}"

def make_entity_id(entity_type: str, entity_name: str) -> str:
    normalized = normalize_str(f"{entity_type}_{entity_name}")
    hash_obj = hashlib.sha256(normalized.encode()).hexdigest()[:8]
    return f"{SemanticNodeType['ENTITY']}_{hash_obj}"

def make_property_id(entity_id: str, prop_name: str) -> str:
    return f"{entity_id}_PROP_{normalize_str(prop_name)}"

def clean_text(text: str) -> str:
    if not text:
        return ""
    # Remove multiple spaces and newlines
    text = re.sub(r'\s+', ' ', text)
    # Remove unprintable characters
    text = "".join(c for c in text if c.isprintable())
    return text.strip()

def split_into_chunks(text: str, chunk_size: int = 1000, overlap: int = 200, min_length: int = 0) -> list[str]:
    """Basic text chunking algorithm considering word boundaries and minimum length."""
    if not text:
        return []
        
    words = text.split()
    chunks = []
    
    if len(words) <= chunk_size:
        if len(text) >= min_length:
            return [text]
        return []
        
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        if len(chunk) >= min_length:
            chunks.append(chunk)
        i += chunk_size - overlap
        
    return chunks

def detect_section_title(text: str) -> str:
    """Heuristic to find a potential section title in text."""
    lines = text.split('\n')
    for line in lines[:3]: # Look at first 3 lines
        cleaned = line.strip()
        # Typical header format checking
        if cleaned and len(cleaned) < 100 and (cleaned.isupper() or cleaned.title() == cleaned or re.match(r'^#+|\d+\.', cleaned)):
            return cleaned
    return ""

def truncate(text: str, max_length: int = 100) -> str:
    if not text: return ""
    if len(text) <= max_length: return text
    return text[:max_length-3] + "..."

def normalize_str(s: str) -> str:
    if not s:
        return ""
    # Lowercase, replace spaces and special chars with underscore
    s = s.lower()
    s = re.sub(r'[^a-z0-9]', '_', s)
    s = re.sub(r'_+', '_', s)
    return s.strip('_')
