"""Shared PDF text extraction with OCR-on-demand fallback."""

import fitz  # pymupdf

from modules.ocr import ocr_if_needed


def extract_text(pdf_path, max_chars=None):
    """Extract text and keywords from a PDF. Runs OCR if no text layer found.

    Returns (text, keywords). Raises ValueError if no text even after OCR.
    """
    text, keywords = _read_text(pdf_path, max_chars)
    if text:
        return text, keywords

    ocr_if_needed(pdf_path)

    text, keywords = _read_text(pdf_path, max_chars)
    if not text:
        raise ValueError("No text found in PDF even after OCR")
    return text, keywords


def _read_text(pdf_path, max_chars=None):
    """Read text and keywords from PDF metadata via pymupdf."""
    doc = fitz.open(pdf_path)
    keywords = (doc.metadata or {}).get("keywords", "") or ""
    text = ""
    for page in doc:
        text += page.get_text()
        if max_chars and len(text) >= max_chars:
            break
    doc.close()
    if max_chars:
        text = text[:max_chars]
    return text.strip(), keywords.strip()
