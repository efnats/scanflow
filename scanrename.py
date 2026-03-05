#!/usr/bin/env python3
"""Standalone CLI: rename PDFs based on AI content analysis."""

import argparse
import os
import sys
import time

import requests

from config import load_config
from modules.rename import (
    analyze_pdf,
    is_already_renamed,
    rename_pdf,
    resolve_target,
    sanitize_filename,
)

INITIAL_BATCH_DELAY = 2  # seconds between files in auto mode


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


def confirm_rename(old_name, new_name):
    """Ask user to confirm a rename. Returns True if confirmed."""
    try:
        answer = input("  Rename? [Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("", "y", "yes", "j", "ja")


def process_single_pdf(pdf_path, config, dry_run, auto_yes, index=0, total=0):
    """Process a single PDF file. Returns (success, rate_limited) tuple."""
    progress = f"[{index}/{total}]" if total else ""
    old_name = os.path.basename(pdf_path)

    try:
        suggested = analyze_pdf(pdf_path, config)
        name = sanitize_filename(suggested, pdf_path)
    except requests.exceptions.HTTPError as e:
        rate_limited = e.response is not None and e.response.status_code == 429
        print(f"\n{progress} {old_name}\n  ERROR: {e}", file=sys.stderr)
        return False, rate_limited
    except Exception as e:
        print(f"\n{progress} {old_name}\n  ERROR: {e}", file=sys.stderr)
        return False, False

    if name is None:
        print(f"\n{progress} {old_name}\n  Skipped (no meaningful name found)")
        return True, False

    new_name = f"{name}.pdf"

    if dry_run:
        print(f"\n{progress} {old_name}\n  -> {new_name}")
        return True, False

    directory = os.path.dirname(os.path.abspath(pdf_path))
    target = resolve_target(directory, name)
    new_name = os.path.basename(target)

    print(f"\n{progress} {old_name}\n  -> {new_name}")

    if not auto_yes and not confirm_rename(old_name, new_name):
        print("  Skipped.")
        return True, False

    os.rename(pdf_path, target)
    if auto_yes:
        print("  Done.")
    return True, False


def main():
    parser = argparse.ArgumentParser(description="Rename PDFs based on AI content analysis")
    parser.add_argument("path", help="Path to a PDF file or directory containing PDFs")
    parser.add_argument("--config", default=None,
                        help="Path to config file (default: /etc/scanflow.conf, "
                             "~/.config/scanflow/scanflow.conf, ./scanflow.conf)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only print suggested name, do not rename")
    parser.add_argument("--force", action="store_true",
                        help="Re-process files that were already renamed")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Process subdirectories recursively")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Skip confirmation prompt, rename automatically")
    args = parser.parse_args()

    if not os.path.exists(args.path):
        print(f"Error: Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    config = load_config(args.config)

    if not config.has_option("general", "provider"):
        print("Error: Config must contain [general] provider", file=sys.stderr)
        sys.exit(1)

    pdfs = collect_pdfs(args.path, args.recursive)

    if not pdfs:
        print(f"No PDF files found in {args.path}", file=sys.stderr)
        sys.exit(1)

    if not args.force:
        skipped = [p for p in pdfs if is_already_renamed(p)]
        pdfs = [p for p in pdfs if not is_already_renamed(p)]
        if skipped:
            print(f"Skipping {len(skipped)} already renamed file(s) (use --force to re-process)")

    if not pdfs:
        print("No unprocessed PDF files found.")
        return

    print(f"Processing {len(pdfs)} PDF(s)")
    errors = 0
    last_api_call = 0
    batch_delay = INITIAL_BATCH_DELAY
    for i, pdf in enumerate(pdfs):
        if not args.dry_run and args.yes:
            elapsed = time.monotonic() - last_api_call
            if last_api_call and elapsed < batch_delay:
                time.sleep(batch_delay - elapsed)
        last_api_call = time.monotonic()
        success, rate_limited = process_single_pdf(pdf, config, args.dry_run, args.yes, i + 1, len(pdfs))
        if not success:
            errors += 1
        if rate_limited:
            batch_delay = min(batch_delay * 2, 30)
            print(f"  Increasing delay to {batch_delay}s", file=sys.stderr)
    if errors:
        print(f"\n{errors} file(s) with errors.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nAborted.")
        sys.exit(130)
