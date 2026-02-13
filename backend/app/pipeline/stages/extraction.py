import logging
import base64
from pathlib import Path
from typing import Dict, Any, List, Optional
import pandas as pd
from docling.document_converter import DocumentConverter
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from app.config import settings

logger = logging.getLogger(__name__)

class DocumentExtractor:
    """Handles extraction from heterogeneous document sources using Docling for structural precision."""
    
    def __init__(self):
        # Docling handles multiple formats (PDF, DOCX, HTML, etc)
        self.converter = DocumentConverter()
        # Keep vision model for specialized image deep-dive if needed
        self.vision_model = ChatOpenAI(model="gpt-4o", max_tokens=300)
        
    def extract(self, file_path: Path, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Extracting content into a standardized format using Docling.
        """
        config = config or {}
        ext = file_path.suffix.lower()
        
        try:
            # Special handling for CSV as pandas is more direct for plain data
            if ext == '.csv':
                return self._extract_csv(file_path)
            
            logger.info(f"Using Docling to extract {file_path}")
            result = self.converter.convert(str(file_path))
            
            # Export to markdown to preserve H1, H2, Tables, and Lists for the KG
            text_content = result.document.export_to_markdown()
            
            # Additional structural metadata can be added here from result.document
            
            return {
                "text": text_content,
                "metadata": {
                    "filename": file_path.name,
                    "type": ext.replace('.', ''),
                    "engine": "docling",
                    "pages": getattr(result.document, 'num_pages', 0)
                },
                "type": ext.replace('.', '')
            }

        except Exception as e:
            logger.error(f"Extraction failed for {file_path}: {e}")
            raise

    def _extract_csv(self, path: Path) -> Dict[str, Any]:
        logger.info(f"Extracting CSV from {path}")
        try:
            # Try UTF-8 first
            df = pd.read_csv(path, encoding='utf-8')
        except UnicodeDecodeError:
            # Fallback to Latin-1 for common Brazilian characters
            df = pd.read_csv(path, encoding='latin1')
        except Exception as e:
            logger.error(f"CSV read failed: {e}")
            raise
            
        text_repr = df.to_markdown(index=False)
        return {
            "text": text_repr,
            "metadata": {"columns": list(df.columns), "rows": len(df)},
            "type": "csv"
        }

    def _describe_image(self, image_bytes: bytes) -> str:
        """
        Sends image to GPT-4o for a concise description relevant to KG construction.
        """
        try:
            # Encode to base64
            base64_image = base64.b64encode(image_bytes).decode('utf-8')
            
            messages = [
                HumanMessage(
                    content=[
                        {"type": "text", "text": "Describe this chart, graph, or diagram in detail. Focus on entities, relationships, numbers, and trends. If it's a decorative image, just say 'Decorative image'."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                )
            ]
            
            response = self.vision_model.invoke(messages)
            return response.content
        except Exception as e:
            logger.error(f"Image analysis error: {e}")
            return "Error analyzing image."
