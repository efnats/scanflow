"""Shared configuration loading for scanflow."""

import configparser
import os
import shutil
import sys

DEFAULT_CONFIG_PATHS = [
    "/etc/scanflow.conf",
    os.path.expanduser("~/.config/scanflow/scanflow.conf"),
    "./scanflow.conf",
]

REQUIRED_TOOLS = {
    "inotifywait": "inotify-tools",
    "ocrmypdf": "ocrmypdf",
    "pdftk": "pdftk",
}


def find_config():
    """Search for the config file in default paths."""
    for path in DEFAULT_CONFIG_PATHS:
        if os.path.exists(path):
            return path
    return None


def load_config(config_path=None):
    """Load the configuration file."""
    if config_path is None:
        config_path = find_config()
        if config_path is None:
            print(
                "Error: No config file found. Searched in:\n  "
                + "\n  ".join(DEFAULT_CONFIG_PATHS),
                file=sys.stderr,
            )
            sys.exit(1)
    elif not os.path.exists(config_path):
        print(f"Error: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)
    config = configparser.ConfigParser()
    config.read(config_path)
    return config


def get_watch_sections(config):
    """Extract watch directory configurations from [watch:*] sections."""
    watches = []
    for section in config.sections():
        if section.startswith("watch:"):
            name = section.split(":", 1)[1]
            single_dir = config.get(section, "single_dir", fallback=None)
            multi_dir = config.get(section, "multi_dir", fallback=None)
            output_dir = config.get(section, "output_dir", fallback=None)
            if not all([single_dir, multi_dir, output_dir]):
                print(f"Warning: Incomplete watch config [{section}], skipping", file=sys.stderr)
                continue
            watches.append({
                "name": name,
                "single_dir": single_dir.rstrip("/"),
                "multi_dir": multi_dir.rstrip("/"),
                "output_dir": output_dir.rstrip("/"),
            })
    return watches


def check_dependencies():
    """Check that required external tools are installed."""
    missing = []
    for tool, package in REQUIRED_TOOLS.items():
        if not shutil.which(tool):
            missing.append(package)
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}", file=sys.stderr)
        print(f"Install with: apt install {' '.join(missing)}", file=sys.stderr)
        sys.exit(1)


def has_rename_config(config):
    """Check if AI rename is configured (provider + API key available)."""
    if not config.has_option("general", "provider"):
        return False
    provider = config.get("general", "provider")
    # Check env var
    from modules.rename import ENV_KEYS
    env_var = ENV_KEYS.get(provider)
    if env_var and os.environ.get(env_var):
        return True
    # Check config
    return config.has_option(provider, "api_key")
