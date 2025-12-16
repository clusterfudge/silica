"""Toolbox tools for managing user-created tools.

These tools allow the agent to create, list, inspect, and shelve user tools
stored in ~/.silica/tools/.
"""

import json

from silica.developer.context import AgentContext

from .framework import tool
from .user_tools import (
    ensure_hello_world_tool,
    ensure_toolspec_helper,
    get_archive_dir,
    get_tools_dir,
    invoke_user_tool,
    list_tools,
    parse_tool_metadata,
    shelve_tool,
    validate_tool,
)


@tool(group="Toolbox")
def toolbox_list(context: AgentContext, category: str = None) -> str:
    """List all tools in the user toolbox.

    Lists tools stored in ~/.silica/tools/ with their descriptions and metadata.
    Use this to see what tools are available before using them.

    Args:
        category: Optional category filter (e.g., 'web', 'file', 'api')
    """
    # Ensure the hello world example exists on first access
    ensure_hello_world_tool()

    tools = list_tools(category=category)

    if not tools:
        if category:
            return f"No tools found in category '{category}'. Use toolbox_list without a category to see all tools."
        return "No user tools found. Use toolbox_create to create your first tool."

    output = []
    output.append(f"Found {len(tools)} user tool(s):\n")

    for t in tools:
        status = "OK" if not t.error else f"ERROR: {t.error}"
        desc = t.spec.get("description", "No description") if t.spec else "N/A"

        output.append(f"**{t.name}** [{status}]")
        output.append(f"  Description: {desc}")
        output.append(f"  Category: {t.metadata.category}")
        if t.metadata.tags:
            output.append(f"  Tags: {', '.join(t.metadata.tags)}")
        if t.metadata.long_running:
            output.append("  Note: Long-running tool, consider using shell sessions")
        output.append("")

    return "\n".join(output)


@tool(group="Toolbox")
def toolbox_create(
    context: AgentContext,
    name: str,
    code: str,
    test_input: str = None,
) -> str:
    """Create or edit a tool in the user toolbox.

    Creates a new tool or overwrites an existing one. The tool must be a valid
    Python script following the PEP 723 format with cyclopts for CLI handling.

    The tool will be validated (syntax check, --toolspec verification) before
    being saved. If test_input is provided, the tool will also be test-invoked.

    Args:
        name: Tool name (will become filename, e.g., 'my_tool' -> 'my_tool.py')
        code: Complete Python script content (must follow the user tool template)
        test_input: Optional JSON string with test arguments to validate the tool works
    """
    tools_dir = get_tools_dir()
    ensure_toolspec_helper()

    # Clean up name
    name = name.strip().replace(" ", "_").replace("-", "_")
    if name.endswith(".py"):
        name = name[:-3]

    # Reserved names
    if name.startswith("_"):
        return (
            "Error: Tool names cannot start with underscore (reserved for internal use)"
        )

    tool_path = tools_dir / f"{name}.py"
    is_update = tool_path.exists()

    # Write the tool file
    try:
        tool_path.write_text(code)
        tool_path.chmod(0o755)  # Make executable
    except Exception as e:
        return f"Error writing tool file: {e}"

    # Validate the tool
    validation = validate_tool(tool_path)

    output = []

    if not validation.valid:
        # Delete the invalid tool
        tool_path.unlink()
        output.append("Tool validation failed. The tool was not saved.\n")
        output.append("Errors:")
        for error in validation.errors:
            output.append(f"  - {error}")
        if validation.warnings:
            output.append("\nWarnings:")
            for warning in validation.warnings:
                output.append(f"  - {warning}")
        return "\n".join(output)

    # Show warnings if any
    if validation.warnings:
        output.append("Warnings:")
        for warning in validation.warnings:
            output.append(f"  - {warning}")

    action = "updated" if is_update else "created"
    output.append(f"Tool '{name}' {action} successfully at: {tool_path}")

    # Show the generated spec
    if validation.spec:
        output.append("\nTool specification:")
        output.append(f"  Name: {validation.spec.get('name')}")
        output.append(f"  Description: {validation.spec.get('description', 'N/A')}")
        params = validation.spec.get("input_schema", {}).get("properties", {})
        if params:
            output.append("  Parameters:")
            for param_name, param_info in params.items():
                required = param_name in validation.spec.get("input_schema", {}).get(
                    "required", []
                )
                req_str = " (required)" if required else ""
                output.append(
                    f"    - {param_name}: {param_info.get('type', 'string')}{req_str}"
                )

    # Test the tool if test_input provided
    if test_input:
        output.append("\nTesting tool with provided input...")
        try:
            test_args = json.loads(test_input)
            result = invoke_user_tool(name, test_args)

            if result.success:
                output.append("Test succeeded!")
                output.append(f"Output: {result.output.strip()}")
            else:
                output.append(f"Test failed (exit code {result.exit_code})")
                if result.output:
                    output.append(f"Stdout: {result.output.strip()}")
                if result.error:
                    output.append(f"Stderr: {result.error.strip()}")
        except json.JSONDecodeError as e:
            output.append(f"Test skipped: Invalid JSON in test_input: {e}")

    output.append(f"\nThe tool is now available for use. Call it as: {name}()")

    return "\n".join(output)


@tool(group="Toolbox")
def toolbox_inspect(context: AgentContext, name: str) -> str:
    """Inspect a tool - show its source code, specification, and metadata.

    Use this to understand how a tool works or to get its source for editing.

    Args:
        name: Tool name to inspect (without .py extension)
    """
    tools_dir = get_tools_dir()

    # Clean up name
    name = name.strip()
    if name.endswith(".py"):
        name = name[:-3]

    tool_path = tools_dir / f"{name}.py"

    if not tool_path.exists():
        # Check if it's in the archive
        archive_dir = get_archive_dir()
        archived = list(archive_dir.glob(f"{name}_*.py"))
        if archived:
            return (
                f"Tool '{name}' not found, but found archived versions:\n"
                + "\n".join(f"  - {p.name}" for p in archived)
            )
        return f"Tool '{name}' not found in {tools_dir}"

    output = []

    # Get source
    source = tool_path.read_text()

    # Parse metadata
    from .user_tools import _extract_module_docstring

    docstring = _extract_module_docstring(source)
    metadata = parse_tool_metadata(docstring)

    # Run validation to get spec
    validation = validate_tool(tool_path)

    output.append(f"# Tool: {name}\n")
    output.append(f"**Path:** {tool_path}")
    output.append(f"**Status:** {'Valid' if validation.valid else 'Invalid'}")

    if validation.errors:
        output.append("\n**Errors:**")
        for error in validation.errors:
            output.append(f"  - {error}")

    output.append("\n## Metadata")
    output.append(f"- Category: {metadata.category}")
    output.append(f"- Tags: {', '.join(metadata.tags) if metadata.tags else 'none'}")
    output.append(f"- Creator: {metadata.creator_persona or 'unknown'}")
    output.append(f"- Created: {metadata.created or 'unknown'}")
    output.append(f"- Long-running: {metadata.long_running}")
    output.append(f"- Requires auth: {metadata.requires_auth}")

    if validation.spec:
        output.append("\n## Tool Specification")
        output.append(f"```json\n{json.dumps(validation.spec, indent=2)}\n```")

    output.append("\n## Source Code")
    output.append(f"```python\n{source}\n```")

    return "\n".join(output)


@tool(group="Toolbox")
def toolbox_shelve(context: AgentContext, name: str) -> str:
    """Archive a tool (move to .archive directory with timestamp).

    Use this to remove a tool from the active toolbox without deleting it.
    Archived tools can be restored by moving them back from ~/.silica/tools/.archive/

    Args:
        name: Tool name to archive (without .py extension)
    """
    # Clean up name
    name = name.strip()
    if name.endswith(".py"):
        name = name[:-3]

    success, message = shelve_tool(name)

    if success:
        return f"Tool '{name}' has been archived.\n{message}\n\nTo restore, move the file back to ~/.silica/tools/{name}.py"
    else:
        return f"Failed to archive tool: {message}"


@tool(group="Toolbox")
def toolbox_test(
    context: AgentContext,
    name: str,
    args: str = "{}",
) -> str:
    """Test a user tool with sample input.

    Runs the tool with the provided arguments and returns the result.
    Use this to verify a tool works correctly before relying on it.

    Args:
        name: Tool name to test (without .py extension)
        args: JSON string with arguments to pass to the tool
    """
    # Clean up name
    name = name.strip()
    if name.endswith(".py"):
        name = name[:-3]

    # Parse arguments
    try:
        parsed_args = json.loads(args)
    except json.JSONDecodeError as e:
        return f'Invalid JSON in args: {e}\n\nExpected format: {{"param1": "value1", "param2": 123}}'

    if not isinstance(parsed_args, dict):
        return "args must be a JSON object (dictionary)"

    # Run the tool
    result = invoke_user_tool(name, parsed_args)

    output = []
    output.append(f"# Test Results: {name}\n")
    output.append(f"**Arguments:** {json.dumps(parsed_args)}")
    output.append(f"**Exit code:** {result.exit_code}")
    output.append(f"**Success:** {result.success}")

    if result.output:
        output.append("\n## Output")
        # Try to parse as JSON for better formatting
        try:
            parsed = json.loads(result.output)
            output.append(f"```json\n{json.dumps(parsed, indent=2)}\n```")
        except json.JSONDecodeError:
            output.append(f"```\n{result.output.strip()}\n```")

    if result.error:
        output.append("\n## Errors")
        output.append(f"```\n{result.error.strip()}\n```")

    return "\n".join(output)
