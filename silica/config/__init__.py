"""Configuration management for silica."""

import yaml
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "silica"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

DEFAULT_CONFIG = {
    "piku_connection": "piku",
    "workspace_name": "agent",
    "api_keys": {
        "ANTHROPIC_API_KEY": None,
        "GITHUB_TOKEN": None,
        "BRAVE_SEARCH_API_KEY": None,
    },
}


def ensure_config_dir():
    """Ensure the configuration directory exists."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config():
    """Load the configuration file."""
    ensure_config_dir()

    if not CONFIG_FILE.exists():
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    with open(CONFIG_FILE, "r") as f:
        config = yaml.safe_load(f)

    # Ensure all default keys exist
    for key, value in DEFAULT_CONFIG.items():
        if key not in config:
            config[key] = value

    return config


def save_config(config):
    """Save the configuration file."""
    ensure_config_dir()

    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config, f, default_flow_style=False)


def get_config_value(key, default=None):
    """Get a configuration value."""
    config = load_config()
    keys = key.split(".")

    # Navigate nested keys
    current = config
    for k in keys:
        if k in current:
            current = current[k]
        else:
            return default

    return current


def set_config_value(key, value):
    """Set a configuration value."""
    config = load_config()
    keys = key.split(".")

    # Navigate nested keys and set the value
    current = config
    for i, k in enumerate(keys[:-1]):
        if k not in current:
            current[k] = {}
        current = current[k]

    current[keys[-1]] = value
    save_config(config)
    return True


def find_git_root(path=None):
    """Find the root of the git repository."""
    from pathlib import Path
    import subprocess

    if path is None:
        path = Path.cwd()
    else:
        path = Path(path)

    try:
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], cwd=path, universal_newlines=True
        ).strip()
        return Path(git_root)
    except subprocess.CalledProcessError:
        return None


def get_silica_dir(path=None):
    """Get the .silica directory path."""
    git_root = find_git_root(path)
    if git_root:
        return git_root / ".silica"
    return None
