#!/usr/bin/env python3
"""Standalone CLI: sort PDFs into matching directories based on AI analysis."""

import argparse
import os
import sys
import time

import requests

from config import load_config
from modules.sort import scan_directory_tree, sort_pdf, move_pdf

INITIAL_BATCH_DELAY = 2


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


def confirm_move(filename, folder, folders):
    """Ask user to confirm a move. Returns (action, folder_override).

    action: 'move', 'skip', or 'choose'
    folder_override: chosen folder path (only when action='choose'), else None
    """
    try:
        answer = input("  [Y]es / [n]o / [c]hoose folder: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return "skip", None
    if answer in ("", "y", "yes", "j", "ja"):
        return "move", None
    if answer in ("c", "choose", "wählen"):
        return choose_folder(folders)
    return "skip", None


def choose_folder(folders):
    """Show numbered folder list and let user pick. Returns (action, folder_override)."""
    print("  Available folders:")
    for i, f in enumerate(folders, 1):
        print(f"    {i}) {f}")
    try:
        answer = input("  Folder number (0 to skip): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return "skip", None
    if not answer:
        return "skip", None
    try:
        num = int(answer)
    except ValueError:
        print("  Invalid number.")
        return "skip", None
    if num == 0:
        return "skip", None
    if num < 1 or num > len(folders):
        print("  Invalid number.")
        return "skip", None
    return "choose", folders[num - 1]


def process_single_pdf(pdf_path, base_dir, folders, config, dry_run, auto_yes, index=0, total=0):
    """Sort a single PDF. Returns (success, rate_limited) tuple."""
    progress = f"[{index}/{total}]" if total else ""
    filename = os.path.basename(pdf_path)

    try:
        folder, target_path = sort_pdf(pdf_path, base_dir, folders, config)
    except requests.exceptions.HTTPError as e:
        rate_limited = e.response is not None and e.response.status_code == 429
        print(f"\n{progress} {filename}\n  ERROR: {e}", file=sys.stderr)
        return False, rate_limited
    except Exception as e:
        print(f"\n{progress} {filename}\n  ERROR: {e}", file=sys.stderr)
        return False, False

    if folder is None:
        print(f"\n{progress} {filename}\n  Skipped (no matching folder found)")
        return True, False

    target_name = os.path.basename(target_path)
    print(f"\n{progress} {filename}\n  -> {folder}/{target_name}")

    if dry_run:
        return True, False

    if not auto_yes:
        action, folder_override = confirm_move(filename, folder, folders)
        if action == "skip":
            print("  Skipped.")
            return True, False
        if action == "choose" and folder_override:
            folder = folder_override
            target_path = os.path.join(base_dir, folder, target_name)
            print(f"  -> {folder}/{target_name}")

    move_pdf(pdf_path, target_path)
    if auto_yes:
        print("  Done.")
    return True, False


def main():
    parser = argparse.ArgumentParser(description="Sort PDFs into directories based on AI analysis")
    parser.add_argument("source", help="PDF file or directory containing PDFs to sort")
    parser.add_argument("target", help="Target directory tree to sort into")
    parser.add_argument("--config", default=None,
                        help="Path to config file (default: /etc/scanflow.conf, "
                             "~/.config/scanflow/scanflow.conf, ./scanflow.conf)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Only show suggestions, do not move files")
    parser.add_argument("-r", "--recursive", action="store_true",
                        help="Search source subdirectories recursively")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Skip confirmation prompt, move automatically")
    args = parser.parse_args()

    if not os.path.exists(args.source):
        print(f"Error: Source not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(args.target):
        print(f"Error: Target directory not found: {args.target}", file=sys.stderr)
        sys.exit(1)

    config = load_config(args.config)

    if not config.has_option("general", "provider"):
        print("Error: Config must contain [general] provider", file=sys.stderr)
        sys.exit(1)

    # Scan target directory tree
    print(f"Scanning directory tree: {args.target}")
    folders = scan_directory_tree(args.target)
    if not folders:
        print("Error: No subdirectories found in target", file=sys.stderr)
        sys.exit(1)
    print(f"Found {len(folders)} folder(s)")

    # Collect source PDFs
    pdfs = collect_pdfs(args.source, args.recursive)
    if not pdfs:
        print(f"No PDF files found in {args.source}", file=sys.stderr)
        sys.exit(1)

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
        success, rate_limited = process_single_pdf(
            pdf, args.target, folders, config, args.dry_run, args.yes, i + 1, len(pdfs)
        )
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
