"""Subcommand: run OCR on PDFs that have no text layer."""

import os
import sys
import time

from cli.common import collect_pdfs, C_BOLD, C_DIM, C_GREEN, C_RED, C_RESET
from modules.ocr import ocr_if_needed, has_text


def setup_parser(subparsers):
    """Register the 'ocr' subcommand."""
    p = subparsers.add_parser("ocr", help="Run OCR on PDFs that have no text layer")
    p.add_argument("path", help="Path to a PDF file or directory containing PDFs")
    p.add_argument("-r", "--recursive", action="store_true",
                    help="Process subdirectories recursively")
    p.add_argument("--force", action="store_true",
                    help="Re-run OCR even on files that already have a text layer")
    p.add_argument("--dry-run", action="store_true",
                    help="Only show which files need OCR, do not process")
    p.set_defaults(func=main)


def main(args):
    """Run OCR on PDFs without a text layer."""
    if not os.path.exists(args.path):
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    print(f"{C_BOLD}scanflow ocr{C_RESET} - OCR for PDFs without text layer")
    print()

    pdfs = collect_pdfs(args.path, args.recursive)
    if not pdfs:
        print(f"No PDF files found in {args.path}", file=sys.stderr)
        sys.exit(1)

    # Filter: check which files need OCR
    pending = []
    skipped = 0
    for pdf in pdfs:
        try:
            pdf_has_text = has_text(pdf)
        except Exception:
            pdf_has_text = False
        if args.force or not pdf_has_text:
            pending.append(pdf)
        else:
            skipped += 1

    print(f"  {C_DIM}Path:{C_RESET} {args.path}")
    print(f"  {C_DIM}Total:{C_RESET} {len(pdfs)} PDF(s)")
    print(f"  {C_DIM}Need OCR:{C_RESET} {len(pending)}")
    if skipped:
        print(f"  {C_DIM}Skipped (have text):{C_RESET} {skipped}")
    if args.force and skipped == 0:
        print(f"  {C_DIM}Mode:{C_RESET} force (re-OCR all)")

    if not pending:
        print(f"\n{C_GREEN}All files already have a text layer.{C_RESET}")
        return

    if args.dry_run:
        print()
        for pdf in pending:
            print(f"  {os.path.relpath(pdf, args.path) if os.path.isdir(args.path) else os.path.basename(pdf)}")
        return

    print()
    errors = 0
    for i, pdf in enumerate(pending, 1):
        name = os.path.relpath(pdf, args.path) if os.path.isdir(args.path) else os.path.basename(pdf)
        progress = f"{C_DIM}[{i}/{len(pending)}]{C_RESET}"
        try:
            t0 = time.monotonic()
            ocr_if_needed(pdf, force=args.force)
            elapsed = time.monotonic() - t0
            print(f"{progress} {C_GREEN}OK{C_RESET} {name} {C_DIM}({elapsed:.1f}s){C_RESET}")
        except Exception as e:
            print(f"{progress} {C_RED}FAIL{C_RESET} {name}: {e}", file=sys.stderr)
            errors += 1

    print()
    if errors:
        print(f"{C_RED}{errors} file(s) failed.{C_RESET}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"{C_GREEN}Done. {len(pending)} file(s) processed.{C_RESET}")
