import json
import os
from datetime import datetime, date
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, IO

from prompt_toolkit.completion import Completer, WordCompleter, Completion

# Constants for app name and directories
APP_NAME = "heare"
DEFAULT_CONFIG_DIR = Path.home() / ".config" / APP_NAME
DEFAULT_DATA_DIR = Path.home() / ".local" / "share" / APP_NAME


def get_config_dir() -> Path:
    """Get the configuration directory for the application."""
    config_dir = os.environ.get("XDG_CONFIG_HOME", DEFAULT_CONFIG_DIR)
    return Path(config_dir)


def get_data_dir() -> Path:
    """Get the data directory for the application."""
    data_dir = os.environ.get("XDG_DATA_HOME", DEFAULT_DATA_DIR)
    return Path(data_dir)


def ensure_dir_exists(directory: Path) -> None:
    """Ensure that the given directory exists."""
    directory.mkdir(parents=True, exist_ok=True)


def get_config_file(filename: str) -> Path:
    """Get the path to a configuration file."""
    config_dir = get_config_dir()
    ensure_dir_exists(config_dir)
    return config_dir / filename


def get_data_file(filename: str) -> Path:
    """Get the path to a data file."""
    data_dir = get_data_dir()
    ensure_dir_exists(data_dir)
    return data_dir / filename


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Enum):
            return obj.name
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, SimpleNamespace):
            return vars(obj)
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        if hasattr(obj, "__slots__"):
            return {
                slot: getattr(obj, slot) for slot in obj.__slots__ if hasattr(obj, slot)
            }
        return super().default(obj)


def serialize_to_file(obj: Any, fp: IO[str], indent: int = None) -> None:
    json.dump(obj, fp, cls=CustomJSONEncoder, indent=indent)


def load_config(filename: str = "config.json") -> dict:
    """
    Load a configuration file from the config directory
    """
    config_file = get_config_file(filename)
    if config_file.exists():
        with open(config_file, "r") as f:
            return json.load(f)
    return {}


def save_config(config: dict, filename: str = "config.json") -> None:
    """
    Save a configuration file to the config directory
    """
    config_file = get_config_file(filename)
    with open(config_file, "w") as f:
        serialize_to_file(config, f, indent=2)


class CustomCompleter(Completer):
    def __init__(self, commands, history):
        self.commands = commands
        self.history = history
        self.word_completer = WordCompleter(
            list(commands.keys()), ignore_case=True, sentence=True, meta_dict=commands
        )

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor.lstrip()
        if text.startswith("/"):
            yield from self.word_completer.get_completions(document, complete_event)
        else:
            for history_item in reversed(self.history.get_strings()):
                if history_item.startswith(text):
                    yield Completion(history_item, start_position=-len(text))


def get_current_project_name() -> str:
    """
    Get the current project name.

    If in a git repository, uses the basename of the git repo
    (e.g., 'foo' from 'github.com:clusterfudge/foo.git').
    Otherwise, uses the basename of the current working directory.

    Returns:
        str: Name of the current project
    """
    import subprocess
    import os

    try:
        # Check if we're in a git repository
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode == 0 and result.stdout.strip():
            # Extract the basename from the git remote URL
            git_url = result.stdout.strip()

            # Handle different URL formats
            if git_url.endswith(".git"):
                git_url = git_url[:-4]  # Remove .git suffix

            # Extract the repo name (last part of the path)
            if "/" in git_url:
                repo_name = git_url.split("/")[-1]
            elif ":" in git_url:
                # Handle SSH-style URLs (e.g., github.com:user/repo)
                repo_name = git_url.split(":")[-1].split("/")[-1]
            else:
                repo_name = git_url

            return repo_name
    except (subprocess.SubprocessError, FileNotFoundError):
        # Git command failed or git is not installed
        pass

    # Fallback to current directory name
    return os.path.basename(os.getcwd())


def wrap_text_as_content_block(text: str) -> dict[str, Any]:
    return {
        "type": "text",
        "text": text,
    }


def render_tree(
    lines: list[str],
    node: dict[str, Any],
    prefix: str = "",
    is_last=True,
    is_root=False,
):
    if not node:
        return

    # Skip rendering the root object name itself
    if not is_root:
        # Characters for tree structure
        branch = "└── " if is_last else "├── "

        # Get node name and add to lines
        if isinstance(node, dict):
            node_names = list(node.keys())
            if node_names:
                node_name = node_names[0]
                lines.append(f"{prefix}{branch}{node_name}")

                # Process children
                new_prefix = prefix + ("    " if is_last else "│   ")
                child_dict = node.get(node_name, {})
                child_keys = list(child_dict.keys())

                for i, key in enumerate(child_keys):
                    is_last_child = i == len(child_keys) - 1
                    child_node = (
                        {key: child_dict[key]}
                        if isinstance(child_dict[key], dict)
                        else {}
                    )
                    render_tree(lines, child_node, new_prefix, is_last_child)
        else:
            # Handle leaf nodes or special messages
            lines.append(f"{prefix}{branch}{node}")
    else:
        # Root level processing
        root_keys = list(node.keys())
        for i, key in enumerate(root_keys):
            is_last_child = i == len(root_keys) - 1
            child_node = {key: node[key]} if isinstance(node[key], dict) else {}
            render_tree(lines, child_node, prefix, is_last_child)
