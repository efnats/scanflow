"""Subcommand: run OCR on PDFs that have no text layer."""

import os
import sys
import time

from modules.ocr import ocr_if_needed, _has_text

C_BOLD = "\033[1m"
C_DIM = "\033[90m"
C_GREEN = "\033[32m"
C_YELLOW = "\033[33m"
C_RED = "\033[31m"
C_RESET = "\033[0m"


def collect_pdfs(path, recursive):
    """Collect PDF files from a path (file or directory)."""
    if not os.path.isdir(path):
        return [path]
    if recursive:
        pdfs = []
        for root, _dirs, files in os.walk(path):
            for f in sorted(files):
                if f.lower().endswith(".pdf"):
                    pdfs.append(os.path.join(root, f))
        return sorted(pdfs)
    return sorted(
        os.path.join(path, f)
        for f in os.listdir(path)
        if f.lower().endswith(".pdf")
    )


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

    print(f"{C_BOLD}scanflow ocr{C_RESET} — OCR for PDFs without text layer")
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
            has_text = _has_text(pdf)
        except Exception:
            has_text = False
        if args.force or not has_text:
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
