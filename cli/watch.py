"""Subcommand: watch directories for scanned PDFs and process them."""

import glob
import os
import subprocess
import sys
import threading
import time

from config import load_config, get_watch_sections, check_dependencies, has_rename_config
from modules.ocr import ocr_file
from modules.multipage import reverse_pdf, interleave_pdfs
from modules.rename import rename_pdf

MULTI_TIMEOUT = 300  # 5 minutes

# --- Logging helpers ---

def log(msg, name="scanflow"):
    """Print a timestamped log message."""
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{name}] {msg}", flush=True)


def log_err(msg, name="scanflow"):
    """Print a timestamped error message."""
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{name}] ERROR: {msg}", file=sys.stderr, flush=True)


def log_ok(msg, name="scanflow"):
    """Print a timestamped success message."""
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] [{name}] OK: {msg}", flush=True)


# --- Processing ---

def timestamp():
    """Generate a YYYYMMDD-HHMMSS timestamp."""
    return time.strftime("%Y%m%d-%H%M%S")


def process_single(incoming_file, output_dir, config, do_rename, watcher_name):
    """Process a single-page PDF: OCR, optional rename, cleanup."""
    ts = timestamp()
    output_file = os.path.join(output_dir, f"{ts}.pdf")
    basename = os.path.basename(incoming_file)

    log(f"Processing: {basename}", watcher_name)
    try:
        ocr_file(incoming_file, output_file)
    except Exception as e:
        log_err(f"OCR failed for {basename}: {e}", watcher_name)
        return

    os.remove(incoming_file)
    log_ok(f"OCR -> {os.path.basename(output_file)}", watcher_name)

    if do_rename:
        result = rename_pdf(output_file, config)
        if result and result != output_file:
            log_ok(f"Renamed -> {os.path.basename(result)}", watcher_name)


def process_multi(odd_file, even_file, output_dir, config, do_rename, watcher_name):
    """Process a pair of PDFs: reverse even pages, interleave, OCR, optional rename."""
    ts = timestamp()
    reversed_file = f"/tmp/scanflow_reversed_{ts}.pdf"
    combined_file = f"/tmp/scanflow_combined_{ts}.pdf"
    output_file = os.path.join(output_dir, f"{ts}.pdf")

    log(f"Processing pair: {os.path.basename(odd_file)} + {os.path.basename(even_file)}", watcher_name)
    try:
        reverse_pdf(even_file, reversed_file)
        interleave_pdfs(odd_file, reversed_file, combined_file)
    except Exception as e:
        log_err(f"Combine failed: {e}", watcher_name)
        if os.path.exists(reversed_file):
            os.remove(reversed_file)
        return

    os.remove(odd_file)
    os.remove(even_file)
    os.remove(reversed_file)

    log(f"Running OCR on combined file...", watcher_name)
    try:
        ocr_file(combined_file, output_file)
    except Exception as e:
        log_err(f"OCR failed. Combined file left at: {combined_file}", watcher_name)
        return

    os.remove(combined_file)
    log_ok(f"OCR -> {os.path.basename(output_file)}", watcher_name)

    if do_rename:
        result = rename_pdf(output_file, config)
        if result and result != output_file:
            log_ok(f"Renamed -> {os.path.basename(result)}", watcher_name)


# --- Watchers ---

def validate_dirs(watch, steps):
    """Check that all configured directories exist."""
    missing = []
    required = ["single_dir", "output_dir"]
    if "multipage" in steps:
        required.append("multi_dir")
    for key in required:
        d = watch[key]
        if not os.path.isdir(d):
            missing.append(f"{key}={d}")
    return missing


def watch_single(watch_dir, output_dir, config, do_rename, watcher_name):
    """Watch a directory for single-page PDFs using inotifywait."""
    log(f"Watching: {watch_dir}", watcher_name)
    proc = subprocess.Popen(
        ["inotifywait", "-m", "-e", "close_write", "--format", "%f", watch_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for line in proc.stdout:
        filename = line.strip()
        if not filename.lower().endswith(".pdf"):
            continue
        time.sleep(1)
        filepath = os.path.join(watch_dir, filename)
        if os.path.exists(filepath):
            process_single(filepath, output_dir, config, do_rename, watcher_name)
    stderr = proc.stderr.read()
    raise RuntimeError(f"inotifywait exited: {stderr.strip()}")


def try_process_multi(watch_dir, output_dir, config, do_rename, lock, watcher_name):
    """Try to pair and process PDFs from multi dir (thread-safe)."""
    with lock:
        pdfs = sorted(glob.glob(os.path.join(watch_dir, "*.pdf")), key=os.path.getmtime)
        if len(pdfs) >= 2 and os.path.exists(pdfs[0]) and os.path.exists(pdfs[1]):
            process_multi(pdfs[0], pdfs[1], output_dir, config, do_rename, watcher_name)


def watch_multi(watch_dir, output_dir, config, do_rename, lock, watcher_name):
    """Watch a directory for multi-page PDF pairs using inotifywait."""
    log(f"Watching: {watch_dir}", watcher_name)
    proc = subprocess.Popen(
        ["inotifywait", "-m", "-e", "close_write", "--format", "%f", watch_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    for line in proc.stdout:
        filename = line.strip()
        if not filename.lower().endswith(".pdf"):
            continue
        time.sleep(1)
        try_process_multi(watch_dir, output_dir, config, do_rename, lock, watcher_name)
    stderr = proc.stderr.read()
    raise RuntimeError(f"inotifywait exited: {stderr.strip()}")


def watch_orphans(watch_dir, timeout, watcher_name):
    """Periodically remove orphaned single PDFs in multi dir."""
    while True:
        time.sleep(60)
        pdfs = glob.glob(os.path.join(watch_dir, "*.pdf"))
        if len(pdfs) == 1 and os.path.exists(pdfs[0]):
            age = time.time() - os.path.getmtime(pdfs[0])
            if age >= timeout:
                log(f"Removing orphan ({int(age)}s old): {os.path.basename(pdfs[0])}", watcher_name)
                os.remove(pdfs[0])


# --- Startup ---

def start_watchers(watches, config, steps):
    """Start watcher threads for all configured directory sets."""
    do_rename = "rename" in steps
    do_multipage = "multipage" in steps
    threads = []
    for w in watches:
        name = w["name"]

        missing = validate_dirs(w, steps)
        if missing:
            log_err(f"[{name}] Directories not found: {', '.join(missing)}")
            log_err(f"[{name}] Skipping this watch set")
            continue

        log(f"[{name}] single={w['single_dir']}")
        if do_multipage:
            log(f"[{name}] multi={w['multi_dir']}")
        log(f"[{name}] output={w['output_dir']}")

        t1 = threading.Thread(
            target=watch_single,
            args=(w["single_dir"], w["output_dir"], config, do_rename, f"{name}/single"),
            name=f"{name}-single",
            daemon=True,
        )
        t1.start()
        threads.append(t1)

        if do_multipage:
            lock = threading.Lock()
            t2 = threading.Thread(
                target=watch_multi,
                args=(w["multi_dir"], w["output_dir"], config, do_rename, lock, f"{name}/multi"),
                name=f"{name}-multi",
                daemon=True,
            )
            t3 = threading.Thread(
                target=watch_orphans,
                args=(w["multi_dir"], MULTI_TIMEOUT, f"{name}/orphan"),
                name=f"{name}-orphans",
                daemon=True,
            )
            t2.start()
            t3.start()
            threads.extend([t2, t3])

    return threads


def cleanup_temp():
    """Remove temp files from previous runs."""
    for f in glob.glob("/tmp/scanflow_*.pdf"):
        os.remove(f)


def setup_parser(subparsers):
    """Register the 'watch' subcommand."""
    p = subparsers.add_parser("watch", help="Watch directories for scanned PDFs and process them")
    p.add_argument("--config", default=None,
                    help="Path to config file")
    p.add_argument("--rename", action="store_true",
                    help="Enable AI rename after OCR")
    p.add_argument("--no-multipage", action="store_true",
                    help="Disable duplex/multipage watcher")
    p.set_defaults(func=main)


def main(args):
    """Run the watch daemon."""
    print("scanflow watch starting...")
    print()

    steps = {"ocr"}
    if not args.no_multipage:
        steps.add("multipage")
    if args.rename:
        steps.add("rename")

    check_dependencies()
    config = load_config(args.config)

    if "rename" in steps and not has_rename_config(config):
        print("Error: --rename requires AI provider config (provider + API key)", file=sys.stderr)
        sys.exit(1)

    watches = get_watch_sections(config)
    if not watches:
        print("Error: No [watch:*] sections found in config", file=sys.stderr)
        sys.exit(1)

    log(f"Steps: {', '.join(sorted(steps))}")
    log(f"Directory sets: {len(watches)}")
    print()

    cleanup_temp()

    threads = start_watchers(watches, config, steps)

    if not threads:
        log_err("No watchers started (all directory sets had errors)")
        sys.exit(1)

    print()
    log("Ready. Waiting for files...")
    print()

    # Wait for any thread to die
    while True:
        for t in threads:
            if not t.is_alive():
                log_err(f"Watcher thread '{t.name}' died unexpectedly")
                sys.exit(1)
        time.sleep(5)
