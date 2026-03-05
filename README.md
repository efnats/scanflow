# scanflow

Modular PDF processing pipeline for scanned documents. Watches directories for incoming PDFs, applies OCR, handles duplex scanning (odd/even page interleaving), and optionally renames files based on AI content analysis.

## Features

- **OCR** via `ocrmypdf` - deskew, image correction, rotation, eng+deu languages
- **Duplex scanning** - reverses even pages and interleaves with odd pages into a single document
- **AI rename** - extracts text from processed PDFs and generates descriptive filenames (e.g. `20260301-DrHaderRechnung.pdf`) using Claude or OpenAI
- **Directory watcher** - monitors directories via `inotifywait`, processes files automatically as they arrive
- **Multi-user** - supports multiple independent directory sets in a single config

## Requirements

- Python 3.10+
- `ocrmypdf`, `pdftk`, `inotify-tools`, `tesseract-ocr-deu`
- Python packages: `requests`, `pymupdf`

```bash
apt install ocrmypdf pdftk inotify-tools tesseract-ocr-deu python3-pip
pip install -r requirements.txt
```

## Project Structure

```
scanflow/
├── scanflow              # Main watcher service
├── scanrename.py         # Standalone CLI for AI rename
├── config.py             # Shared configuration loading
├── modules/
│   ├── ocr.py            # OCR via ocrmypdf
│   ├── multipage.py      # Duplex page interleaving via pdftk
│   └── rename.py         # AI-based rename logic
├── scanflow.conf.example # Example configuration
└── requirements.txt
```

## Configuration

Copy the example config and edit it:

```bash
cp scanflow.conf.example /etc/scanflow.conf
```

```ini
[general]
provider = claude
# model = claude-sonnet-4-20250514

[claude]
api_key = sk-ant-...

[openai]
api_key = sk-...

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

### Watcher (scanflow)

Monitors directories and processes incoming PDFs automatically:

```bash
./scanflow
./scanflow --config /path/to/scanflow.conf
./scanflow --no-rename    # disable AI rename
```

### Standalone Rename (scanrename.py)

Rename existing PDFs based on AI content analysis:

```bash
# Single file, interactive (confirms each rename)
./scanrename.py document.pdf

# Directory, automatic
./scanrename.py -y /path/to/pdfs/

# Recursive, dry run
./scanrename.py -r --dry-run /path/to/pdfs/

# Re-process already renamed files
./scanrename.py --force /path/to/pdfs/
```

Options:
- `-y, --yes` - skip confirmation, rename automatically
- `-r, --recursive` - process subdirectories
- `--dry-run` - show suggested names without renaming
- `--force` - re-process files that were already renamed
- `--config` - path to config file

## How It Works

### Single-page workflow
1. PDF arrives in `single_dir`
2. OCR is applied, output saved as `YYYYMMDD-HHMMSS.pdf` in `output_dir`
3. If AI rename is enabled, the file is renamed based on its content

### Duplex workflow
1. Two PDFs arrive in `multi_dir` (odd pages first, then even pages in reverse order)
2. Even pages are reversed, then interleaved with odd pages
3. OCR is applied to the combined document
4. If AI rename is enabled, the file is renamed based on its content

### AI Rename
- Extracts text from the OCR layer using pymupdf
- Sends text to Claude or OpenAI with a prompt requesting a `YYYYMMDD-Description` filename
- Falls back to the original timestamp if no document date is found
- Skips files where no meaningful name can be determined
- Handles API rate limits with exponential backoff

## systemd Service

Create a service file at `/etc/systemd/system/scanflow.service`:

```ini
[Unit]
Description=scanflow PDF processing pipeline
After=network.target

[Service]
ExecStart=/opt/scanflow/scanflow --config /etc/scanflow.conf
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
