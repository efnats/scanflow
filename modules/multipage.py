"""Duplex scanning: reverse even pages and interleave with odd pages."""

import subprocess


def reverse_pdf(input_pdf, output_pdf):
    """Reverse page order of a PDF (for even pages scanned in reverse)."""
    result = subprocess.run(
        ["pdftk", input_pdf, "cat", "end-1", "output", output_pdf],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pdftk reverse failed: {result.stderr.strip()}")


def interleave_pdfs(odd_file, even_file, output_file):
    """Interleave odd and (reversed) even page PDFs into one document."""
    result = subprocess.run(
        [
            "pdftk",
            f"A={odd_file}",
            f"B={even_file}",
            "shuffle", "A", "B",
            "output", output_file,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pdftk interleave failed: {result.stderr.strip()}")
