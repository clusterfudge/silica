# Toolbox Custom Tools

## Overview

The `Toolbox` class now supports three ways to specify which tools are available to the agent:

1. **Default**: Use all tools from `ALL_TOOLS`
2. **Filter by name**: Provide a list of tool names to filter from `ALL_TOOLS`
3. **Provide concrete tools**: Pass in a list of actual tool functions directly

## Usage Examples

### 1. Default: All Tools

```python
from silica.developer.toolbox import Toolbox

# Uses all tools from ALL_TOOLS
toolbox = Toolbox(context)
```

### 2. Filter by Name

```python
# Use only specific tools by name
toolbox = Toolbox(
    context, 
    tool_names=["read_file", "write_file", "list_directory"]
)
```

This is useful when:
- You want a subset of the standard tools
- You're creating a sub-agent with limited capabilities
- You want to reference tools by name dynamically

### 3. Provide Concrete Tools

```python
from silica.developer.tools import read_file, write_file

# Pass tool functions directly
toolbox = Toolbox(
    context,
    tools=[read_file, write_file, my_custom_tool]
)
```

This is useful when:
- You have custom tools not in `ALL_TOOLS`
- You want to use tools from different sources
- You want complete control over the tool list
- You're creating specialized toolboxes for specific tasks

## Custom Tool Example

```python
from silica.developer.tools.framework import tool
from silica.developer.context import AgentContext
from silica.developer.toolbox import Toolbox

# Define a custom tool
@tool
def my_custom_tool(context: AgentContext, input: str) -> str:
    """
    A custom tool that does something specific.
    
    Args:
        input: Some input string
        
    Returns:
        Processed result
    """
    return f"Custom processing: {input}"

# Create toolbox with mix of standard and custom tools
toolbox = Toolbox(
    context,
    tools=[
        read_file,      # Standard tool
        write_file,     # Standard tool
        my_custom_tool, # Custom tool
    ]
)
```

## Precedence Rules

When multiple parameters are provided:

1. **`tools` parameter takes precedence** - If provided, `tool_names` is ignored
2. **`tool_names` parameter is used** - If no `tools` provided, filters `ALL_TOOLS`
3. **Default to `ALL_TOOLS`** - If neither parameter provided

```python
# tools takes precedence
toolbox = Toolbox(
    context,
    tool_names=["read_file"],  # Ignored
    tools=[write_file]          # This is used
)
# Result: Only write_file is available
```

## Use Cases

### Sub-Agent with Limited Tools

```python
# Sub-agent that can only read and search memory
memory_tools = [read_memory, search_memory, list_memory_files]
toolbox = Toolbox(context, tools=memory_tools)
```

### Testing with Mock Tools

```python
# Create test doubles for tools
mock_read = Mock(spec=read_file)
mock_write = Mock(spec=write_file)

toolbox = Toolbox(context, tools=[mock_read, mock_write])
```

### Domain-Specific Toolboxes

```python
# File operations only
file_toolbox = Toolbox(
    context,
    tools=[read_file, write_file, edit_file, list_directory]
)

# Memory operations only
memory_toolbox = Toolbox(
    context,
    tools=[read_memory, write_memory, split_memory, search_memory]
)

# Web operations only
web_toolbox = Toolbox(
    context,
    tools=[web_search, safe_curl]
)
```

### Specialized Split Agent

```python
from silica.developer.memory_v2.operations import create_split_toolbox

# Create specialized tools for splitting
split_tools = create_split_toolbox(storage)

# Create toolbox with only split-specific tools
toolbox = Toolbox(context, tools=split_tools)
```

## Backward Compatibility

Existing code continues to work without changes:

```python
# Old style - still works
toolbox = Toolbox(context)
toolbox = Toolbox(context, tool_names=["read_file", "write_file"])

# New style - added flexibility
toolbox = Toolbox(context, tools=[read_file, write_file, custom_tool])
```

## Implementation Details

### Signature

```python
class Toolbox:
    def __init__(
        self,
        context: AgentContext,
        tool_names: List[str] | None = None,
        tools: List[Callable] | None = None,
    ):
```

### Tool Schema Generation

The `schemas()` method works with all three modes:

```python
schemas = toolbox.schemas()
# Returns schema for whatever tools are in toolbox.agent_tools
```

### CLI Tools

CLI tools (like `/help`, `/tips`, `/commit`) are always registered regardless of which agent tools are used:

```python
# Even with no agent tools, CLI tools are available
toolbox = Toolbox(context, tools=[])
assert "help" in toolbox.local
```

## Benefits

1. **Flexibility**: Choose the right tool specification method for your use case
2. **Custom Tools**: Easy to use tools not in `ALL_TOOLS`
3. **Testing**: Can pass mock tools for testing
4. **Specialization**: Create domain-specific toolboxes
5. **Backward Compatible**: Existing code works unchanged
6. **Type Safe**: All approaches maintain type safety

## Related

- `silica/developer/toolbox.py` - Toolbox implementation
- `silica/developer/tools/framework.py` - Tool decorator
- `docs/developer/memory_v2_spec.md` - Example of specialized toolbox usage
