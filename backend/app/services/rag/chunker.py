"""Document text extraction and semantic chunking service."""

import io
import re
from typing import Any, Dict, List, Optional
from backend.app.core.logging import get_logger

logger = get_logger("services.rag.chunker")


def extract_text_from_bytes(file_bytes: bytes, filename: str, content_type: Optional[str] = None) -> str:
    """Extract plain text from uploaded file bytes (PDF, DOCX, TXT, MD, CSV, JSON)."""
    fn_lower = filename.lower()
    ct_lower = (content_type or "").lower()

    # 1. PDF Documents
    if fn_lower.endswith(".pdf") or "pdf" in ct_lower:
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            extracted_pages = []
            for i, page in enumerate(doc):
                text = page.get_text()
                if text and text.strip():
                    extracted_pages.append(f"--- Page {i + 1} ---\n{text.strip()}")
            doc.close()
            return "\n\n".join(extracted_pages)
        except Exception as e:
            logger.error("Failed to parse PDF %s with PyMuPDF: %s", filename, e)
            raise ValueError(f"Could not parse PDF document: {e}")

    # 2. DOCX Word Documents
    if fn_lower.endswith(".docx") or "wordprocessingml" in ct_lower:
        try:
            import docx
            doc_file = io.BytesIO(file_bytes)
            doc = docx.Document(doc_file)
            doc_paragraphs: List[str] = []

            for p in doc.paragraphs:
                text = p.text.strip()
                if text:
                    doc_paragraphs.append(text)

            # Also extract structured tables if present
            for table in doc.tables:
                for row in table.rows:
                    cells_text = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                    if cells_text:
                        doc_paragraphs.append(" | ".join(cells_text))

            return "\n\n".join(doc_paragraphs)
        except Exception as e:
            logger.error("Failed to parse DOCX %s with python-docx: %s", filename, e)
            raise ValueError(f"Could not parse DOCX document: {e}")

    # 3. Fallback to UTF-8 / latin-1 decoding for text files (TXT, MD, CSV, JSON)
    try:
        return file_bytes.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return file_bytes.decode("latin-1")
        except Exception as e:
            raise ValueError(f"Unable to decode text document {filename}: {e}")


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> List[Dict[str, Any]]:
    """Semantically split text into chunks with sliding overlap window.
    
    Prioritizes paragraph breaks, sentence breaks, and word boundaries.
    """
    if not text or not text.strip():
        return []

    # Clean redundant whitespace while preserving paragraph breaks
    cleaned_text = re.sub(r"\r\n", "\n", text).strip()
    
    # Split by paragraph blocks
    paragraphs = [p.strip() for p in cleaned_text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [cleaned_text]

    chunks: List[Dict[str, Any]] = []
    current_chunk = ""
    chunk_index = 0

    for para in paragraphs:
        # If single paragraph exceeds chunk_size, split by sentences or words
        if len(para) > chunk_size:
            sentences = re.split(r"(?<=[.!?])\s+", para)
            for sent in sentences:
                if len(current_chunk) + len(sent) + 1 > chunk_size and current_chunk:
                    chunk_str = current_chunk.strip()
                    chunks.append({
                        "chunk_index": chunk_index,
                        "chunk_content": chunk_str,
                        "token_count": len(chunk_str.split()),
                    })
                    chunk_index += 1
                    # Sliding overlap
                    if overlap > 0 and len(chunk_str) > overlap:
                        current_chunk = chunk_str[-overlap:] + " " + sent
                    else:
                        current_chunk = sent
                else:
                    current_chunk = f"{current_chunk} {sent}".strip()
        else:
            if len(current_chunk) + len(para) + 2 > chunk_size and current_chunk:
                chunk_str = current_chunk.strip()
                chunks.append({
                    "chunk_index": chunk_index,
                    "chunk_content": chunk_str,
                    "token_count": len(chunk_str.split()),
                })
                chunk_index += 1
                if overlap > 0 and len(chunk_str) > overlap:
                    current_chunk = chunk_str[-overlap:] + "\n\n" + para
                else:
                    current_chunk = para
            else:
                current_chunk = f"{current_chunk}\n\n{para}".strip() if current_chunk else para

    # Flush final chunk
    if current_chunk.strip():
        chunk_str = current_chunk.strip()
        chunks.append({
            "chunk_index": chunk_index,
            "chunk_content": chunk_str,
            "token_count": len(chunk_str.split()),
        })

    return chunks
