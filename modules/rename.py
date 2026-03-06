"""AI-based PDF renaming: extract text, ask AI for a descriptive filename."""

import os
import re
import sys

import fitz  # pymupdf

from modules.api import ask_ai, ENV_KEYS
from modules.text import extract_text


PROMPT_TEMPLATE = (
    "Analysiere den folgenden Text aus einem PDF-Dokument. "
    "Antworte mit genau 2 Zeilen:\n"
    "Zeile 1: Dateiname im Format YYYYMMDD-KurzBeschreibung "
    "(ohne .pdf). Das Datum soll das Dokumentdatum sein (nicht heute). "
    "Falls kein Datum erkennbar ist, verwende 00000000 als Datum. "
    "Falls der Inhalt nicht erkennbar oder unlesbar ist, antworte nur mit dem Datum "
    "(z.B. 00000000 oder das erkannte Datum). "
    "Die Beschreibung soll kurz und in CamelCase sein, z.B. "
    "20260301-DrHaderRechnung oder 20250115-FinanzamtBescheid.\n"
    "Zeile 2: 3-5 Schlagwoerter (kommagetrennt, kleingeschrieben), die den Inhalt "
    "kategorisieren, z.B. gesundheit, rechnung, orthopaedie, arzt"
    "\n\n---\n\n{text}"
)


def analyze_pdf(pdf_path, config):
    """Extract text from the PDF and ask the AI for a filename and keywords.

    Returns (suggested_name, keywords_string). Keywords may be empty.
    """
    text, _ = extract_text(pdf_path)
    response = ask_ai(PROMPT_TEMPLATE.format(text=text), config)
    lines = response.strip().splitlines()
    suggested_name = lines[0].strip()
    keywords = lines[1].strip() if len(lines) > 1 else ""
    return suggested_name, keywords


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
    # Skip if only a date without description (not a meaningful rename)
    if re.match(r"^\d{8}$", name):
        return None
    return name


def write_keywords(pdf_path, keywords):
    """Write keywords into PDF metadata."""
    if not keywords:
        return
    try:
        doc = fitz.open(pdf_path)
        metadata = doc.metadata or {}
        metadata["keywords"] = keywords
        doc.set_metadata(metadata)
        doc.saveIncr()
        doc.close()
    except Exception as e:
        print(f"Warning: Could not write keywords to {os.path.basename(pdf_path)}: {e}",
              file=sys.stderr)


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
    """Analyze and rename a single PDF. Writes keywords to PDF metadata. Returns new path or None on failure."""
    try:
        suggested, keywords = analyze_pdf(pdf_path, config)
        name = sanitize_filename(suggested, pdf_path)
    except Exception as e:
        print(f"Rename error for {os.path.basename(pdf_path)}: {e}", file=sys.stderr)
        return None

    write_keywords(pdf_path, keywords)

    if name is None:
        return pdf_path

    directory = os.path.dirname(os.path.abspath(pdf_path))
    target = resolve_target(directory, name)
    os.rename(pdf_path, target)
    return target
