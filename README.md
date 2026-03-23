# scanflow

Modular PDF processing toolkit for scanned documents. Watches directories for incoming PDFs, applies OCR, handles duplex scanning (odd/even page interleaving), and optionally renames or sorts files based on AI content analysis.

## Features

- **OCR** via `ocrmypdf` - deskew, image correction, rotation, eng+deu languages
- **OCR on demand** - bulk-add text layers to existing PDF archives
- **Duplex scanning** - reverses even pages and interleaves with odd pages into a single document
- **AI rename** - generates descriptive filenames (e.g. `20260301-DrHaderRechnung.pdf`) using Claude, OpenAI, or Ollama
- **AI sort** - suggests and moves PDFs into matching directories in a folder tree
- **Multi-provider** - supports Claude, OpenAI, and Ollama (local); multiple Ollama instances with smart load balancing
- **Directory watcher** - monitors directories via `inotifywait`, processes files automatically as they arrive
- **Multi-user** - supports multiple independent directory sets in a single config

## Requirements

- Python 3.10+
- `ocrmypdf`, `pdftk`, `inotify-tools`, `tesseract-ocr-deu`
```bash
apt install ocrmypdf pdftk inotify-tools tesseract-ocr-deu python3-requests python3-fitz
pip3 install simple-term-menu
```

## Project Structure

```
scanflow/
├── scanflow              # Entry point: subcommand dispatcher
├── cli/
│   ├── watch.py          # Subcommand: directory watcher daemon
│   ├── ocr.py            # Subcommand: batch OCR for PDFs without text layer
│   ├── rename.py         # Subcommand: AI-powered PDF renaming
│   └── sort.py           # Subcommand: AI-powered PDF sorting into folders
├── modules/
│   ├── api.py            # AI API client (Claude / OpenAI / Ollama)
│   ├── ocr.py            # OCR via ocrmypdf
│   ├── text.py           # Shared text extraction with OCR-on-demand fallback
│   ├── multipage.py      # Duplex page interleaving via pdftk
│   ├── rename.py         # AI rename logic
│   └── sort.py           # AI folder sorting logic
├── config.py             # Shared configuration loading
├── scanflow.conf.example
└── requirements.txt
```

## Configuration

Copy the example config and edit it:

```bash
cp scanflow.conf.example /etc/scanflow.conf
```

```ini
[general]
# provider: claude, openai, or ollama
provider = claude
# model = claude-sonnet-4-20250514

[claude]
api_key = sk-ant-...

[openai]
api_key = sk-...

# Ollama: multiple instances supported, tried by priority (lowest first)
# Idle servers are preferred over busy ones automatically
[ollama:server1]
url = http://192.168.1.100:11434
model = gemma3:27b
priority = 10

[ollama:server2]
url = http://192.168.1.101:11434
model = qwen3:14b
priority = 20

[sort]
# Default source and target directories for 'scanflow sort'
# source = /scans/output
# target = /documents

[watch:user1]
single_dir = /scans/user1/single
multi_dir = /scans/user1/multi
output_dir = /scans/user1/output
```

Config file is searched in order:
1. `/etc/scanflow.conf`
2. `~/.config/scanflow/scanflow.conf`
3. `./scanflow.conf`

API keys can also be set via environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`), which take precedence over the config file.

## Usage

All functionality is accessible through a single entry point with subcommands:

```
scanflow watch    - directory watcher daemon
scanflow ocr      - batch OCR for PDFs without text layer
scanflow rename   - AI-powered PDF renaming
scanflow sort     - AI-powered PDF sorting into folders
```

### watch

Monitors directories and processes incoming PDFs automatically (OCR + optional AI rename):

```bash
scanflow watch
scanflow watch --config /path/to/scanflow.conf
scanflow watch --no-rename
```

### ocr

Add OCR text layers to PDFs that don't have one. Useful for bulk-processing existing document archives:

```bash
# Show which files need OCR
scanflow ocr /path/to/documents -r --dry-run

# Process all PDFs without text layer
scanflow ocr /path/to/documents -r

# Re-OCR everything (e.g. after ocrmypdf update)
scanflow ocr /path/to/documents -r --force
```

Options:
- `-r, --recursive` - process subdirectories
- `--dry-run` - only show which files need OCR
- `--force` - re-run OCR even on files that already have a text layer

### rename

Rename PDFs based on AI content analysis. Automatically runs OCR if no text layer is found:

```bash
# Single file, interactive
scanflow rename document.pdf

# Directory, automatic
scanflow rename -y /path/to/pdfs/

# Recursive, dry run
scanflow rename -r --dry-run /path/to/pdfs/

# Re-process already renamed files
scanflow rename --force /path/to/pdfs/

# Only write keywords to PDF metadata
scanflow rename --tag-only /path/to/pdfs/
```

Options:
- `-y, --yes` - skip confirmation, rename automatically
- `-r, --recursive` - process subdirectories
- `--dry-run` - show suggested names without renaming
- `--force` - re-process files that were already renamed
- `--tag-only` - only write AI keywords to PDF metadata, do not rename
- `--config` - path to config file

### sort

Sort PDFs into a target directory tree based on AI content analysis. Automatically runs OCR if no text layer is found:

```bash
# Interactive sorting
scanflow sort /inbox/ /archive/

# Automatic mode
scanflow sort -y /inbox/ /archive/

# Dry run
scanflow sort --dry-run /inbox/ /archive/

# Recursive source
scanflow sort -r /inbox/ /archive/
```

Options:
- `-y, --yes` - skip confirmation, move automatically
- `-r, --recursive` - search source subdirectories recursively
- `--dry-run` - only show suggestions, do not move files
- `--config` - path to config file

## How It Works

### Watcher workflow

**Single-page:**
1. PDF arrives in `single_dir`
2. OCR is applied, output saved as `YYYYMMDD-HHMMSS.pdf` in `output_dir`
3. If AI rename is enabled, the file is renamed based on its content

**Duplex:**
1. Two PDFs arrive in `multi_dir` (odd pages first, then even pages in reverse order)
2. Even pages are reversed, then interleaved with odd pages
3. OCR is applied to the combined document
4. If AI rename is enabled, the file is renamed based on its content

### OCR on demand

The `rename` and `sort` commands automatically detect PDFs without a text layer and run OCR before processing. This means they work with any PDF - not just those that came through the watcher pipeline.

### AI rename

- Extracts text from the OCR layer using pymupdf
- Sends text to Claude, OpenAI, or Ollama with a prompt requesting a `YYYYMMDD-Description` filename
- Falls back to the original timestamp if no document date is found
- Skips files where no meaningful name can be determined
- Writes AI-generated keywords to PDF metadata
- Handles API rate limits with exponential backoff

### AI sort

- Extracts text and metadata keywords from the PDF
- For large folder trees (>200 folders), uses a two-step approach: keyword pre-filter or AI-based parent category selection, then exact folder matching
- Interactive mode with hierarchical folder browser, refinement, and subfolder creation
- Handles API rate limits with exponential backoff

## systemd Service

Create a service file at `/etc/systemd/system/scanflow.service`:

```ini
[Unit]
Description=scanflow PDF processing pipeline
After=network.target

[Service]
ExecStart=/opt/scanflow/scanflow watch --config /etc/scanflow.conf
WorkingDirectory=/opt/scanflow
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
systemctl daemon-reload
systemctl enable --now scanflow
```

## License

MIT
