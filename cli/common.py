"""Shared CLI utilities: PDF collection, ANSI colors."""

import os

# ANSI colors
C_BOLD = "\033[1m"
C_DIM = "\033[90m"
C_GREEN = "\033[32m"
C_CYAN = "\033[36m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_RESET = "\033[0m"


ALWAYS_EXCLUDE = {"_failed"}


def collect_pdfs(path, recursive, exclude_dirs=None):
    """Collect PDF files from a path (file or directory).

    exclude_dirs: set of directory names to skip during recursive walk.
    _failed/ is always excluded.
    """
    skip = ALWAYS_EXCLUDE | (exclude_dirs or set())
    if not os.path.isdir(path):
        return [path]
    if recursive:
        pdfs = []
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in sorted(files):
                if f.lower().endswith(".pdf"):
                    pdfs.append(os.path.join(root, f))
        return sorted(pdfs)
    return sorted(
        os.path.join(path, f)
        for f in os.listdir(path)
        if f.lower().endswith(".pdf")
    )
