"""Subcommand: sort PDFs into matching directories based on AI analysis."""

import itertools
import os
import sys
import threading
import time

import requests

from cli.common import collect_pdfs, C_BOLD, C_DIM, C_GREEN, C_YELLOW, C_RESET
from config import load_config
from modules.sort import (scan_directory_tree, sort_pdf, suggest_folders,
                          suggest_parent_folders, suggest_new_subfolders,
                          move_pdf, resolve_target_path)

INITIAL_BATCH_DELAY = 2
SPINNER = itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"])


def _build_menu_entries(direct, parents):
    """Build menu entries: direct suggestions + separator + parent folders with '/' suffix.

    Returns (entries, entry_map) where entry_map maps index to (type, value).
    Type is 'direct', 'separator', or 'parent'.
    """
    entries = []
    entry_map = {}
    for f in direct:
        entry_map[len(entries)] = ("direct", f)
        entries.append(f)
    if direct and parents:
        entry_map[len(entries)] = ("separator", None)
        entries.append("──────────")
    for p in parents:
        entry_map[len(entries)] = ("parent", p)
        entries.append(p + "/")
    return entries, entry_map


def _get_parent_for_entry(value, prefix):
    """Determine the parent path for refine/create based on current entry and prefix."""
    if prefix:
        parts = value.split("/")
        depth = prefix.count("/")
        return "/".join(parts[:depth + 1]) if len(parts) > depth else value
    return value.split("/")[0]


def _refine_into(filename, parent, all_folders, config, text):
    """Refine into a parent folder. Returns (direct, parents, prefix) or None if leaf."""
    new_prefix = parent + "/"
    subtree = [f for f in all_folders if f.startswith(new_prefix) or f == parent]
    if not subtree or (len(subtree) == 1 and subtree[0] == parent):
        return None
    print(f"  {C_DIM}Refine: {new_prefix}...{C_RESET}")
    direct = suggest_folders(filename, subtree, config, text=text)
    parents = suggest_parent_folders(filename, all_folders, config, prefix=new_prefix, text=text)
    if not direct and not parents:
        return None
    return direct, parents, new_prefix


_QUIT = object()


def _create_subfolder(filename, parent, base_dir, all_folders, config, text):
    """Show AI-suggested new subfolder names under parent. Returns chosen full path, None (back), or _QUIT."""
    from simple_term_menu import TerminalMenu

    print(f"  {C_DIM}Generating subfolder suggestions for {parent}/...{C_RESET}")
    names = suggest_new_subfolders(filename, parent, all_folders, config, text=text)
    if not names:
        print(f"  {C_YELLOW}No suggestions{C_RESET}")
        return None

    entries = [f"{parent}/{n}" for n in names]
    menu = TerminalMenu(
        entries,
        cursor_index=0,
        menu_cursor="➜ ",
        menu_cursor_style=("fg_cyan", "bold"),
        menu_highlight_style=("fg_cyan", "bold"),
        clear_menu_on_exit=True,
        accept_keys=("enter", "b", "q"),
        status_bar="  [enter] create & select  [b]ack  [q]uit",
        status_bar_style=("fg_gray",),
    )
    idx = menu.show()
    key = menu.chosen_accept_key
    if key == "q":
        return _QUIT
    if key == "b" or idx is None:
        return None

    chosen = entries[idx]
    target_dir = os.path.join(base_dir, chosen)
    os.makedirs(target_dir, exist_ok=True)
    print(f"  {C_GREEN}+ Created {chosen}/{C_RESET}")
    return chosen


def confirm_move(filename, ranked, all_folders, base_dir, config, text=""):
    """Show hierarchical cursor-based folder selector with refine, create, and back.

    Returns chosen folder or None (skip).
    """
    from simple_term_menu import TerminalMenu

    # History stack: list of (prefix, direct, parents, parent_limit) for back navigation
    history = []
    prefix = ""
    direct = list(ranked)
    parent_limit = None  # use config default initially
    parents = suggest_parent_folders(filename, all_folders, config, prefix="", text=text)

    while True:
        entries, entry_map = _build_menu_entries(direct, parents)
        if not entries:
            return None

        if prefix:
            print(f"  {C_DIM}→  {prefix}{C_RESET}")

        keys = ["enter", "r", "c", "m", "s", "q"]
        bar = "  [enter] select  [r]efine  [c]reate  [m]ore  [s]kip  [q]uit"
        if history:
            keys.append("b")
            bar = "  [enter] select  [r]efine  [c]reate  [m]ore  [b]ack  [s]kip  [q]uit"

        menu = TerminalMenu(
            entries,
            cursor_index=0,
            menu_cursor="➜ ",
            menu_cursor_style=("fg_cyan", "bold"),
            menu_highlight_style=("fg_cyan", "bold"),
            clear_menu_on_exit=True,
            skip_empty_entries=True,
            accept_keys=tuple(keys),
            status_bar=bar,
            status_bar_style=("fg_gray",),
        )
        idx = menu.show()
        key = menu.chosen_accept_key

        if key == "q":
            print(f"  {C_YELLOW}Aborted.{C_RESET}")
            sys.exit(0)

        if key == "s" or idx is None:
            return None

        if key == "b" and history:
            prefix, direct, parents, parent_limit = history.pop()
            continue

        if idx not in entry_map:
            return None

        etype, value = entry_map[idx]

        if etype == "separator":
            continue

        if key == "m":
            from modules.sort import _get_sort_config
            _, default_max = _get_sort_config(config)
            current = parent_limit or default_max
            new_limit = current * 2
            new_parents = suggest_parent_folders(filename, all_folders, config,
                                                  prefix=prefix, text=text,
                                                  max_override=new_limit)
            if len(new_parents) <= len(parents):
                print(f"  {C_YELLOW}No more folders available{C_RESET}")
            else:
                parent_limit = new_limit
                parents = new_parents
            continue

        if key == "enter":
            if etype == "direct":
                return value
            if etype == "parent":
                result = _refine_into(filename, value, all_folders, config, text)
                if result is None:
                    if value in all_folders:
                        return value
                    print(f"  {C_YELLOW}No subfolders in {value}/{C_RESET}")
                    continue
                history.append((prefix, direct, parents, parent_limit))
                parent_limit = None
                direct, parents, prefix = result
                continue

        if key == "r":
            result = _refine_into(filename, value, all_folders, config, text)
            if result is None:
                if value in all_folders:
                    return value
                print(f"  {C_YELLOW}No subfolders in {value}/{C_RESET}")
                continue
            history.append((prefix, direct, parents, parent_limit))
            parent_limit = None
            direct, parents, prefix = result
            continue

        if key == "c":
            parent = value
            created = _create_subfolder(filename, parent, base_dir, all_folders, config, text)
            if created is _QUIT:
                print(f"  {C_YELLOW}Aborted.{C_RESET}")
                sys.exit(0)
            if created:
                all_folders.append(created)
                all_folders.sort()
                return created
            continue

    return None


def _move_to_failed(pdf_path):
    """Move a PDF to _failed/ next to its current location."""
    filename = os.path.basename(pdf_path)
    fail_dir = os.path.join(os.path.dirname(pdf_path), "_failed")
    os.makedirs(fail_dir, exist_ok=True)
    fail_path = resolve_target_path(fail_dir, filename)
    move_pdf(pdf_path, fail_path)
    print(f"  {C_YELLOW}Moved to _failed/{os.path.basename(fail_path)}{C_RESET}")


def _skip_pdf(pdf_path):
    """Move a PDF to _skipped/ next to its current location. Handles duplicates."""
    filename = os.path.basename(pdf_path)
    skip_dir = os.path.join(os.path.dirname(pdf_path), "_skipped")
    os.makedirs(skip_dir, exist_ok=True)
    skip_path = resolve_target_path(skip_dir, filename)
    move_pdf(pdf_path, skip_path)
    print(f"  {C_YELLOW}⏭ Skipped → _skipped/{os.path.basename(skip_path)}{C_RESET}")


def process_single_pdf(pdf_path, base_dir, folders, config, dry_run, auto_yes, index=0, total=0):
    """Sort a single PDF. Returns (success, rate_limited) tuple."""
    progress = f"[{index}/{total}]" if total else ""
    filename = os.path.basename(pdf_path)

    try:
        folder, target_path, alternatives, text = sort_pdf(pdf_path, base_dir, folders, config)
    except requests.exceptions.HTTPError as e:
        rate_limited = e.response is not None and e.response.status_code == 429
        print(f"\n{progress} {filename}\n  ERROR: {e}", file=sys.stderr)
        if not dry_run:
            _move_to_failed(pdf_path)
        return False, rate_limited
    except Exception as e:
        print(f"\n{progress} {filename}\n  ERROR: {e}", file=sys.stderr)
        if not dry_run:
            _move_to_failed(pdf_path)
        return False, False

    if folder is None:
        if dry_run:
            print(f"\n{progress} {filename}\n    No direct match")
            return True, False
        if auto_yes:
            print(f"\n{C_BOLD}{progress} {filename}{C_RESET}")
            _skip_pdf(pdf_path)
            return True, False
        print(f"\n{C_BOLD}{progress} {filename}{C_RESET}\n  {C_YELLOW}No direct match - browse folders:{C_RESET}")
        chosen = confirm_move(filename, [], folders, base_dir, config, text=text)
        if chosen is None:
            _skip_pdf(pdf_path)
            return True, False
        target_path = resolve_target_path(os.path.join(base_dir, chosen), filename)
        print(f"  {C_GREEN}✓ {chosen}/{os.path.basename(target_path)}{C_RESET}")
        move_pdf(pdf_path, target_path)
        return True, False

    ranked = [folder] + alternatives

    if dry_run:
        print(f"\n{progress} {filename}")
        for i, f in enumerate(ranked, 1):
            marker = " <-" if i == 1 else ""
            print(f"    {i}) {f}{marker}")
        return True, False

    if auto_yes:
        print(f"\n{C_BOLD}{progress} {filename}{C_RESET}\n  {C_GREEN}✓ {folder}/{os.path.basename(target_path)}{C_RESET}")
        move_pdf(pdf_path, target_path)
        return True, False

    print(f"\n{C_BOLD}{progress} {filename}{C_RESET}")
    chosen = confirm_move(filename, ranked, folders, base_dir, config, text=text)
    if chosen is None:
        _skip_pdf(pdf_path)
        return True, False

    if chosen != folder:
        folder = chosen
        target_path = resolve_target_path(os.path.join(base_dir, folder), filename)

    print(f"  {C_GREEN}✓ {folder}/{os.path.basename(target_path)}{C_RESET}")
    move_pdf(pdf_path, target_path)
    return True, False


def setup_parser(subparsers):
    """Register the 'sort' subcommand."""
    p = subparsers.add_parser("sort", help="Sort PDFs into directories based on AI analysis")
    p.add_argument("source", nargs="?", default=None,
                    help="PDF file or directory containing PDFs to sort (default: from config)")
    p.add_argument("target", nargs="?", default=None,
                    help="Target directory tree to sort into (default: from config)")
    p.add_argument("--config", default=None,
                    help="Path to config file")
    p.add_argument("--dry-run", action="store_true",
                    help="Only show suggestions, do not move files")
    p.add_argument("-r", "--recursive", action="store_true",
                    help="Search source subdirectories recursively")
    p.add_argument("-y", "--yes", action="store_true",
                    help="Skip confirmation prompt, move automatically")
    p.set_defaults(func=main)


def main(args):
    """Run the sort command."""
    config = load_config(args.config)

    # Fall back to config defaults if not given on command line
    if args.source is None:
        args.source = config.get("sort", "source", fallback=None)
    if args.target is None:
        args.target = config.get("sort", "target", fallback=None)

    if not args.source or not args.target:
        print("Error: source and target required. Provide as arguments or set in [sort] config.",
              file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.source):
        print(f"Error: Source not found: {args.source}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isdir(args.target):
        print(f"Error: Target directory not found: {args.target}", file=sys.stderr)
        sys.exit(1)

    if not config.has_option("general", "provider"):
        print("Error: Config must contain [general] provider", file=sys.stderr)
        sys.exit(1)

    # Clear screen and show header
    print("\033[2J\033[H", end="")
    print(f"{C_BOLD}scanflow sort{C_RESET} - AI-powered PDF sorting")
    print()

    # Scan target directory tree with spinner
    done = threading.Event()
    def spin(msg):
        while not done.is_set():
            print(f"\r  {next(SPINNER)} {msg}", end="", flush=True)
            done.wait(0.08)
        print(f"\r\033[2K", end="")

    done.clear()
    t = threading.Thread(target=spin, args=(f"Scanning {args.target}...",), daemon=True)
    t.start()
    folders = scan_directory_tree(args.target)
    done.set()
    t.join()
    if not folders:
        print("Error: No subdirectories found in target", file=sys.stderr)
        sys.exit(1)
    print(f"  Target: {args.target} ({len(folders)} folders)")

    # Collect source PDFs with spinner
    done.clear()
    t = threading.Thread(target=spin, args=("Collecting PDFs...",), daemon=True)
    t.start()
    pdfs = collect_pdfs(args.source, args.recursive, exclude_dirs={"_skipped"})
    done.set()
    t.join()
    if not pdfs:
        print(f"No PDF files found in {args.source}", file=sys.stderr)
        sys.exit(1)

    print(f"  Source: {len(pdfs)} PDF(s) in {args.source}")

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
            pdf, args.target, folders, config, args.dry_run, args.yes,
            index=i + 1, total=len(pdfs)
        )
        if not success:
            errors += 1
        if rate_limited:
            batch_delay = min(batch_delay * 2, 30)
            print(f"  Increasing delay to {batch_delay}s", file=sys.stderr)
    if errors:
        print(f"\n{errors} file(s) with errors.", file=sys.stderr)
        sys.exit(1)
