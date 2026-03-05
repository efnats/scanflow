"""AI-based PDF renaming: extract text, ask AI for a descriptive filename."""

import os
import re
import sys
import time

import fitz  # pymupdf
import requests


PROMPT = (
    "Analysiere den folgenden Text aus einem PDF-Dokument. "
    "Antworte NUR mit einem Dateinamen im Format YYYYMMDD-KurzBeschreibung "
    "(ohne .pdf). Das Datum soll das Dokumentdatum sein (nicht heute). "
    "Falls kein Datum erkennbar ist, verwende 00000000 als Datum. "
    "Falls der Inhalt nicht erkennbar oder unlesbar ist, antworte nur mit dem Datum "
    "(z.B. 00000000 oder das erkannte Datum). "
    "Die Beschreibung soll kurz und in CamelCase sein, z.B. "
    "20260301-DrHaderRechnung oder 20250115-FinanzamtBescheid. "
    "Antworte ausschliesslich mit dem Dateinamen, nichts anderes."
)

DEFAULT_MODELS = {
    "claude": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
}

ENV_KEYS = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

MAX_RETRIES = 5


def extract_text(pdf_path):
    """Extract the text layer from a PDF via pymupdf."""
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text()
    doc.close()
    if not text.strip():
        raise ValueError("No text found in PDF (OCR layer present?)")
    return text.strip()


def get_api_key(provider, config):
    """Get API key: environment variable first, then config file."""
    env_var = ENV_KEYS[provider]
    key = os.environ.get(env_var)
    if key:
        return key
    if config.has_option(provider, "api_key"):
        return config.get(provider, "api_key")
    raise ValueError(
        f"No API key found for '{provider}'. "
        f"Set {env_var} or add api_key to [{provider}] in the config file."
    )


def api_request_with_retry(method, url, **kwargs):
    """Send an HTTP request with retry on 429 rate limit errors."""
    for attempt in range(MAX_RETRIES):
        resp = method(url, **kwargs)
        if resp.status_code != 429:
            resp.raise_for_status()
            return resp
        retry_after = resp.headers.get("retry-after")
        if retry_after:
            wait = int(retry_after)
        else:
            wait = 2 ** (attempt + 1)
        print(f"  Rate limited, waiting {wait}s... (attempt {attempt + 1}/{MAX_RETRIES})",
              file=sys.stderr)
        time.sleep(wait)
    resp.raise_for_status()
    return resp


def call_claude(text, config):
    """Send text to the Claude API and return the suggested filename."""
    api_key = get_api_key("claude", config)
    model = DEFAULT_MODELS["claude"]
    if config.has_option("general", "model"):
        model = config.get("general", "model")

    resp = api_request_with_retry(
        requests.post,
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 100,
            "messages": [
                {"role": "user", "content": f"{PROMPT}\n\n---\n\n{text}"}
            ],
        },
        timeout=30,
    )
    data = resp.json()
    return data["content"][0]["text"].strip()


def call_openai(text, config):
    """Send text to the OpenAI API and return the suggested filename."""
    api_key = get_api_key("openai", config)
    model = DEFAULT_MODELS["openai"]
    if config.has_option("general", "model"):
        model = config.get("general", "model")

    resp = api_request_with_retry(
        requests.post,
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 100,
            "messages": [
                {"role": "user", "content": f"{PROMPT}\n\n---\n\n{text}"}
            ],
        },
        timeout=30,
    )
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def analyze_pdf(pdf_path, config):
    """Extract text from the PDF and ask the AI for a filename."""
    text = extract_text(pdf_path)
    provider = config.get("general", "provider")
    if provider == "claude":
        return call_claude(text, config)
    elif provider == "openai":
        return call_openai(text, config)
    else:
        raise ValueError(f"Unknown provider '{provider}'")


def sanitize_filename(name, original_path=None):
    """Validate and sanitize the AI-suggested filename."""
    name = name.strip().removesuffix(".pdf")
    name = re.sub(r"[^a-zA-Z0-9-]", "", name)
    if not re.match(r"^\d{8}(-[a-zA-Z0-9]+)?$", name):
        raise ValueError(f"AI returned invalid filename: '{name}'")
    # Replace placeholder date with date from original filename
    if name.startswith("00000000") and original_path:
        orig = os.path.splitext(os.path.basename(original_path))[0]
        m = re.match(r"^(\d{8})", orig)
        if m:
            name = m.group(1) + name[8:]
    # Skip if nothing meaningful was identified (same date, no description)
    if original_path:
        orig = os.path.splitext(os.path.basename(original_path))[0]
        orig_date = re.match(r"^(\d{8})", orig)
        if orig_date and name == orig_date.group(1):
            return None
    return name


def is_already_renamed(pdf_path):
    """Check if a file was already renamed (not a YYYYMMDD-HHMMSS timestamp name)."""
    basename = os.path.splitext(os.path.basename(pdf_path))[0]
    return not re.match(r"^\d{8}-\d{6}$", basename)


def resolve_target(directory, name):
    """Determine target path, appending a suffix for duplicates."""
    target = os.path.join(directory, f"{name}.pdf")
    if not os.path.exists(target):
        return target
    counter = 2
    while True:
        target = os.path.join(directory, f"{name}-{counter}.pdf")
        if not os.path.exists(target):
            return target
        counter += 1


def rename_pdf(pdf_path, config):
    """Analyze and rename a single PDF. Returns new path or None on failure."""
    try:
        suggested = analyze_pdf(pdf_path, config)
        name = sanitize_filename(suggested, pdf_path)
    except Exception as e:
        print(f"Rename error for {os.path.basename(pdf_path)}: {e}", file=sys.stderr)
        return None

    if name is None:
        return pdf_path

    directory = os.path.dirname(os.path.abspath(pdf_path))
    target = resolve_target(directory, name)
    os.rename(pdf_path, target)
    return target
