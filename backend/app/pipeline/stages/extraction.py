from pathlib import Path
from typing import Dict, Any, List
import pandas as pd
import fitz  # PyMuPDF
from docx import Document as DocxDocument
import logging

logger = logging.getLogger(__name__)

class DocumentExtractor:
    """Handles extraction from heterogeneous document sources"""
    
    def __init__(self):
        # No heavy model initialization needed for PyMuPDF
        pass
        
    def extract(self, file_path: Path) -> Dict[str, Any]:
        """
        Extracting content into a standardized format.
        """
        ext = file_path.suffix.lower()
        
        try:
            if ext == '.pdf':
                return self._extract_pdf(file_path)
            elif ext == '.csv':
                return self._extract_csv(file_path)
            elif ext == '.docx':
                return self._extract_docx(file_path)
            else:
                raise ValueError(f"Unsupported format: {ext}")
        except Exception as e:
            logger.error(f"Extraction failed for {file_path}: {e}")
            raise

    def _extract_pdf(self, path: Path) -> Dict[str, Any]:
        text = ""
        page_count = 0
        try:
            with fitz.open(path) as doc:
                page_count = len(doc)
                for page in doc:
                    text += page.get_text() + "\n\n"
        except Exception as e:
            logger.error(f"PyMuPDF failed to extract {path}: {e}")
            raise

        return {
            "text": text,
            "metadata": {"filename": path.name, "pages": page_count},
            "type": "pdf"
        }

    def _extract_csv(self, path: Path) -> Dict[str, Any]:
        logger.info(f"Extracting CSV from {path}")
        try:
            # Try UTF-8 first
            logger.info("Attempting UTF-8 encoding...")
            df = pd.read_csv(path, encoding='utf-8')
        except UnicodeDecodeError:
            # Fallback to Latin-1 for common Brazilian characters
            logger.info("UTF-8 failed, falling back to Latin-1 encoding...")
            df = pd.read_csv(path, encoding='latin1')
        except Exception as e:
            logger.error(f"CSV read failed: {e}")
            raise
        # specialized representation for CSV: row-based text or raw data
        # converting to text representation for semantic analysis
        text_repr = df.to_markdown(index=False)
        return {
            "text": text_repr,
            "metadata": {"columns": list(df.columns), "rows": len(df)},
            "type": "csv"
        }

    def _extract_docx(self, path: Path) -> Dict[str, Any]:
        doc = DocxDocument(path)
        text = "\n\n".join([p.text for p in doc.paragraphs if p.text.strip()])
        return {
            "text": text,
            "metadata": {"paragraphs": len(doc.paragraphs)},
            "type": "docx"
        }
