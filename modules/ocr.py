"""OCR processing via ocrmypdf."""

import subprocess


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
