"""Silica toolspec helper - shipped with default tools.

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
        parts = docstring.split("\n\nArgs:")
        description = parts[0].strip()

        param_docs = {}
        if len(parts) > 1:
            param_section = parts[1].strip()
            for line in param_section.split("\n"):
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

            if hint is bool or (isinstance(hint, type) and issubclass(hint, bool)):
                param_type = "boolean"
            elif hint in (int,) or (isinstance(hint, type) and issubclass(hint, int)):
                param_type = "integer"
            elif hint in (float,) or (
                isinstance(hint, type) and issubclass(hint, float)
            ):
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
