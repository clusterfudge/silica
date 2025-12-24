"""User tools module for discovering, validating, and executing user-created tools.

User tools are self-installing Python scripts stored in ~/.silica/tools/ that use
the PEP 723 inline script metadata format with uv for dependency management.
"""

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def get_tools_dir() -> Path:
    """Get the user tools directory, creating it if necessary."""
    tools_dir = Path.home() / ".silica" / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    return tools_dir


def get_archive_dir() -> Path:
    """Get the archive directory for shelved tools."""
    archive_dir = get_tools_dir() / ".archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    return archive_dir


def ensure_toolspec_helper() -> Path:
    """Ensure the toolspec helper module exists in the personal tools directory.

    This copies the generate_schema function to a standalone module that
    user tools can import without depending on the full silica package.
    """
    return ensure_toolspec_helper_in_dir(get_tools_dir())


def ensure_toolspec_helper_in_dir(tools_dir: Path) -> Path:
    """Ensure the toolspec helper module exists in the specified directory.

    This copies the generate_schema function to a standalone module that
    user tools can import without depending on the full silica package.

    Args:
        tools_dir: Directory where the helper should be created

    Returns:
        Path to the created helper module
    """
    tools_dir.mkdir(parents=True, exist_ok=True)
    helper_path = tools_dir / "_silica_toolspec.py"

    # Generate the helper module content
    helper_content = '''"""Silica toolspec helper - auto-generated, do not edit.

This module provides the generate_schema function for user tools to generate
their Anthropic API tool specifications.
"""

import inspect
from typing import get_origin, Union, get_args, Tuple, List


def generate_schema(
    func,
    name: str = None,
    skip_params: Tuple[str, ...] = ("toolspec", "authorize"),
) -> dict:
    """Generate Anthropic tool schema from a function signature and docstring.

    Args:
        func: The function to generate schema for
        name: Tool name (defaults to func.__name__)
        skip_params: Parameter names to exclude from schema

    Returns:
        A dictionary with 'name', 'description', and 'input_schema' keys.
    """
    tool_name = name or func.__name__

    # Parse the docstring to get description and param docs
    docstring = inspect.getdoc(func)
    if docstring:
        parts = docstring.split("\\n\\nArgs:")
        description = parts[0].strip()

        param_docs = {}
        if len(parts) > 1:
            param_section = parts[1].strip()
            for line in param_section.split("\\n"):
                line = line.strip()
                if line and ":" in line:
                    param_name, param_desc = line.split(":", 1)
                    param_docs[param_name.strip()] = param_desc.strip()
    else:
        description = ""
        param_docs = {}

    type_hints = inspect.get_annotations(func)

    schema = {
        "name": tool_name,
        "description": description,
        "input_schema": {"type": "object", "properties": {}, "required": []},
    }

    sig = inspect.signature(func)
    for param_name, param in sig.parameters.items():
        if param_name in skip_params:
            continue

        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue

        type_hint = type_hints.get(param_name)
        is_optional = False
        has_default = param.default != inspect.Parameter.empty

        if type_hint is not None:
            origin = get_origin(type_hint)
            if origin is Union:
                args = get_args(type_hint)
                is_optional = type(None) in args

        is_optional = is_optional or has_default

        if not is_optional:
            schema["input_schema"]["required"].append(param_name)

        param_desc = param_docs.get(param_name, "")
        param_type = "string"

        if param_name in type_hints:
            hint = type_hints[param_name]
            if get_origin(hint) is Union:
                args = get_args(hint)
                hint = next((arg for arg in args if arg is not type(None)), hint)

            if hint == bool or (isinstance(hint, type) and issubclass(hint, bool)):
                param_type = "boolean"
            elif hint in (int,) or (isinstance(hint, type) and issubclass(hint, int)):
                param_type = "integer"
            elif hint in (float,) or (isinstance(hint, type) and issubclass(hint, float)):
                param_type = "number"

        schema["input_schema"]["properties"][param_name] = {
            "type": param_type,
            "description": param_desc,
        }

    return schema


def generate_schemas_for_commands(
    commands: List[tuple],
    prefix: str = "",
) -> List[dict]:
    """Generate schemas for multiple command functions.

    Use this for multi-tool files where you have several commands.

    Args:
        commands: List of (function, name) tuples. If name is None, uses function name.
        prefix: Optional prefix for tool names (e.g., 'gmail_' for gmail tools)

    Returns:
        List of tool specification dictionaries.

    Example:
        commands = [
            (search, "gmail_search"),
            (read, "gmail_read"),
            (send, "gmail_send"),
        ]
        specs = generate_schemas_for_commands(commands)
    """
    schemas = []
    for func, name in commands:
        tool_name = name or func.__name__
        if prefix and not tool_name.startswith(prefix):
            tool_name = prefix + tool_name
        schemas.append(generate_schema(func, name=tool_name))
    return schemas
'''

    # Write the helper module
    helper_path.write_text(helper_content)
    return helper_path


def get_toolspec_helper_path() -> Path:
    """Get the path to the toolspec helper module in the personal tools dir."""
    return get_tools_dir() / "_silica_toolspec.py"


@dataclass
class ToolMetadata:
    """Metadata extracted from a tool's docstring."""

    category: str = "uncategorized"
    tags: list[str] = None
    creator_persona: str = None
    created: str = None
    long_running: bool = False
    requires_auth: bool = False

    def __post_init__(self):
        if self.tags is None:
            self.tags = []


def parse_tool_metadata(docstring: str) -> ToolMetadata:
    """Parse metadata from a tool's module docstring.

    Expected format in docstring:
        Metadata:
            category: web
            tags: api, weather
            creator_persona: hdev
            created: 2024-12-06
            long_running: false
            requires_auth: true
    """
    metadata = ToolMetadata()

    if not docstring:
        return metadata

    # Find the Metadata section
    metadata_match = re.search(
        r"Metadata:\s*\n((?:\s+\w+:.*\n?)*)", docstring, re.IGNORECASE
    )
    if not metadata_match:
        return metadata

    metadata_section = metadata_match.group(1)

    # Parse each metadata field
    for line in metadata_section.split("\n"):
        line = line.strip()
        if not line or ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if key == "category":
            metadata.category = value
        elif key == "tags":
            metadata.tags = [t.strip() for t in value.split(",")]
        elif key == "creator_persona":
            metadata.creator_persona = value
        elif key == "created":
            metadata.created = value
        elif key == "long_running":
            metadata.long_running = value.lower() in ("true", "yes", "1")
        elif key == "requires_auth":
            metadata.requires_auth = value.lower() in ("true", "yes", "1")

    return metadata


@dataclass
class DiscoveredTool:
    """A discovered user tool with its spec and metadata."""

    name: str
    path: Path
    spec: dict
    metadata: ToolMetadata
    file_stem: str = None  # The filename stem (for multi-tool files)
    error: str = None
    group: str = None  # The group name for permission management
    is_authorized: bool = (
        True  # Whether the tool is authorized (for tools requiring auth)
    )

    def __post_init__(self):
        if self.file_stem is None:
            self.file_stem = self.path.stem if self.path else self.name
        if self.group is None:
            self.group = self.file_stem


def discover_tools(check_auth: bool = False) -> list[DiscoveredTool]:
    """Discover all user tools from ~/.silica/tools/.

    Args:
        check_auth: Whether to verify authorization for tools with requires_auth=True.
                    If False, is_authorized is set to True for all tools.
                    If True, tools that fail auth check will have is_authorized=False.

    Returns a list of DiscoveredTool objects with their specs and metadata.
    A single file can contain multiple tools (--toolspec returns an array).
    Tools that fail to load are included with an error message.
    """
    # Ensure toolspec helper exists
    ensure_toolspec_helper()

    discovered = []
    tools_dir = get_tools_dir()

    for path in tools_dir.glob("*.py"):
        # Skip the helper module and hidden files
        if path.name.startswith("_") or path.name.startswith("."):
            continue

        file_tools = _discover_tools_from_file(path, check_auth=check_auth)
        discovered.extend(file_tools)

    return discovered


def check_tool_authorization(path: Path) -> tuple[bool, str]:
    """Check if a tool is authorized by calling --authorize.

    Args:
        path: Path to the tool file

    Returns:
        Tuple of (is_authorized, message)
    """
    try:
        result = subprocess.run(
            ["uv", "run", str(path), "--authorize"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(path.parent),
        )

        if result.returncode == 0:
            try:
                auth_result = json.loads(result.stdout)
                success = auth_result.get("success", False)
                message = auth_result.get("message", "")
                return success, message
            except json.JSONDecodeError:
                # If output isn't JSON, assume authorized if exit code was 0
                return True, "Authorized"
        else:
            return False, result.stderr.strip() or "Authorization check failed"
    except subprocess.TimeoutExpired:
        return False, "Authorization check timed out"
    except Exception as e:
        return False, f"Authorization check error: {e}"


def _discover_tools_from_file(
    path: Path, check_auth: bool = True
) -> list[DiscoveredTool]:
    """Discover tools from a single file.

    A file can contain one or more tools. --toolspec should return either:
    - A single tool spec object: {"name": ..., "description": ..., "input_schema": ...}
    - An array of tool specs: [{"name": ..., ...}, {"name": ..., ...}]

    Args:
        path: Path to the tool file
        check_auth: Whether to check authorization for tools with requires_auth=True
    """
    file_stem = path.stem

    try:
        # Run the tool with --toolspec to get its specification(s)
        result = subprocess.run(
            ["uv", "run", str(path), "--toolspec"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(path.parent),
        )

        if result.returncode != 0:
            return [
                DiscoveredTool(
                    name=file_stem,
                    path=path,
                    spec={},
                    metadata=ToolMetadata(),
                    file_stem=file_stem,
                    error=f"--toolspec failed: {result.stderr}",
                )
            ]

        # Parse the JSON spec(s)
        try:
            spec_data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            return [
                DiscoveredTool(
                    name=file_stem,
                    path=path,
                    spec={},
                    metadata=ToolMetadata(),
                    file_stem=file_stem,
                    error=f"Invalid JSON from --toolspec: {e}",
                )
            ]

        # Extract metadata from the file's docstring
        source = path.read_text()
        docstring = _extract_module_docstring(source)
        metadata = parse_tool_metadata(docstring)

        # Check authorization if tool requires it
        is_authorized = True
        auth_error = None
        if check_auth and metadata.requires_auth:
            is_authorized, auth_message = check_tool_authorization(path)
            if not is_authorized:
                auth_error = f"Not authorized: {auth_message}"

        # Handle both single spec and array of specs
        if isinstance(spec_data, list):
            # Multiple tools in one file
            tools = []
            for spec in spec_data:
                tool_name = spec.get("name", file_stem)
                tools.append(
                    DiscoveredTool(
                        name=tool_name,
                        path=path,
                        spec=spec,
                        metadata=metadata,
                        file_stem=file_stem,
                        is_authorized=is_authorized,
                        error=auth_error,
                    )
                )
            return tools
        else:
            # Single tool
            tool_name = spec_data.get("name", file_stem)
            return [
                DiscoveredTool(
                    name=tool_name,
                    path=path,
                    spec=spec_data,
                    metadata=metadata,
                    file_stem=file_stem,
                    is_authorized=is_authorized,
                    error=auth_error,
                )
            ]

    except subprocess.TimeoutExpired:
        return [
            DiscoveredTool(
                name=file_stem,
                path=path,
                spec={},
                metadata=ToolMetadata(),
                file_stem=file_stem,
                error="--toolspec timed out after 30 seconds",
            )
        ]
    except Exception as e:
        return [
            DiscoveredTool(
                name=file_stem,
                path=path,
                spec={},
                metadata=ToolMetadata(),
                file_stem=file_stem,
                error=f"Discovery error: {e}",
            )
        ]


def _extract_module_docstring(source: str) -> str:
    """Extract the module-level docstring from Python source code."""
    import ast

    try:
        tree = ast.parse(source)
        return ast.get_docstring(tree) or ""
    except SyntaxError:
        return ""


@dataclass
class ValidationResult:
    """Result of validating a tool."""

    valid: bool
    errors: list[str]
    warnings: list[str]
    spec: dict = None


def validate_tool(path: Path) -> ValidationResult:
    """Validate a user tool.

    Checks:
    1. Python syntax (via ruff if available, else ast.parse)
    2. --toolspec returns valid JSON
    3. Spec has required fields (name, description, input_schema)

    Returns a ValidationResult with any errors and warnings.
    """
    errors = []
    warnings = []
    spec = None

    # Check if file exists
    if not path.exists():
        return ValidationResult(
            valid=False, errors=["File does not exist"], warnings=[]
        )

    source = path.read_text()

    # 1. Syntax check with ruff (if available) or ast.parse
    try:
        result = subprocess.run(
            ["ruff", "check", str(path), "--select=E,F"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            # Parse ruff output for errors
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    errors.append(f"ruff: {line}")
    except FileNotFoundError:
        # ruff not available, fall back to ast.parse
        try:
            import ast

            ast.parse(source)
        except SyntaxError as e:
            errors.append(f"Syntax error: {e}")

    # 2. Check --toolspec works
    try:
        result = subprocess.run(
            ["uv", "run", str(path), "--toolspec"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(path.parent),
        )

        if result.returncode != 0:
            errors.append(f"--toolspec failed: {result.stderr.strip()}")
        else:
            try:
                spec = json.loads(result.stdout)

                # 3. Validate spec structure
                if "name" not in spec:
                    errors.append("Spec missing required field: name")
                if "description" not in spec:
                    warnings.append("Spec missing recommended field: description")
                if "input_schema" not in spec:
                    errors.append("Spec missing required field: input_schema")
                elif not isinstance(spec.get("input_schema"), dict):
                    errors.append("input_schema must be an object")

            except json.JSONDecodeError as e:
                errors.append(f"--toolspec returned invalid JSON: {e}")

    except subprocess.TimeoutExpired:
        errors.append("--toolspec timed out after 30 seconds")
    except Exception as e:
        errors.append(f"Error running --toolspec: {e}")

    return ValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        spec=spec,
    )


@dataclass
class ToolInvocationResult:
    """Result of invoking a user tool."""

    success: bool
    output: str
    error: str = None
    exit_code: int = 0


def find_tool(tool_name: str) -> Optional[DiscoveredTool]:
    """Find a tool by name.

    Args:
        tool_name: The tool name to find

    Returns:
        DiscoveredTool if found, None otherwise
    """
    tools = discover_tools()
    for tool in tools:
        if tool.name == tool_name:
            return tool
    return None


def invoke_user_tool(
    tool_name: str,
    args: dict[str, Any],
    timeout: int = 60,
) -> ToolInvocationResult:
    """Invoke a user tool with the given arguments.

    Supports both single-tool files and multi-tool files. For multi-tool files,
    the tool name is used as a subcommand (e.g., 'gmail_search' invokes
    'uv run gmail.py search --arg value').

    Args:
        tool_name: Name of the tool
        args: Dictionary of arguments to pass to the tool
        timeout: Maximum execution time in seconds

    Returns:
        ToolInvocationResult with output or error information.
    """
    # Find the tool
    tool = find_tool(tool_name)

    if tool is None:
        # Try legacy lookup by file name
        tools_dir = get_tools_dir()
        tool_path = tools_dir / f"{tool_name}.py"
        if tool_path.exists():
            # Single tool file with matching name
            return _invoke_tool_file(tool_path, None, args, timeout)

        return ToolInvocationResult(
            success=False,
            output="",
            error=f"Tool not found: {tool_name}",
            exit_code=1,
        )

    # Determine if we need a subcommand
    # If the tool name differs from the file stem, it's a multi-tool file
    subcommand = None
    if tool.name != tool.file_stem:
        # Extract subcommand: if tool is 'gmail_search' and file is 'gmail',
        # subcommand might be 'search' (strip prefix) or 'gmail_search' (full name)
        # We'll try the suffix first, then the full name
        if tool.name.startswith(tool.file_stem + "_"):
            subcommand = tool.name[len(tool.file_stem) + 1 :]
        else:
            subcommand = tool.name

    return _invoke_tool_file(tool.path, subcommand, args, timeout)


def _invoke_tool_file(
    tool_path: Path,
    subcommand: Optional[str],
    args: dict[str, Any],
    timeout: int,
) -> ToolInvocationResult:
    """Invoke a tool file with optional subcommand and arguments."""
    # Build command
    cmd = ["uv", "run", str(tool_path)]

    # Add subcommand if present (for multi-tool files)
    if subcommand:
        cmd.append(subcommand)

    # Add arguments as --key=value or --key value
    for key, value in args.items():
        if isinstance(value, bool):
            if value:
                cmd.append(f"--{key}")
        else:
            cmd.append(f"--{key}")
            cmd.append(str(value))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(tool_path.parent),
        )

        if result.returncode != 0:
            return ToolInvocationResult(
                success=False,
                output=result.stdout,
                error=result.stderr,
                exit_code=result.returncode,
            )

        return ToolInvocationResult(
            success=True,
            output=result.stdout,
            exit_code=0,
        )

    except subprocess.TimeoutExpired:
        return ToolInvocationResult(
            success=False,
            output="",
            error=f"Tool execution timed out after {timeout} seconds",
            exit_code=-1,
        )
    except Exception as e:
        return ToolInvocationResult(
            success=False,
            output="",
            error=f"Error executing tool: {e}",
            exit_code=-1,
        )


def shelve_tool(tool_name: str) -> tuple[bool, str]:
    """Move a tool to the archive directory.

    Args:
        tool_name: Name of the tool (without .py extension)

    Returns:
        Tuple of (success, message)
    """
    tools_dir = get_tools_dir()
    archive_dir = get_archive_dir()
    tool_path = tools_dir / f"{tool_name}.py"

    if not tool_path.exists():
        return False, f"Tool not found: {tool_name}"

    # Create archive filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"{tool_name}_{timestamp}.py"
    archive_path = archive_dir / archive_name

    try:
        tool_path.rename(archive_path)
        return True, f"Tool archived to: {archive_path}"
    except Exception as e:
        return False, f"Failed to archive tool: {e}"


def list_tools(category: str = None) -> list[DiscoveredTool]:
    """List all available tools, optionally filtered by category.

    Args:
        category: Optional category filter

    Returns:
        List of DiscoveredTool objects
    """
    tools = discover_tools()

    if category:
        tools = [t for t in tools if t.metadata.category == category]

    return tools


def get_hello_world_template() -> str:
    """Get the hello world template for new tools."""
    return '''#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts"]
# ///

"""A simple hello world example tool.

This tool demonstrates the structure of a user tool in Silica.
Use it as a template for creating your own tools.

Metadata:
    category: example
    tags: demo, template
    creator_persona: system
    created: {date}
    long_running: false
"""

import json
import sys
from pathlib import Path

import cyclopts

# Import the toolspec helper from the same directory
sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema

app = cyclopts.App()


@app.default
def main(
    name: str = "World",
    excited: bool = False,
    *,
    toolspec: bool = False,
    authorize: bool = False,
):
    """Say hello to someone.

    Args:
        name: Who to greet
        excited: Add exclamation marks for emphasis
    """
    if toolspec:
        print(json.dumps(generate_schema(main, "hello_world")))
        return

    if authorize:
        print(json.dumps({{"success": True, "message": "No authorization needed"}}))
        return

    punctuation = "!!!" if excited else "."
    greeting = f"Hello, {{name}}{{punctuation}}"
    print(json.dumps({{"success": True, "greeting": greeting}}))


if __name__ == "__main__":
    app()
'''.format(date=datetime.now().strftime("%Y-%m-%d"))


def ensure_hello_world_tool() -> Path:
    """Ensure the hello world example tool exists.

    Returns the path to the tool.
    """
    tools_dir = get_tools_dir()
    ensure_toolspec_helper()

    hello_path = tools_dir / "hello_world.py"

    if not hello_path.exists():
        hello_path.write_text(get_hello_world_template())
        # Make executable
        hello_path.chmod(0o755)

    return hello_path
