"""AI-based PDF renaming: extract text, ask AI for a descriptive filename."""

import os
import re
import sys

import fitz  # pymupdf

from modules.api import ask_ai, ENV_KEYS


PROMPT_TEMPLATE = (
    "Analysiere den folgenden Text aus einem PDF-Dokument. "
    "Antworte NUR mit einem Dateinamen im Format YYYYMMDD-KurzBeschreibung "
    "(ohne .pdf). Das Datum soll das Dokumentdatum sein (nicht heute). "
    "Falls kein Datum erkennbar ist, verwende 00000000 als Datum. "
    "Falls der Inhalt nicht erkennbar oder unlesbar ist, antworte nur mit dem Datum "
    "(z.B. 00000000 oder das erkannte Datum). "
    "Die Beschreibung soll kurz und in CamelCase sein, z.B. "
    "20260301-DrHaderRechnung oder 20250115-FinanzamtBescheid. "
    "Antworte ausschliesslich mit dem Dateinamen, nichts anderes."
    "\n\n---\n\n{text}"
)


def extract_text(pdf_path):
    """Extract the text layer from a PDF via pymupdf."""
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    if not text.strip():
        raise ValueError("No text found in PDF (OCR layer present?)")
    return text.strip()


def analyze_pdf(pdf_path, config):
    """Extract text from the PDF and ask the AI for a filename."""
    text = extract_text(pdf_path)
    return ask_ai(PROMPT_TEMPLATE.format(text=text), config)


def sanitize_filename(name, original_path=None):
    """Validate and sanitize the AI-suggested filename."""
    name = name.strip().removesuffix(".pdf")
    name = re.sub(r"[^a-zA-Z0-9-]", "", name)
    if not re.match(r"^\d{8}(-[a-zA-Z0-9]+)?$", name):
        raise ValueError(f"AI returned invalid filename: '{name}'")
    # Replace placeholder date with date from original filename
    if name.startswith("00000000") and original_path:
        orig = os.path.splitext(os.path.basename(original_path))[0]
        m = re.match(r"^(\d{8})", orig)
        if m:
            name = m.group(1) + name[8:]
    # Skip if nothing meaningful was identified (same date, no description)
    if original_path:
        orig = os.path.splitext(os.path.basename(original_path))[0]
        orig_date = re.match(r"^(\d{8})", orig)
        if orig_date and name == orig_date.group(1):
            return None
    return name


def is_already_renamed(pdf_path):
    """Check if a file was already renamed (not a YYYYMMDD-HHMMSS timestamp name)."""
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    return not re.match(r"^\d{8}-\d{6}$", basename)


def resolve_target(directory, name):
    """Determine target path, appending a suffix for duplicates."""
    target = os.path.join(directory, f"{name}.pdf")
    if not os.path.exists(target):
        return target
    counter = 2
    while True:
        target = os.path.join(directory, f"{name}-{counter}.pdf")
        if not os.path.exists(target):
            return target
        counter += 1


def rename_pdf(pdf_path, config):
    """Analyze and rename a single PDF. Returns new path or None on failure."""
    try:
        suggested = analyze_pdf(pdf_path, config)
        name = sanitize_filename(suggested, pdf_path)
    except Exception as e:
        print(f"Rename error for {os.path.basename(pdf_path)}: {e}", file=sys.stderr)
        return None

    if name is None:
        return pdf_path

    directory = os.path.dirname(os.path.abspath(pdf_path))
    target = resolve_target(directory, name)
    os.rename(pdf_path, target)
    return target
