"""
CLI command for the Silica WebSocket server.
"""

import asyncio
from pathlib import Path
from typing import Annotated, Optional

import cyclopts

from silica.developer.sandbox import SandboxMode


serve_app = cyclopts.App(name="serve", help="Run the Silica WebSocket server")


SANDBOX_MODE_MAP = {
    "request_every_time": SandboxMode.REQUEST_EVERY_TIME,
    "remember_per_resource": SandboxMode.REMEMBER_PER_RESOURCE,
    "remember_all": SandboxMode.REMEMBER_ALL,
    "allow_all": SandboxMode.ALLOW_ALL,
    "dwr": SandboxMode.ALLOW_ALL,  # Alias
}


def parse_sandbox_mode(value: str) -> SandboxMode:
    """Parse a sandbox mode string into a SandboxMode enum."""
    canonicalized = value.lower().replace("-", "_")
    if canonicalized in SANDBOX_MODE_MAP:
        return SANDBOX_MODE_MAP[canonicalized]
    raise ValueError(
        f"Invalid sandbox mode: {value}. Valid modes: {list(SANDBOX_MODE_MAP.keys())}"
    )


@serve_app.default
def serve(
    host: Annotated[str, cyclopts.Parameter(help="Host to bind to")] = "0.0.0.0",
    port: Annotated[int, cyclopts.Parameter(help="Port to listen on")] = 8765,
    model: Annotated[
        str, cyclopts.Parameter(help="Default AI model for sessions")
    ] = "sonnet",
    sandbox_mode: Annotated[
        str,
        cyclopts.Parameter(
            help="Sandbox mode (request_every_time, remember_per_resource, remember_all, allow_all, dwr)"
        ),
    ] = "remember_all",
    persona: Annotated[Optional[str], cyclopts.Parameter(help="Persona to use")] = None,
):
    """
    Run the Silica WebSocket server.

    The server accepts WebSocket connections and creates agent sessions
    for each client. Clients communicate using the JSONL protocol.

    Example:
        silica serve --port 8765
        silica serve --host 127.0.0.1 --port 9000 --model opus
    """
    from silica.serve.server import run_server
    from silica.developer import personas

    # Parse sandbox mode
    try:
        parsed_mode = parse_sandbox_mode(sandbox_mode)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    # Get persona base directory
    if persona:
        persona_obj = personas.get_persona(persona)
        persona_base_dir = persona_obj.base_directory
    else:
        persona_base_dir = Path.home() / ".silica" / "personas" / "default"

    print("Starting Silica WebSocket server...")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  Model: {model}")
    print(f"  Sandbox mode: {parsed_mode.name}")
    print(f"  Persona: {persona or 'default'}")
    print()
    print(f"Connect at: ws://{host}:{port}/ws")
    print()

    # Run the server
    asyncio.run(
        run_server(
            host=host,
            port=port,
            model=model,
            sandbox_mode=parsed_mode,
            persona_base_dir=persona_base_dir,
        )
    )
