import os
from silica.developer.context import AgentContext
from .framework import tool


@tool
def sandbox_debug(context: "AgentContext"):
    """Show sandbox configuration and debug information.

    This tool displays comprehensive information about the sandbox environment
    including paths, mode, permissions, and filesystem state to help debug
    sandbox-related issues in remote deployments.
    """
    sandbox = context.sandbox

    # Collect sandbox configuration
    config_info = {
        "Sandbox Root Directory": sandbox.root_directory,
        "Sandbox Mode": sandbox.mode.name,
        "Gitignore Patterns": len(sandbox.gitignore_spec.patterns)
        if sandbox.gitignore_spec
        else 0,
        "Permissions Cache": "Enabled"
        if sandbox.permissions_cache is not None
        else "Disabled",
    }

    # Get current working directory from different perspectives
    cwd_info = {
        "Python os.getcwd()": os.getcwd(),
        "Python os.path.abspath('.')": os.path.abspath("."),
        "Sandbox Root (absolute)": os.path.abspath(sandbox.root_directory),
        "Sandbox Root (real)": os.path.realpath(sandbox.root_directory),
    }

    # Check if sandbox root exists and is accessible
    access_info = {
        "Sandbox Root Exists": os.path.exists(sandbox.root_directory),
        "Sandbox Root Is Dir": os.path.isdir(sandbox.root_directory),
        "Sandbox Root Readable": os.access(sandbox.root_directory, os.R_OK),
        "Sandbox Root Writable": os.access(sandbox.root_directory, os.W_OK),
        "Sandbox Root Executable": os.access(sandbox.root_directory, os.X_OK),
    }

    # Try to list sandbox root directory
    try:
        sandbox_contents = os.listdir(sandbox.root_directory)
        sandbox_listing = sandbox_contents[:10]  # Show first 10 items
        if len(sandbox_contents) > 10:
            sandbox_listing.append(f"... and {len(sandbox_contents) - 10} more items")
    except Exception as e:
        sandbox_listing = [f"Error listing directory: {str(e)}"]

    # Environment variables that might affect paths
    env_vars = {
        "HOME": os.environ.get("HOME", "Not set"),
        "PWD": os.environ.get("PWD", "Not set"),
        "OLDPWD": os.environ.get("OLDPWD", "Not set"),
        "PATH": os.environ.get("PATH", "Not set")[:100] + "..."
        if len(os.environ.get("PATH", "")) > 100
        else os.environ.get("PATH", "Not set"),
    }

    # Check if current directory and sandbox root are the same
    path_comparison = {
        "CWD == Sandbox Root": os.getcwd() == sandbox.root_directory,
        "CWD (abs) == Sandbox Root (abs)": os.path.abspath(".")
        == os.path.abspath(sandbox.root_directory),
        "CWD (real) == Sandbox Root (real)": os.path.realpath(".")
        == os.path.realpath(sandbox.root_directory),
    }

    # Test sandbox path validation
    test_paths = [".", "/", sandbox.root_directory, os.getcwd()]
    path_validation = {}
    for path in test_paths:
        try:
            is_valid = sandbox._is_path_in_sandbox(path)
            path_validation[f"Path '{path}' in sandbox"] = is_valid
        except Exception as e:
            path_validation[f"Path '{path}' validation"] = f"Error: {str(e)}"

    # Format the output
    result_sections = [
        "=== SANDBOX CONFIGURATION ===",
        *[f"{k}: {v}" for k, v in config_info.items()],
        "",
        "=== DIRECTORY PATHS ===",
        *[f"{k}: {v}" for k, v in cwd_info.items()],
        "",
        "=== PATH COMPARISON ===",
        *[f"{k}: {v}" for k, v in path_comparison.items()],
        "",
        "=== ACCESS PERMISSIONS ===",
        *[f"{k}: {v}" for k, v in access_info.items()],
        "",
        "=== SANDBOX ROOT CONTENTS ===",
        *sandbox_listing,
        "",
        "=== PATH VALIDATION TESTS ===",
        *[f"{k}: {v}" for k, v in path_validation.items()],
        "",
        "=== ENVIRONMENT VARIABLES ===",
        *[f"{k}: {v}" for k, v in env_vars.items()],
    ]

    return "\n".join(result_sections)
