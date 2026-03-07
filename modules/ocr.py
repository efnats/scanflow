"""OCR processing via ocrmypdf."""

import os
import subprocess
import tempfile

import fitz  # pymupdf


def ocr_file(input_file, output_file):
    """Run OCR on a PDF: deskew, correct images, rotate, eng+deu."""
    result = subprocess.run(
        [
            "ocrmypdf",
            "-d", "-i", "-r",
            "-l", "eng+deu",
            "-O", "2",
            "--skip-text",
            "-q",
            input_file,
            output_file,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ocrmypdf failed: {result.stderr.strip()}")


def has_text(pdf_path):
    """Check if a PDF has any extractable text."""
    doc = fitz.open(pdf_path)
    for page in doc:
        if page.get_text().strip():
            doc.close()
            return True
    doc.close()
    return False


def ocr_if_needed(pdf_path, force=False):
    """Run OCR on a PDF in-place if it has no text layer.

    If force=True, always re-run OCR regardless of existing text.
    Returns True if OCR was performed, False if text already present.
    """
    if not force and has_text(pdf_path):
        return False
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf", dir=os.path.dirname(pdf_path))
    os.close(fd)
    try:
        ocr_file(pdf_path, tmp_path)
        os.replace(tmp_path, pdf_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    return True
