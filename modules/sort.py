"""AI-based PDF sorting: move files into matching directory based on filename."""

import os
import shutil
import sys

from modules.api import ask_ai


PROMPT_TEMPLATE = (
    "Du bekommst einen PDF-Dateinamen und eine Liste von Zielordnern. "
    "Waehle den am besten passenden Ordner fuer diese Datei. "
    "Antworte NUR mit dem exakten Ordnerpfad aus der Liste, nichts anderes. "
    "Falls kein Ordner passt, antworte mit: NONE"
    "\n\nDateiname: {filename}"
    "\n\nOrdner:\n{folder_list}"
)


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


def suggest_folder(filename, folders, config):
    """Ask AI to suggest the best matching folder for a file."""
    folder_list = "\n".join(folders)
    prompt = PROMPT_TEMPLATE.format(filename=filename, folder_list=folder_list)
    suggestion = ask_ai(prompt, config)
    suggestion = suggestion.strip().strip("/")
    if suggestion == "NONE":
        return None
    # Verify suggestion is in the folder list
    if suggestion not in folders:
        # Try partial match (AI might return slightly different format)
        for f in folders:
            if f.rstrip("/") == suggestion.rstrip("/"):
                return f
        raise ValueError(f"AI suggested unknown folder: '{suggestion}'")
    return suggestion


def sort_pdf(pdf_path, base_dir, folders, config):
    """Suggest a target folder for a PDF. Returns (target_dir, target_path) or (None, None)."""
    filename = os.path.basename(pdf_path)
    try:
        folder = suggest_folder(filename, folders, config)
    except Exception as e:
        print(f"Sort error for {filename}: {e}", file=sys.stderr)
        return None, None

    if folder is None:
        return None, None

    target_dir = os.path.join(base_dir, folder)
    target_path = os.path.join(target_dir, filename)

    # Handle duplicates
    if os.path.exists(target_path):
        name, ext = os.path.splitext(filename)
        counter = 2
        while True:
            target_path = os.path.join(target_dir, f"{name}-{counter}{ext}")
            if not os.path.exists(target_path):
                break
            counter += 1

    return folder, target_path


def move_pdf(pdf_path, target_path):
    """Move a PDF to the target path."""
    shutil.move(pdf_path, target_path)
