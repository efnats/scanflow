"""Shared AI API client for Claude and OpenAI."""

import os
import sys
import time

import requests


DEFAULT_MODELS = {
    "claude": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "ollama": None,
}

ENV_KEYS = {
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "ollama": "OLLAMA_API_KEY",
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
    if provider == "ollama":
        return None
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
    elif provider == "ollama":
        return _call_ollama(prompt, config)
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


def _get_ollama_instances(config):
    """Collect and return Ollama instances sorted by priority (lowest first)."""
    instances = []
    for section in config.sections():
        if section.startswith("ollama:"):
            name = section.split(":", 1)[1]
            if not config.has_option(section, "model"):
                continue
            instances.append({
                "name": name,
                "url": config.get(section, "url", fallback="http://localhost:11434"),
                "model": config.get(section, "model"),
                "api_key": config.get(section, "api_key", fallback=None),
                "priority": config.getint(section, "priority", fallback=100),
            })
    # Legacy [ollama] section (backwards compatible)
    if config.has_section("ollama") and config.has_option("ollama", "model"):
        instances.append({
            "name": "default",
            "url": config.get("ollama", "url", fallback="http://localhost:11434"),
            "model": config.get("ollama", "model"),
            "api_key": config.get("ollama", "api_key", fallback=None),
            "priority": config.getint("ollama", "priority", fallback=100),
        })
    if not instances:
        raise ValueError("No Ollama instances configured. Add [ollama:name] sections with model = ...")
    instances.sort(key=lambda x: x["priority"])
    return instances


def _send_to_ollama(inst, prompt):
    """Send a prompt to a specific Ollama instance. Returns response text."""
    headers = {"Content-Type": "application/json"}
    if inst["api_key"]:
        headers["Authorization"] = f"Bearer {inst['api_key']}"
    resp = api_request_with_retry(
        requests.post,
        f"{inst['url'].rstrip('/')}/v1/chat/completions",
        headers=headers,
        json={
            "model": inst["model"],
            "messages": [
                {"role": "user", "content": prompt}
            ],
        },
        timeout=120,
    )
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _call_ollama(prompt, config):
    """Send prompt to Ollama API with smart server selection.

    Checks which servers are idle and picks the highest-priority idle one.
    Falls back to highest-priority reachable server if all are busy.
    """
    instances = _get_ollama_instances(config)

    # First pass: check all servers, find idle or reachable
    reachable = []
    for inst in instances:
        try:
            resp = requests.get(f"{inst['url'].rstrip('/')}/api/ps", timeout=2)
            if resp.status_code == 200:
                models = resp.json().get("models", [])
                if len(models) == 0:
                    print(f"  Using ollama '{inst['name']}' (idle)", file=sys.stderr)
                    return _send_to_ollama(inst, prompt)
                reachable.append(inst)
        except (requests.ConnectionError, requests.Timeout):
            pass

    # Fallback: all busy, queue on highest-priority reachable server
    if reachable:
        inst = reachable[0]
        print(f"  Using ollama '{inst['name']}' (all busy, queuing)", file=sys.stderr)
        return _send_to_ollama(inst, prompt)

    # All unreachable
    raise ConnectionError(
        f"All Ollama instances unreachable: "
        + ", ".join(f"{i['name']} ({i['url']})" for i in instances)
    )
