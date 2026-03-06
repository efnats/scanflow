"""AI-based PDF sorting: move files into matching directory based on filename and content."""

import os
import shutil
import sys

import fitz  # pymupdf

from modules.api import ask_ai

MAX_TEXT_CHARS = 2000

PROMPT_TEMPLATE = (
    "Du bekommst einen PDF-Dateinamen, den Textinhalt des PDFs, "
    "und eine Liste von Zielordnern. "
    "Waehle die passendsten Ordner fuer diese Datei, sortiert nach Wahrscheinlichkeit. "
    "Antworte NUR mit den exakten Ordnerpfaden aus der Liste, einer pro Zeile, "
    "der beste zuerst. Maximal 5 Vorschlaege. "
    "Falls kein Ordner passt, antworte mit: NONE"
    "\n\nDateiname: {filename}"
    "\n\nTextinhalt:\n{text}"
    "\n\nOrdner:\n{folder_list}"
)

REFINE_PROMPT_TEMPLATE = (
    "Du bekommst einen PDF-Dateinamen, den Textinhalt des PDFs, "
    "und eine Liste von Ueberordnern (Kategorien). "
    "Waehle die 5 relevantesten Kategorien fuer diese Datei, sortiert nach Wahrscheinlichkeit. "
    "Antworte NUR mit den exakten Kategorienamen aus der Liste, einer pro Zeile."
    "\n\nDateiname: {filename}"
    "\n\nTextinhalt:\n{text}"
    "\n\nKategorien:\n{category_list}"
)

CREATE_PROMPT_TEMPLATE = (
    "Du bekommst einen PDF-Dateinamen, den Textinhalt des PDFs, "
    "und einen Ueberordner. Schlage 5 passende Unterordnernamen vor, "
    "die als neues Verzeichnis unter dem Ueberordner angelegt werden koennten. "
    "Die Namen sollen kurz, beschreibend und im gleichen Stil wie bestehende Ordner sein. "
    "Antworte NUR mit den Ordnernamen, einer pro Zeile, ohne Pfadpraefixe."
    "\n\nDateiname: {filename}"
    "\n\nTextinhalt:\n{text}"
    "\n\nUeberordner: {parent}"
    "\n\nBestehende Unterordner:\n{existing}"
)


def extract_pdf_text(pdf_path):
    """Extract text from the first pages of a PDF, truncated to MAX_TEXT_CHARS.

    Returns (text, keywords) where keywords is from PDF metadata (may be empty).
    """
    try:
        doc = fitz.open(pdf_path)
        keywords = (doc.metadata or {}).get("keywords", "") or ""
        text = ""
        for page in doc:
            text += page.get_text()
            if len(text) >= MAX_TEXT_CHARS:
                break
        doc.close()
        return text[:MAX_TEXT_CHARS].strip(), keywords.strip()
    except Exception:
        return "", ""


def scan_directory_tree(base_dir):
    """Recursively scan a directory and return all subfolder paths (relative to base)."""
    folders = []
    for root, dirs, _files in os.walk(base_dir):
        # Skip hidden directories
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        rel = os.path.relpath(root, base_dir)
        if rel != ".":
            folders.append(rel)
    return sorted(folders)


def _match_folder(candidate, folders):
    """Match a candidate string against the folder list. Returns matched folder or None."""
    candidate = candidate.strip().strip("/")
    if candidate in folders:
        return candidate
    for f in folders:
        if f.rstrip("/") == candidate.rstrip("/"):
            return f
    return None


def suggest_folders(filename, folders, config, text=""):
    """Ask AI to suggest matching folders ranked by likelihood. Returns list of folder strings."""
    folder_list = "\n".join(folders)
    prompt = PROMPT_TEMPLATE.format(filename=filename, text=text or "(nicht verfuegbar)", folder_list=folder_list)
    response = ask_ai(prompt, config).strip()
    if response == "NONE":
        return []
    matched = []
    for line in response.splitlines():
        folder = _match_folder(line, folders)
        if folder and folder not in matched:
            matched.append(folder)
    return matched


def suggest_parent_folders(filename, folders, config, prefix="", text=""):
    """Ask AI to suggest the most relevant parent categories for refinement.

    If prefix is given, returns next-level children under that prefix.
    Returns up to 5 parent folder names (without trailing slash).
    """
    # Determine the depth level to extract
    depth = prefix.count("/") if prefix else 0
    parents = set()
    for f in folders:
        parts = f.split("/")
        if len(parts) > depth:
            if prefix and not f.startswith(prefix):
                continue
            parents.add("/".join(parts[:depth + 1]))
    parents = sorted(parents)
    if not parents:
        return []
    if len(parents) <= 5:
        return parents

    category_list = "\n".join(parents)
    prompt = REFINE_PROMPT_TEMPLATE.format(
        filename=filename, text=text or "(nicht verfuegbar)",
        category_list=category_list
    )
    response = ask_ai(prompt, config).strip()
    matched = []
    for line in response.splitlines():
        candidate = line.strip().strip("/")
        if candidate in parents and candidate not in matched:
            matched.append(candidate)
    return matched[:5]


def suggest_new_subfolders(filename, parent, folders, config, text=""):
    """Ask AI to suggest 5 new subfolder names under parent. Returns list of folder names."""
    existing = [f.split("/")[-1] for f in folders if f.startswith(parent + "/")
                and f.count("/") == parent.count("/") + 1]
    existing_str = "\n".join(existing) if existing else "(keine)"
    prompt = CREATE_PROMPT_TEMPLATE.format(
        filename=filename, text=text or "(nicht verfuegbar)",
        parent=parent, existing=existing_str
    )
    response = ask_ai(prompt, config).strip()
    names = []
    for line in response.splitlines():
        name = line.strip().strip("/")
        if name and "/" not in name and name not in names and name not in existing:
            names.append(name)
    return names[:5]


def resolve_target_path(directory, filename):
    """Build target path, appending -2, -3 etc. if file already exists."""
    target = os.path.join(directory, filename)
    if not os.path.exists(target):
        return target
    name, ext = os.path.splitext(filename)
    counter = 2
    while os.path.exists(os.path.join(directory, f"{name}-{counter}{ext}")):
        counter += 1
    return os.path.join(directory, f"{name}-{counter}{ext}")


MAX_FOLDERS_DIRECT = 200


def _filter_by_keywords(folders, keywords):
    """Pre-filter folders using keywords from PDF metadata. Returns matching folders or all if no match."""
    if not keywords:
        return None
    kw_list = [k.strip().lower() for k in keywords.split(",") if k.strip()]
    if not kw_list:
        return None
    matched = []
    for f in folders:
        f_lower = f.lower()
        if any(kw in f_lower for kw in kw_list):
            matched.append(f)
    return matched if matched else None


def sort_pdf(pdf_path, base_dir, folders, config):
    """Suggest a target folder for a PDF. Returns (folder, target_path, alternatives, text).

    For large folder trees (>MAX_FOLDERS_DIRECT), uses a two-step approach:
    1. Try keyword-based pre-filtering from PDF metadata (free, no API call)
    2. Fall back to AI parent categories (cheap, short list)
    3. Ask AI for exact folders only within the narrowed subtree

    Raises on API errors (caller handles). Returns (None, None, [], text) if no match.
    """
    filename = os.path.basename(pdf_path)
    text, keywords = extract_pdf_text(pdf_path)

    if len(folders) <= MAX_FOLDERS_DIRECT:
        search_folders = folders
    else:
        # Try keyword pre-filter first (no API call)
        kw_filtered = _filter_by_keywords(folders, keywords)
        if kw_filtered and len(kw_filtered) <= MAX_FOLDERS_DIRECT:
            search_folders = kw_filtered
        else:
            # Fall back to AI parent categories
            top_parents = suggest_parent_folders(filename, folders, config, prefix="", text=text)
            if not top_parents:
                return None, None, [], text
            search_folders = []
            for f in folders:
                for p in top_parents:
                    if f == p or f.startswith(p + "/"):
                        search_folders.append(f)
                        break

    ranked = suggest_folders(filename, search_folders, config, text=text)

    if not ranked:
        return None, None, [], text

    folder = ranked[0]
    alternatives = ranked[1:]
    target_path = resolve_target_path(os.path.join(base_dir, folder), filename)

    return folder, target_path, alternatives, text


def move_pdf(pdf_path, target_path):
    """Move a PDF to the target path."""
    shutil.move(pdf_path, target_path)
