from typing import List, Dict, Any
from langchain_text_splitters import RecursiveCharacterTextSplitter
from app.config import settings
import logging

logger = logging.getLogger(__name__)

class ChunkingEngine:
    """
    Lightweight chunking using RecursiveCharacterTextSplitter.
    Fast and requires zero local compute.
    """
    
    def __init__(self):
        # Increased overlap and size for better context retention
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=4000,
            chunk_overlap=400,
            separators=["\n\n", "\n", ".", " ", ""]
        )

    def chunk(self, content: Dict[str, Any]) -> List[Dict[str, Any]]:
        text = content.get("text", "")
        if not text:
            return []
            
        logger.info(f"Chunking document with length {len(text)}...")
        
        # Create LangChain documents
        docs = self.splitter.create_documents([text])
        
        # Convert back to our internal dictionary format
        chunks = []
        for i, doc in enumerate(docs):
            chunks.append({
                "index": i,
                "text": doc.page_content,
                "tokens": len(doc.page_content.split()), # roughly
                "source": content.get("metadata", {}),
                "type": content.get("type", "unknown")
            })
            
        logger.info(f"Created {len(chunks)} chunks.")
        return chunks
