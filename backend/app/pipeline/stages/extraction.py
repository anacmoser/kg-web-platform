import logging
import base64
from pathlib import Path
from typing import Dict, Any, List, Optional
import pandas as pd
import fitz  # PyMuPDF
import pymupdf4llm
from docx import Document
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from app.config import settings

logger = logging.getLogger(__name__)

class DocumentExtractor:
    """Handles extraction from heterogeneous document sources using PyMuPDF and python-docx."""
    
    def __init__(self):
        # Keep vision model for specialized image deep-dive if needed
        self.vision_model = ChatOpenAI(model="gpt-4o", max_tokens=300)
        
    def extract(self, file_path: Path, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Extracting content into a standardized format.
        """
        config = config or {}
        ext = file_path.suffix.lower()
        
        try:
            if ext == '.csv':
                return self._extract_csv(file_path)
            elif ext == '.pdf':
                return self._extract_pdf(file_path)
            elif ext in ['.docx', '.doc']:
                return self._extract_docx(file_path)
            else:
                # Fallback to plain text for unknown formats
                return self._extract_text(file_path)

        except Exception as e:
            logger.error(f"Extraction failed for {file_path}: {e}")
            raise

    def _extract_pdf(self, file_path: Path) -> Dict[str, Any]:
        logger.info(f"Using PyMuPDF4LLM to extract {file_path}")
        md_text = pymupdf4llm.to_markdown(str(file_path))
        
        # Get page count using base pymupdf
        doc = fitz.open(str(file_path))
        num_pages = len(doc)
        doc.close()
        
        return {
            "text": md_text,
            "metadata": {
                "filename": file_path.name,
                "type": "pdf",
                "engine": "pymupdf4llm",
                "pages": num_pages
            },
            "type": "pdf"
        }

    def _extract_docx(self, file_path: Path) -> Dict[str, Any]:
        logger.info(f"Using python-docx to extract {file_path}")
        doc = Document(file_path)
        full_text = []
        for para in doc.paragraphs:
            # Basic markdown-like conversion
            if para.style.name.startswith('Heading'):
                level = para.style.name.split()[-1]
                if level.isdigit():
                    prefix = '#' * int(level) + ' '
                else:
                    prefix = '# '
                full_text.append(prefix + para.text)
            else:
                full_text.append(para.text)
        
        return {
            "text": "\n\n".join(full_text),
            "metadata": {
                "filename": file_path.name,
                "type": "docx",
                "engine": "python-docx"
            },
            "type": "docx"
        }

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

    def _extract_text(self, path: Path) -> Dict[str, Any]:
        logger.info(f"Extracting plain text from {path}")
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            text = path.read_text(encoding='latin1')
            
        return {
            "text": text,
            "metadata": {"filename": path.name},
            "type": "txt"
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
