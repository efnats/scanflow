"""Shared AI API client for Claude and OpenAI."""

import os
import sys
import time

import requests


DEFAULT_MODELS = {
    "claude": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
}

ENV_KEYS = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}

MAX_RETRIES = 5


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


def ask_ai(prompt, config):
    """Send a prompt to the configured AI provider and return the response text."""
    provider = config.get("general", "provider")
    if provider == "claude":
        return _call_claude(prompt, config)
    elif provider == "openai":
        return _call_openai(prompt, config)
    else:
        raise ValueError(f"Unknown provider '{provider}'")


def _call_claude(prompt, config):
    """Send prompt to Claude API."""
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
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": prompt}
            ],
        },
        timeout=30,
    )
    data = resp.json()
    return data["content"][0]["text"].strip()


def _call_openai(prompt, config):
    """Send prompt to OpenAI API."""
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
            "max_tokens": 1024,
            "messages": [
                {"role": "user", "content": prompt}
            ],
        },
        timeout=30,
    )
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()
