# Sandbox Debug Tool

## Overview

The `sandbox_debug` tool provides comprehensive debugging information about the sandbox environment configuration. This is particularly useful when troubleshooting sandbox-related issues in remote deployments where filesystem tools may behave unexpectedly.

## Problem It Solves

When deploying agents remotely (e.g., via Piku or other container environments), there can be mismatches between:
- The sandbox root directory that file tools (`read_file`, `write_file`, `list_directory`, `edit_file`) operate in
- The current working directory that shell tools (`shell_execute`) operate in

This can lead to confusing situations where shell commands can see project files, but file manipulation tools report empty directories or "file not found" errors.

## Usage

Simply invoke the tool without any parameters:

```
sandbox_debug
```

## Output Sections

The tool provides the following diagnostic information:

### Sandbox Configuration
- **Sandbox Root Directory**: The absolute path where file operations occur
- **Sandbox Mode**: Current permission mode (ALLOW_ALL, REMEMBER_PER_RESOURCE, etc.)
- **Gitignore Patterns**: Number of patterns loaded from .gitignore
- **Permissions Cache**: Whether permission caching is enabled

### Directory Paths
- **Python os.getcwd()**: Current working directory from Python's perspective
- **Python os.path.abspath('.')**: Absolute path of current directory
- **Sandbox Root (absolute)**: Absolute path of sandbox root
- **Sandbox Root (real)**: Real path (resolved symlinks) of sandbox root

### Path Comparison
- Compares whether current working directory matches sandbox root
- Tests both absolute and real paths for mismatches

### Access Permissions
- Tests if sandbox root directory exists and is accessible
- Checks read, write, and execute permissions

### Sandbox Root Contents
- Lists up to 10 files/directories in the sandbox root
- Shows if there are more items beyond the displayed list

### Path Validation Tests
- Tests how the sandbox validates various paths (current dir, root, sandbox root)
- Helps identify path resolution issues

### Environment Variables
- Shows relevant environment variables (HOME, PWD, OLDPWD, PATH)
- Useful for diagnosing environment-specific issues

## Common Issues and Diagnosis

### Issue: File tools can't find files that shell can see

**Symptoms**: `shell_execute("ls")` shows files, but `list_directory(".")` returns empty

**Diagnosis**: Check if "CWD == Sandbox Root" is False in the output

**Solution**: The sandbox and shell are operating in different directories. You may need to:
1. Use absolute paths when calling the agent
2. Ensure sandbox_contents parameter is set correctly
3. Check deployment configuration

### Issue: Permission denied errors in remote deployment

**Symptoms**: File operations fail with permission errors

**Diagnosis**: Check the "Access Permissions" section

**Solution**: 
1. Verify the user running the agent has proper file system permissions
2. Check if the sandbox directory is mounted correctly in containerized environments
3. Ensure no SELinux or similar security policies are blocking access

### Issue: Gitignore patterns not working

**Symptoms**: Files that should be ignored appear in listings

**Diagnosis**: Check "Gitignore Patterns" count - should be > 0 if .gitignore exists

**Solution**:
1. Verify .gitignore file exists in sandbox root
2. Check file permissions on .gitignore
3. Verify .gitignore syntax

## Integration with System Prompt

The system prompt now includes sandbox configuration information by default:

```
## Sandbox Environment Configuration

**Sandbox Root Directory:** `/path/to/sandbox`
**Current Working Directory:** `/path/to/cwd`  
**Sandbox Mode:** `ALLOW_ALL`

The sandbox filesystem tools operate within the sandbox root directory.
Shell commands operate in the current working directory.
Use the `sandbox_debug` tool to diagnose configuration issues.
```

This helps the agent understand the environment it's operating in and when to use the debug tool.

## Implementation Details

The tool is implemented in `silica/developer/tools/sandbox_debug.py` and automatically included in the agent's available tools. It requires no special permissions and can be run in any sandbox mode.

The tool is designed to be safe and non-invasive - it only reads configuration and performs basic file system checks without modifying anything.

## Testing

Comprehensive tests are available in `tests/developer/test_sandbox_debug.py` covering:
- Basic functionality
- Path validation 
- Error handling
- Different sandbox modes
- Environment variable reporting
- Gitignore pattern detection

## Remote Deployment Considerations

When using this tool in remote deployments:

1. **Container Environments**: May show different paths for sandbox vs working directory
2. **Piku Deployments**: Working directory might be in app-specific path while sandbox is elsewhere
3. **Docker/Podman**: Volume mounts may affect path resolution
4. **Symlinks**: Real vs absolute paths may differ significantly

The tool helps identify these environmental differences so appropriate fixes can be applied.