"""Sync tools command for silica remote.

Updates personal tools on an existing remote workspace.
For initial tool setup, use --with-tools during `silica remote create`.
"""

import base64
import subprocess
import tarfile
from io import BytesIO
from pathlib import Path
from typing import Annotated, List, Tuple

import cyclopts
from rich.console import Console
from rich.table import Table

from silica.remote.config import find_git_root, get_silica_dir
from silica.remote.config.multi_workspace import get_workspace_config
from silica.remote.utils import piku as piku_utils

console = Console()


def get_local_tools_dir() -> Path:
    """Get the local personal tools directory."""
    return Path.home() / ".silica" / "tools"


def list_local_tools(tools_dir: Path) -> List[Tuple[str, str, Path]]:
    """List all tool files with their descriptions.

    Returns:
        List of (name, description, path) tuples
    """
    if not tools_dir.exists():
        return []

    tools = []
    for path in sorted(tools_dir.glob("*.py")):
        if path.name.startswith("_") or path.name.startswith("."):
            continue

        # Try to get description
        try:
            result = subprocess.run(
                ["uv", "run", str(path), "--toolspec"],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=str(path.parent),
            )
            if result.returncode == 0:
                import json

                spec_data = json.loads(result.stdout)
                if isinstance(spec_data, list):
                    desc = f"{len(spec_data)} tools"
                else:
                    desc = spec_data.get("description", "")[:50]
                tools.append((path.stem, desc, path))
            else:
                tools.append((path.stem, "(error)", path))
        except Exception:
            tools.append((path.stem, "(error)", path))

    return tools


def create_tools_archive(tool_paths: List[Path], include_config: bool = True) -> bytes:
    """Create a tar.gz archive of the specified tools.

    Automatically includes:
    - All helper modules (files starting with _)
    - Config files (*.yml, *.yaml) if include_config is True

    Args:
        tool_paths: List of tool file paths
        include_config: Whether to include config files (default: True)

    Returns:
        Bytes of the tar.gz archive
    """
    buffer = BytesIO()
    tools_dir = tool_paths[0].parent if tool_paths else get_local_tools_dir()
    added_files = set()

    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        # Add the specified tools
        for path in tool_paths:
            tar.add(path, arcname=path.name)
            added_files.add(path.name)

        # Include ALL helper modules (files starting with _)
        # This ensures _google_auth.py and _silica_toolspec.py are synced
        for helper_path in tools_dir.glob("_*.py"):
            if helper_path.name not in added_files:
                tar.add(helper_path, arcname=helper_path.name)
                added_files.add(helper_path.name)

        # Include config files (for calendar configuration, etc.)
        if include_config:
            for config_path in tools_dir.glob("*.yml"):
                if config_path.name not in added_files:
                    tar.add(config_path, arcname=config_path.name)
                    added_files.add(config_path.name)
            for config_path in tools_dir.glob("*.yaml"):
                if config_path.name not in added_files:
                    tar.add(config_path, arcname=config_path.name)
                    added_files.add(config_path.name)

    buffer.seek(0)
    return buffer.read()


def sync_tools(
    workspace: Annotated[
        str,
        cyclopts.Parameter(name=["--workspace", "-w"], help="Name of the workspace"),
    ] = "agent",
    tool: Annotated[
        tuple[str, ...],
        cyclopts.Parameter(
            name=["--tool", "-t"],
            help="Specific tool(s) to sync (can be used multiple times)",
        ),
    ] = (),
    all_tools: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--all"],
            help="Sync all personal tools",
        ),
    ] = False,
    list_only: Annotated[
        bool,
        cyclopts.Parameter(
            name=["--list", "-l"],
            help="Just list local tools without syncing",
        ),
    ] = False,
):
    """Update personal tools on an existing remote workspace.

    Use this to sync tool changes after workspace creation, or to add
    new tools. For initial tool setup, use --with-tools during create.

    Examples:
        silica remote sync-tools -w agent --all          # Sync all tools
        silica remote sync-tools -w agent -t weather     # Sync specific tool
        silica remote sync-tools -w agent --list         # List available tools
    """
    local_tools_dir = get_local_tools_dir()

    if not local_tools_dir.exists():
        console.print(
            f"[yellow]No personal tools directory found at {local_tools_dir}[/yellow]"
        )
        console.print(
            "Create tools with `toolbox_create` or add .py files to the directory."
        )
        return

    tools = list_local_tools(local_tools_dir)

    if list_only:
        if not tools:
            console.print("[yellow]No personal tools found.[/yellow]")
            return

        console.print(f"[bold]Personal tools in {local_tools_dir}:[/bold]\n")

        table = Table(show_header=True, header_style="bold")
        table.add_column("Tool", style="cyan")
        table.add_column("Description")

        for name, desc, _ in tools:
            table.add_row(name, desc)

        console.print(table)
        console.print(f"\n[dim]Total: {len(tools)} tools[/dim]")
        return

    if not tools:
        console.print("[yellow]No personal tools to sync.[/yellow]")
        return

    # Determine which tools to sync
    if all_tools:
        selected_paths = [path for _, _, path in tools]
    elif tool:
        # Find specified tools
        tool_map = {name: path for name, _, path in tools}
        selected_paths = []
        for t in tool:
            if t in tool_map:
                selected_paths.append(tool_map[t])
            else:
                console.print(f"[yellow]Tool not found: {t}[/yellow]")

        if not selected_paths:
            console.print("[red]No valid tools specified.[/red]")
            return
    else:
        console.print("[yellow]Specify tools with --tool or use --all[/yellow]")
        console.print("Use --list to see available tools.")
        return

    # Find git root and silica directory
    git_root = find_git_root()
    if not git_root:
        console.print("[red]Error: Not in a git repository.[/red]")
        return

    silica_dir = get_silica_dir(git_root)
    if not silica_dir or not silica_dir.exists():
        console.print("[red]Error: No .silica directory found.[/red]")
        console.print("Run 'silica remote create' first to set up the workspace.")
        return

    # Check workspace configuration
    try:
        workspace_config = get_workspace_config(silica_dir, workspace)
    except Exception as e:
        console.print(f"[red]Error: Could not load workspace config: {e}[/red]")
        console.print(f"Make sure workspace '{workspace}' exists.")
        return

    is_local = workspace_config.get("is_local", False)

    if is_local:
        # For local workspaces, copy to workspace-local tools directory
        import shutil

        workspace_tools_dir = silica_dir / "workspaces" / workspace / "tools"
        workspace_tools_dir.mkdir(parents=True, exist_ok=True)

        # Copy ALL helper modules (files starting with _)
        for helper_path in local_tools_dir.glob("_*.py"):
            shutil.copy(helper_path, workspace_tools_dir / helper_path.name)

        # Copy config files (*.yml, *.yaml)
        for config_path in local_tools_dir.glob("*.yml"):
            shutil.copy(config_path, workspace_tools_dir / config_path.name)
        for config_path in local_tools_dir.glob("*.yaml"):
            shutil.copy(config_path, workspace_tools_dir / config_path.name)

        # Copy each tool
        for path in selected_paths:
            shutil.copy(path, workspace_tools_dir / path.name)

        console.print(
            f"[green]✓ Synced {len(selected_paths)} tools to {workspace_tools_dir}[/green]"
        )
        for path in selected_paths:
            console.print(f"  • {path.stem}")

        console.print(
            "\n[dim]Restart the agent session for changes to take effect.[/dim]"
        )
        return

    # Sync to remote workspace-local directory
    workspace_tools_path = f"~/.silica/workspaces/{workspace}/tools"
    console.print(
        f"[bold]Syncing {len(selected_paths)} tools to workspace '{workspace}'...[/bold]"
    )

    try:
        # Create tools directory on remote
        mkdir_cmd = f"mkdir -p {workspace_tools_path}"
        piku_utils.run_piku_in_silica(
            mkdir_cmd,
            workspace_name=workspace,
            use_shell_pipe=True,
            capture_output=True,
        )

        # Create and transfer archive
        archive_data = create_tools_archive(selected_paths)
        archive_b64 = base64.b64encode(archive_data).decode("ascii")

        extract_cmd = f"""cd {workspace_tools_path} && echo "{archive_b64}" | base64 -d | tar -xzf -"""
        piku_utils.run_piku_in_silica(
            extract_cmd,
            workspace_name=workspace,
            use_shell_pipe=True,
            capture_output=True,
        )

        console.print(f"[green]✓ Synced {len(selected_paths)} tools[/green]")
        for path in selected_paths:
            console.print(f"  • {path.stem}")

        console.print(
            "\n[dim]Restart the agent session for changes to take effect.[/dim]"
        )

    except Exception as e:
        console.print(f"[red]Error syncing tools: {e}[/red]")
