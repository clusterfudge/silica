"""Workspace Environment commands for silica.

This module provides commands for managing the workspace environment on remote deployments.
These commands are designed to be run within the deployed silica environment to handle
agent setup, execution, and environment management.
"""

import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import cyclopts
from typing import Annotated
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Built-in silica developer agent

console = Console()


def check_python_version() -> bool:
    """Check if Python version meets requirements."""
    version = sys.version_info
    return version.major >= 3 and version.minor >= 11


def setup_python_environment() -> bool:
    """Set up Python 3.11 environment if needed."""
    setup_script = Path.cwd() / "setup_python.sh"

    if not setup_script.exists():
        console.print(
            f"[yellow]Python setup script not found at {setup_script}[/yellow]"
        )
        console.print("[yellow]Continuing with current Python version...[/yellow]")
        return True

    try:
        console.print("[dim]Running Python setup script...[/dim]")
        result = subprocess.run(
            ["bash", str(setup_script)],
            env=os.environ.copy(),
            timeout=1800,  # 30 minutes timeout for Python compilation
        )

        if result.returncode == 0:
            console.print("[green]✓ Python environment setup completed[/green]")
            return True
        else:
            console.print(
                f"[red]✗ Python setup failed with code {result.returncode}[/red]"
            )
            return False

    except subprocess.TimeoutExpired:
        console.print("[red]✗ Python setup timed out[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ Python setup error: {e}[/red]")
        return False


def load_environment_variables(silent=False):
    """Load environment variables from piku ENV and LIVE_ENV files."""
    top_dir = Path.cwd()
    app_name = top_dir.name

    # Load both ENV and LIVE_ENV files (LIVE_ENV takes precedence)
    env_files = [
        Path.home() / ".piku" / "envs" / app_name / "ENV",
        Path.home() / ".piku" / "envs" / app_name / "LIVE_ENV",
    ]

    env_vars_loaded = 0
    for env_file in env_files:
        if env_file.exists():
            if not silent:
                console.print(f"[dim]Loading environment from {env_file}[/dim]")
            with open(env_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        # Remove quotes if present
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        elif value.startswith("'") and value.endswith("'"):
                            value = value[1:-1]
                        os.environ[key] = value
                        env_vars_loaded += 1
        else:
            if not silent:
                console.print(f"[dim]Environment file not found: {env_file}[/dim]")

    if not silent:
        if env_vars_loaded > 0:
            console.print(
                f"[green]✓ Loaded {env_vars_loaded} environment variables[/green]"
            )
        else:
            console.print("[yellow]⚠ No environment variables loaded[/yellow]")

    return env_vars_loaded > 0


def sync_dependencies(clear_cache: bool = True):
    """Synchronize UV dependencies, optionally clearing cache first."""
    if clear_cache:
        console.print("[dim]Clearing UV cache to ensure latest versions...[/dim]")
        try:
            cache_result = subprocess.run(
                ["uv", "cache", "clean"],
                capture_output=True,
                text=True,
                timeout=60,
                env=os.environ.copy(),  # Pass current environment
            )
            if cache_result.returncode == 0:
                console.print("[green]✓ UV cache cleared successfully[/green]")
            else:
                # Cache clearing failure is not critical
                console.print(
                    f"[yellow]⚠ Cache clearing warning: {cache_result.stderr}[/yellow]"
                )
        except subprocess.TimeoutExpired:
            console.print("[yellow]⚠ Cache clearing timed out[/yellow]")
        except FileNotFoundError:
            console.print("[dim]UV cache clean not available (older UV version)[/dim]")
        except Exception as e:
            console.print(f"[yellow]⚠ Cache clearing error: {e}[/yellow]")

    console.print("[dim]Synchronizing dependencies with uv...[/dim]")
    try:
        # Use --upgrade flag to ensure latest versions are fetched
        result = subprocess.run(
            ["uv", "sync", "--upgrade"],
            capture_output=True,
            text=True,
            timeout=300,
            env=os.environ.copy(),  # Pass current environment
        )
        if result.returncode == 0:
            console.print("[green]✓ Dependencies synchronized successfully[/green]")
            return True
        else:
            console.print(f"[yellow]⚠ uv sync warning: {result.stderr}[/yellow]")
            return False
    except subprocess.TimeoutExpired:
        console.print("[red]✗ uv sync timed out[/red]")
        return False
    except FileNotFoundError:
        console.print("[red]✗ uv not found - please install uv[/red]")
        return False
    except Exception as e:
        console.print(f"[red]✗ uv sync error: {e}[/red]")
        return False


def is_agent_installed(agent_config: Dict[str, Any]) -> bool:
    """Check if agent is installed."""
    install_data = agent_config.get("install", {})
    check_command = install_data.get("check_command", "")

    if not check_command:
        return True

    # Try direct command first
    try:
        result = subprocess.run(
            check_command.split(),
            capture_output=True,
            text=True,
            timeout=10,
            env=os.environ.copy(),  # Pass current environment
        )
        if result.returncode == 0:
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Try with uv run
    try:
        uv_command = ["uv", "run"] + check_command.split()
        result = subprocess.run(
            uv_command,
            capture_output=True,
            text=True,
            timeout=10,
            env=os.environ.copy(),  # Pass current environment
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def verify_silica_available() -> bool:
    """Verify that silica developer is available (it comes built-in with silica).

    No installation needed - silica developer is part of silica itself.
    """
    try:
        # Simple check - if we can run silica --help, the developer command is available
        result = subprocess.run(
            ["silica", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            env=os.environ.copy(),
        )
        if result.returncode == 0:
            console.print("[green]✓ Silica developer is available[/green]")
            return True
        else:
            console.print("[yellow]⚠ Silica command not available[/yellow]")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        console.print("[red]✗ Silica not found[/red]")
        return False


def check_environment_variables(
    agent_config: Dict[str, Any], silent=False
) -> Tuple[bool, List[str], List[str]]:
    """Check and report environment variable status."""
    env_data = agent_config.get("environment", {})
    missing_required = []
    missing_recommended = []

    # Check required environment variables
    for env_var in env_data.get("required", []):
        env_name = env_var["name"]
        if not os.getenv(env_name):
            missing_required.append((env_name, env_var["description"]))

    # Check recommended environment variables
    for env_var in env_data.get("recommended", []):
        env_name = env_var["name"]
        if not os.getenv(env_name):
            missing_recommended.append((env_name, env_var["description"]))

    # Report status
    success = len(missing_required) == 0
    if not silent:
        if success and len(missing_recommended) == 0:
            console.print(
                f"[green]✓ All environment variables configured for {agent_config['name']}[/green]"
            )
        elif success:
            console.print(
                f"[yellow]⚠ Missing recommended environment variables for {agent_config['name']}[/yellow]"
            )
        else:
            console.print(
                f"[red]✗ Missing required environment variables for {agent_config['name']}[/red]"
            )

    return success, missing_required, missing_recommended


def get_workspace_config() -> Optional[Dict[str, Any]]:
    """Get workspace configuration from the current environment."""
    # In the deployed environment, we need to determine workspace config
    # This could come from environment variables set by piku, or from a config file

    # Simple workspace config - no agent type needed, only one agent
    workspace_config = {
        "agent_config": {"flags": [], "args": {}},
    }

    # Try to load more detailed config from a local file if it exists
    config_file = Path.cwd() / "workspace_config.json"
    if config_file.exists():
        try:
            with open(config_file, "r") as f:
                file_config = json.load(f)
                workspace_config.update(file_config)
                # No need to force agent_type - only one agent available
        except Exception as e:
            console.print(
                f"[yellow]Warning: Could not load workspace config: {e}[/yellow]"
            )

    return workspace_config


def setup_code_directory() -> bool:
    """Ensure code directory exists and is accessible."""
    code_dir = Path.cwd() / "code"

    if code_dir.exists() and code_dir.is_dir():
        console.print(f"[green]✓ Code directory found: {code_dir}[/green]")
        return True
    else:
        console.print(f"[yellow]⚠ Code directory not found: {code_dir}[/yellow]")
        console.print(
            "[yellow]Code directory should be set up by the sync process[/yellow]"
        )
        return False


def get_required_env_vars() -> List[Dict[str, str]]:
    """Get required environment variables for silica developer."""
    return [
        {
            "name": "ANTHROPIC_API_KEY",
            "description": "Anthropic API key for Claude access",
        },
        {
            "name": "BRAVE_SEARCH_API_KEY",
            "description": "Brave Search API key for web search functionality (optional)",
        },
        {
            "name": "GH_TOKEN",
            "description": "GitHub token for repository access",
        },
    ]


def get_silica_developer_command(workspace_config: Dict[str, Any]) -> str:
    """Get the command to run silica developer with default args."""
    command_parts = [
        "uv",
        "run",
        "silica",
        "developer",
        "--dwr",
        "--persona",
        "autonomous_engineer",
    ]

    # Add workspace-specific args if any
    agent_settings = workspace_config.get("agent_config", {})
    command_parts.extend(agent_settings.get("flags", []))

    for key, value in agent_settings.get("args", {}).items():
        if value is True:
            command_parts.append(f"--{key}")
        elif value is not False and value is not None:
            command_parts.extend([f"--{key}", str(value)])

    return " ".join(command_parts)


workspace_environment = cyclopts.App(
    name="workspace_environment",
    help="Manage workspace environment for deployed silica agents.",
)
workspace_environment_ = cyclopts.App(
    name="workspace-environment",
    help="Manage workspace environment for deployed silica agents (alias).",
)
we = cyclopts.App(
    name="we",
    help="Manage workspace environment for deployed silica agents (short alias).",
)


def _setup_impl():
    """Implementation of the setup command."""
    console.print(
        Panel.fit(
            "[bold blue]Silica Workspace Environment Setup[/bold blue]",
            border_style="blue",
        )
    )

    # Check Python version and set up Python 3.11 if needed
    if not check_python_version():
        console.print("[yellow]Python 3.11+ required. Running Python setup...[/yellow]")
        if not setup_python_environment():
            console.print("[red]✗ Failed to set up Python environment[/red]")
            sys.exit(1)

    # Load environment
    load_environment_variables()

    # Sync dependencies
    if not sync_dependencies():
        console.print("[red]✗ Failed to sync dependencies[/red]")
        sys.exit(1)

    # Get workspace configuration (always silica_developer now)
    workspace_config = get_workspace_config()
    if not workspace_config:
        console.print("[red]✗ Could not determine workspace configuration[/red]")
        sys.exit(1)

    console.print("[cyan]Built-in silica developer agent[/cyan]")

    # Verify silica is available
    if not verify_silica_available():
        console.print("[red]✗ Silica developer not available[/red]")
        sys.exit(1)

    # Check environment variables
    missing_req = []
    missing_rec = []

    for env_var in get_required_env_vars():
        if not os.getenv(env_var["name"]):
            if env_var["name"] == "BRAVE_SEARCH_API_KEY":
                missing_rec.append((env_var["name"], env_var["description"]))
            else:
                missing_req.append((env_var["name"], env_var["description"]))

    env_ok = len(missing_req) == 0
    if not env_ok:
        console.print("[red]✗ Required environment variables are missing:[/red]")
        for env_name, description in missing_req:
            console.print(f"    [red]{env_name}[/red]: {description}")
        sys.exit(1)

    if missing_rec:
        console.print(
            "[yellow]⚠ Recommended environment variables are missing:[/yellow]"
        )
        for env_name, description in missing_rec:
            console.print(f"    [yellow]{env_name}[/yellow]: {description}")

    # Check code directory
    setup_code_directory()

    console.print(
        Panel.fit(
            "[bold green]✓ Workspace environment setup complete![/bold green]",
            border_style="green",
        )
    )


def _run_impl():
    """Implementation of the run command."""
    console.print(
        Panel.fit("[bold blue]Starting Silica Agent[/bold blue]", border_style="blue")
    )

    # Load environment
    load_environment_variables()

    # Get workspace configuration (always silica_developer now)
    workspace_config = get_workspace_config()
    if not workspace_config:
        console.print("[red]✗ Could not determine workspace configuration[/red]")
        sys.exit(1)

    # Verify silica is available (no installation needed)
    if not verify_silica_available():
        console.print("[red]✗ Silica developer not available[/red]")
        sys.exit(1)

    # Generate launch command
    launch_command = get_silica_developer_command(workspace_config)

    # Change to code directory if it exists
    code_dir = Path.cwd() / "code"
    if code_dir.exists():
        os.chdir(code_dir)
        console.print(f"[green]Changed to code directory: {code_dir}[/green]")
    else:
        console.print(
            f"[yellow]Code directory not found, staying in: {Path.cwd()}[/yellow]"
        )

    console.print(f"[cyan]Launch command: {launch_command}[/cyan]")
    console.print(
        f"[green]Starting silica developer from {os.getcwd()} at {datetime.now()}[/green]"
    )

    try:
        result = subprocess.run(
            launch_command,
            shell=True,
            env=os.environ.copy(),  # Pass current environment
        )
        console.print(
            f"[yellow]Agent exited with status {result.returncode} at {datetime.now()}[/yellow]"
        )

    except KeyboardInterrupt:
        console.print("[yellow]Agent interrupted by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error running agent: {e}[/red]")
        sys.exit(1)

    console.print("[dim]Agent process has ended. Keeping tmux session alive.[/dim]")
    try:
        input("Press Enter to exit...")
    except (KeyboardInterrupt, EOFError):
        pass


def _status_impl(json_output=False):
    """Implementation of the status command."""
    # Collect status data
    status_data = {}

    if not json_output:
        console.print(
            Panel.fit(
                "[bold blue]Workspace Environment Status[/bold blue]",
                border_style="blue",
            )
        )

        # Create status table
        table = Table(
            title="Environment Status", show_header=True, header_style="bold magenta"
        )
        table.add_column("Component", style="cyan", no_wrap=True)
        table.add_column("Status", style="white")
        table.add_column("Details", style="dim")

    # Check current directory
    current_dir = Path.cwd()
    status_data["working_directory"] = {"status": "ok", "path": str(current_dir)}
    if not json_output:
        table.add_row("Working Directory", "✓", str(current_dir))

    # Check if we can load environment
    env_loaded = load_environment_variables(silent=json_output)
    status_data["environment_variables"] = {
        "status": "ok" if env_loaded else "error",
        "loaded": env_loaded,
        "source": "piku ENV file",
    }
    if not json_output:
        env_status = "✓ Loaded" if env_loaded else "✗ Not Found"
        table.add_row("Environment Variables", env_status, "From piku ENV file")

    # Check uv availability
    try:
        result = subprocess.run(
            ["uv", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            env=os.environ.copy(),  # Pass current environment
        )
        if result.returncode == 0:
            uv_version = result.stdout.strip()
            status_data["uv_package_manager"] = {
                "status": "ok",
                "available": True,
                "version": uv_version,
            }
            if not json_output:
                table.add_row("UV Package Manager", "✓ Available", uv_version)
        else:
            status_data["uv_package_manager"] = {
                "status": "error",
                "available": False,
                "error": "Command failed",
            }
            if not json_output:
                table.add_row("UV Package Manager", "✗ Error", "Command failed")
    except FileNotFoundError:
        status_data["uv_package_manager"] = {
            "status": "error",
            "available": False,
            "error": "Not found - please install uv",
        }
        if not json_output:
            table.add_row("UV Package Manager", "✗ Not Found", "Please install uv")
    except Exception as e:
        status_data["uv_package_manager"] = {
            "status": "error",
            "available": False,
            "error": str(e),
        }
        if not json_output:
            table.add_row("UV Package Manager", "✗ Error", str(e))

    # Check workspace config
    workspace_config = get_workspace_config()
    if workspace_config:
        status_data["workspace_config"] = {
            "status": "ok",
            "found": True,
            "agent_type": "silica_developer",
            "config": workspace_config,
        }
        if not json_output:
            table.add_row(
                "Workspace Config",
                "✓ Found",
                "Agent type: silica developer (silica_developer)",
            )

        try:
            # Built-in silica developer - always valid
            status_data["agent_config"] = {
                "status": "ok",
                "valid": True,
                "name": "silica_developer",
                "description": "Built-in Silica Developer",
            }
            if not json_output:
                table.add_row("Agent Config", "✓ Built-in", "Silica Developer")

            # Check if silica is available (built-in)
            agent_available = verify_silica_available()
            status_data["agent_installation"] = {
                "status": "ok" if agent_available else "error",
                "installed": agent_available,
                "agent_name": "silica_developer",
            }
            if not json_output:
                if agent_available:
                    table.add_row("Agent Availability", "✓ Available", "Built-in")
                else:
                    table.add_row(
                        "Agent Availability",
                        "✗ Not Available",
                        "Check silica installation",
                    )

            # Check environment variables
            missing_req = []
            missing_rec = []
            for env_var in get_required_env_vars():
                if not os.getenv(env_var["name"]):
                    if env_var["name"] == "BRAVE_SEARCH_API_KEY":
                        missing_rec.append((env_var["name"], env_var["description"]))
                    else:
                        missing_req.append((env_var["name"], env_var["description"]))

            env_ok = len(missing_req) == 0
            status_data["agent_environment"] = {
                "status": "ok" if env_ok else "error",
                "complete": env_ok and not missing_rec,
                "missing_required": [
                    {"name": name, "description": desc} for name, desc in missing_req
                ],
                "missing_recommended": [
                    {"name": name, "description": desc} for name, desc in missing_rec
                ],
            }
            if not json_output:
                if env_ok and not missing_rec:
                    table.add_row(
                        "Agent Environment", "✓ Complete", "All variables configured"
                    )
                elif env_ok:
                    table.add_row(
                        "Agent Environment",
                        "⚠ Partial",
                        f"{len(missing_rec)} recommended missing",
                    )
                else:
                    table.add_row(
                        "Agent Environment",
                        "✗ Incomplete",
                        f"{len(missing_req)} required missing",
                    )

        except Exception as e:
            status_data["agent_config"] = {
                "status": "error",
                "valid": False,
                "error": str(e),
            }
            if not json_output:
                table.add_row("Agent Config", "✗ Error", str(e))
    else:
        status_data["workspace_config"] = {
            "status": "error",
            "found": False,
            "error": "Cannot determine configuration",
        }
        if not json_output:
            table.add_row(
                "Workspace Config", "✗ Not Found", "Cannot determine configuration"
            )

    # Check code directory
    code_dir = current_dir / "code"
    if code_dir.exists() and code_dir.is_dir():
        try:
            # Check if it's a git repo
            git_dir = code_dir / ".git"
            if git_dir.exists():
                # Get current branch
                result = subprocess.run(
                    ["git", "branch", "--show-current"],
                    cwd=code_dir,
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=os.environ.copy(),  # Pass current environment
                )
                if result.returncode == 0:
                    branch = result.stdout.strip()
                    status_data["code_directory"] = {
                        "status": "ok",
                        "exists": True,
                        "is_git_repo": True,
                        "branch": branch,
                        "path": str(code_dir),
                    }
                    if not json_output:
                        table.add_row(
                            "Code Directory", "✓ Git Repository", f"Branch: {branch}"
                        )
                else:
                    status_data["code_directory"] = {
                        "status": "ok",
                        "exists": True,
                        "is_git_repo": True,
                        "branch": "unknown",
                        "path": str(code_dir),
                    }
                    if not json_output:
                        table.add_row(
                            "Code Directory", "✓ Git Repository", "Branch unknown"
                        )
            else:
                status_data["code_directory"] = {
                    "status": "ok",
                    "exists": True,
                    "is_git_repo": False,
                    "path": str(code_dir),
                }
                if not json_output:
                    table.add_row(
                        "Code Directory", "✓ Directory", "Not a git repository"
                    )
        except Exception as e:
            status_data["code_directory"] = {
                "status": "ok",
                "exists": True,
                "is_git_repo": None,
                "error": str(e),
                "path": str(code_dir),
            }
            if not json_output:
                table.add_row("Code Directory", "✓ Directory", f"Git status error: {e}")
    else:
        status_data["code_directory"] = {
            "status": "error",
            "exists": False,
            "path": str(code_dir),
            "message": "Should be synced separately",
        }
        if not json_output:
            table.add_row(
                "Code Directory", "✗ Not Found", "Should be synced separately"
            )

    if json_output:
        # Calculate overall status
        overall_status = "ok"
        issues = []

        if not status_data["environment_variables"]["loaded"]:
            overall_status = "warning"
            issues.append("Environment variables not loaded")

        if status_data["uv_package_manager"]["status"] != "ok":
            overall_status = "error"
            issues.append("UV package manager not available")

        if status_data["workspace_config"]["status"] != "ok":
            overall_status = "error"
            issues.append("Workspace configuration not found")
        elif (
            "agent_installation" in status_data
            and not status_data["agent_installation"]["installed"]
        ):
            if overall_status == "ok":
                overall_status = "warning"
            issues.append("Agent not installed")

        if (
            "agent_environment" in status_data
            and status_data["agent_environment"]["missing_required"]
        ):
            overall_status = "error"
            issues.append("Required environment variables missing")

        if not status_data["code_directory"]["exists"]:
            if overall_status == "ok":
                overall_status = "warning"
            issues.append("Code directory not found")

        # Build JSON response
        json_response = {
            "overall_status": overall_status,
            "timestamp": datetime.now().isoformat(),
            "issues": issues,
            "components": status_data,
        }

        import json

        print(json.dumps(json_response, indent=2))
    else:
        console.print(table)

        # Show next steps if there are issues
        console.print("\n[bold]Next Steps:[/bold]")
        if not env_loaded:
            console.print(
                "• Environment variables not loaded - check piku configuration"
            )

        workspace_config = get_workspace_config()
        if workspace_config:
            if not verify_silica_available():
                console.print("• Check silica installation")

            # Check environment variables
            missing_req = []
            for env_var in get_required_env_vars():
                if (
                    not os.getenv(env_var["name"])
                    and env_var["name"] != "BRAVE_SEARCH_API_KEY"
                ):
                    missing_req.append((env_var["name"], env_var["description"]))

            if missing_req:
                console.print("• Configure required environment variables through piku")

        if not (code_dir.exists() and code_dir.is_dir()):
            console.print("• Sync code directory using [cyan]silica sync[/cyan]")

        console.print("• Run [cyan]silica we run[/cyan] to start the agent")


# Register the implementation functions as commands
@workspace_environment.command
@workspace_environment_.command
@we.command
def setup():
    """Set up the workspace environment idempotently."""
    return _setup_impl()


@workspace_environment.command
@workspace_environment_.command
@we.command
def run():
    """Run the configured agent in the workspace environment."""
    return _run_impl()


@workspace_environment.command
@workspace_environment_.command
@we.command
def status(
    json_output: Annotated[
        bool,
        cyclopts.Parameter(
            name="--json",
            help="Output status in JSON format for programmatic consumption",
        ),
    ] = False,
):
    """Check the status of the workspace environment."""
    return _status_impl(json_output)
