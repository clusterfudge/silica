# Ripgrep Integration in Silica Developer Tools

## Overview

Silica's developer tools now prefer ripgrep (`rg`) over traditional `grep` for file searching operations. This provides significant performance improvements and better user experience while maintaining backwards compatibility.

## Benefits of Ripgrep

### Performance
- **Faster execution**: Ripgrep is significantly faster than grep, especially on large codebases
- **Parallelized**: Automatically uses multiple CPU cores for faster searching
- **Optimized**: Written in Rust with performance as a primary goal

### Better Defaults
- **Automatic gitignore**: Respects `.gitignore` files by default, skipping irrelevant files
- **Colored output**: Provides syntax highlighting for better readability  
- **Unicode support**: Better handling of non-ASCII text and files
- **Smart case**: Case-insensitive when all lowercase, case-sensitive with mixed case

### User Experience
- **Intuitive syntax**: More logical command-line options and file type filtering
- **Better error messages**: More helpful feedback when searches fail
- **Context lines**: Easy to add context around matches

## Installation

### macOS
```bash
brew install ripgrep
```

### Ubuntu/Debian  
```bash
sudo apt install ripgrep
```

### Windows
```bash
# Using chocolatey
choco install ripgrep

# Using winget
winget install BurntSushi.ripgrep.MSVC
```

### Other Platforms
See the [official ripgrep installation guide](https://github.com/BurntSushi/ripgrep#installation) for more options.

## Usage in Silica

### Memory Search System
The memory search functionality (`search_memory` tool) automatically detects and uses ripgrep when available:

```python
# This will use ripgrep if available, grep as fallback
search_memory(query="react component", prefix="projects")
```

### Command Equivalents

| Grep Command | Ripgrep Equivalent | Description |
|--------------|-------------------|-------------|
| `grep -r --include="*.py" "pattern" .` | `rg "pattern" --type py` | Search Python files |
| `grep -r -i "pattern" .` | `rg -i "pattern"` | Case-insensitive search |
| `grep -r -l "pattern" .` | `rg -l "pattern"` | List matching files only |
| `grep -r -n "pattern" .` | `rg -n "pattern"` | Show line numbers |
| `grep -r -A 2 -B 2 "pattern" .` | `rg -C 2 "pattern"` | Show context lines |

### Agent Recommendations
All agent personas now recommend using ripgrep over grep:

- **Coding Agent**: Includes specific guidance on using ripgrep for file searches
- **Basic Agent**: Recommends ripgrep for general file searching tasks  
- **Deep Research Agent**: Emphasizes ripgrep for scanning large document collections

## Implementation Details

### Detection
Silica uses `shutil.which("rg")` to detect ripgrep availability, with results cached for efficiency:
- **Cached on first use**: The expensive `shutil.which()` call happens only once per process
- **Process-scoped cache**: Results are cached for the lifetime of the agent process
- **Refresh capability**: Cache can be manually refreshed if ripgrep installation changes during runtime

### Fallback Behavior
- If ripgrep is available: Uses ripgrep commands with enhanced features
- If ripgrep is not available: Falls back to traditional grep commands
- No breaking changes: All existing functionality continues to work

### Memory System Integration
The memory search agent prompts have been updated to:
1. Detect ripgrep availability
2. Provide appropriate command examples for the available tool
3. Explain the benefits of the chosen tool
4. Format results consistently regardless of the search tool used

## Best Practices

### For Developers
1. **Install ripgrep** in development environments for better performance
2. **Use type filters**: `--type py`, `--type md`, etc. instead of glob patterns
3. **Leverage smart case**: Use lowercase for case-insensitive, mixed case for exact matching
4. **Add context**: Use `-C N` to see surrounding lines when debugging

### For Agent Development  
1. **Test both tools**: Ensure functionality works with both ripgrep and grep
2. **Use feature detection**: Check tool availability rather than assuming
3. **Provide helpful prompts**: Include appropriate command examples for each tool
4. **Maintain compatibility**: Support environments without ripgrep installed

## Future Enhancements

Potential improvements for ripgrep integration:
- Custom file type definitions for project-specific patterns
- Configuration file support for default options
- Integration with search indexing for even faster searches
- Enhanced context extraction for memory system results

## Troubleshooting

### Common Issues
1. **"rg: command not found"**: Ripgrep is not installed or not in PATH
2. **Slow performance**: May indicate ripgrep is not being used despite being available
3. **Missing results**: Check if `.gitignore` is excluding expected files

### Debugging
To verify ripgrep usage in the memory system:
```python
from silica.developer.tools.memory import _has_ripgrep, _refresh_ripgrep_cache
print(f"Ripgrep available: {_has_ripgrep()}")

# If ripgrep gets installed/uninstalled during runtime, refresh the cache:
_refresh_ripgrep_cache()
print(f"Ripgrep available (refreshed): {_has_ripgrep()}")
```

### Forcing Grep
If you need to force grep usage for testing:
```bash
# Temporarily rename ripgrep
sudo mv /usr/bin/rg /usr/bin/rg.bak
# Run your tests
# Restore ripgrep  
sudo mv /usr/bin/rg.bak /usr/bin/rg
```