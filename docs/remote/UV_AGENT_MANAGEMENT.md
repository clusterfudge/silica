# UV-Based Agent Management

This document explains how Silica manages agents using `uv` for consistent Python package management.

## Overview

Silica uses `uv` throughout the agent lifecycle to ensure consistent Python environment management. This approach eliminates the common issue of mismatched Python environments between installation and execution.

## Key Principles

### 1. Consistent UV Usage
- **Installation**: Use `uv add <package>` instead of `pip install <package>`
- **Execution**: Use `uv run <command>` for all agent launches
- **Environment**: Operate from the project root directory where `pyproject.toml` exists

### 2. Project Directory Structure
```
agent-workspace/
├── pyproject.toml          # UV project configuration
├── uv.lock                 # UV lock file (auto-generated)
├── .python-version         # Python version specification
└── code/                   # User code directory (available to agents)
```

### 3. Agent Runner Behavior
- Starts in the project root directory
- Uses `uv` for all package management operations
- Resolves executable paths from project root
- Changes to `./code` directory before launching agents
- Agents run with `CWD=./code` (where user project code is located)

## Agent Configuration

### YAML Configuration Format
```yaml
name: "agent-name"
description: "Agent description"
install:
  commands:
    - "uv add package-name"      # Primary installation method
  fallback_commands:
    - "pip install package-name" # Fallback for compatibility
  check_command: "agent-name --version"
launch:
  command: "uv run agent-name"
  default_args:
    - "--arg1"
    - "--arg2"
```

### Installation Process
1. Check if agent is already installed using `check_command`
2. If not installed, try `uv add <package>` first
3. If `uv add` fails, fall back to `pip install` for compatibility
4. Verify installation with `check_command`

### Launch Process
1. Load environment variables from piku ENV files
2. Run `uv sync` to ensure dependencies are up to date
3. Resolve executable paths from project root using `uv run which <executable>`
4. Change to `./code` directory (where user project code is located)
5. Launch agent using resolved executable path

## Benefits of This Approach

### 1. Environment Consistency
- Installation and execution use the same Python environment
- No mismatch between global pip and project-specific uv environment
- Automatic dependency resolution and lock file management

### 2. Isolation
- Each agent workspace has its own isolated environment
- No conflicts between different agent requirements
- Clean separation from system Python

### 3. Reproducibility
- `uv.lock` ensures exact dependency versions
- Consistent behavior across different machines
- Easy to reproduce and debug issues

### 4. Performance
- Fast dependency resolution and installation
- Cached packages for faster subsequent installations
- Minimal overhead for agent launches

## Troubleshooting

### Common Issues

#### "Package not found" when running agent
**Cause**: Agent was installed with `pip` but trying to run with `uv run`
**Solution**: Ensure agent YAML uses `uv add` as primary installation method

#### "Permission denied" or "Command not found" errors
**Cause**: Executable path resolution failed or agent is not properly installed
**Solution**: Check that agent is installed with `uv run <agent> --version` from project root

#### "uv: command not found"
**Cause**: UV is not installed or not in PATH
**Solution**: Install uv following instructions at https://docs.astral.sh/uv/

#### "Python executable does not support -I flag"
**Cause**: This was the original Raspberry Pi issue - system Python too old
**Solution**: This approach bypasses the issue entirely by using uv's managed Python

### Verification Commands

```bash
# Check UV is working
uv --version

# Check project state
uv tree

# Check installed packages
uv run pip list

# Test agent directly
uv run agent-name --version
```

## Migration from Pip-based Approach

### For Existing Workspaces
1. Remove packages installed with pip: `pip uninstall <package>`
2. Add packages with uv: `uv add <package>`
3. Test agent launch: `uv run <agent-command>`

### For Agent Developers
1. Update agent YAML configs to use `uv add` as primary installation
2. Keep `pip install` as fallback for compatibility
3. Ensure launch commands use `uv run`
4. Test on fresh workspace to verify full flow

## Example: hdev Agent

```yaml
name: "hdev"
description: "Heare Developer - autonomous coding agent"
install:
  commands:
    - "uv add heare-developer"        # Primary: use uv
  fallback_commands:
    - "pip install heare-developer"   # Fallback: for compatibility
  check_command: "hdev --version"
launch:
  command: "uv run hdev"              # Always use uv run
  default_args:
    - "--dwr"
    - "--persona"
    - "autonomous_engineer"
```

This approach ensures consistent, reliable agent management across all platforms, including Raspberry Pi systems that previously had Python compatibility issues.