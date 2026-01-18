#!/usr/bin/env python3
"""Session state viewer for debugging silica conversations.

Usage:
    python scripts/session_viewer.py [session_id] [--persona NAME] [--port PORT]

    # View specific session
    python scripts/session_viewer.py 8b8d7140-f8bd-40df-be94-6a6904bff170

    # Browse sessions for a persona
    python scripts/session_viewer.py --persona autonomous_engineer

    # Start on custom port
    python scripts/session_viewer.py --port 8080
"""

import argparse
import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Global configuration
SILICA_DIR = Path.home() / ".silica"
PERSONAS_DIR = SILICA_DIR / "personas"
ACTIVE_PERSONA: str | None = None
INITIAL_SESSION_ID: str | None = None
LAUNCH_CWD: str | None = None  # Directory where the command was launched

app = FastAPI(title="Session Viewer", description="Debug viewer for silica sessions")

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent
STATIC_DIR = SCRIPT_DIR / "session_viewer_static"

# Mount static files
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    """Serve the index.html file."""
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return {"error": "Frontend not found. Run from project root."}
    return FileResponse(index_file)


@app.get("/api/config")
async def get_config():
    """Get initial configuration."""
    return {
        "active_persona": ACTIVE_PERSONA,
        "initial_session_id": INITIAL_SESSION_ID,
        "launch_cwd": LAUNCH_CWD,
    }


@app.get("/api/personas")
async def list_personas():
    """List available personas."""
    personas = []
    if PERSONAS_DIR.exists():
        for persona_dir in sorted(PERSONAS_DIR.iterdir()):
            if persona_dir.is_dir() and not persona_dir.name.startswith("."):
                history_dir = persona_dir / "history"
                session_count = 0
                if history_dir.exists():
                    session_count = len(
                        [d for d in history_dir.iterdir() if d.is_dir()]
                    )
                personas.append(
                    {
                        "name": persona_dir.name,
                        "session_count": session_count,
                        "has_persona_md": (persona_dir / "persona.md").exists(),
                    }
                )
    return {"personas": personas, "active_persona": ACTIVE_PERSONA}


@app.get("/api/sessions")
async def list_sessions(
    persona: str | None = None,
    limit: int = 50,
    root_dir: str | None = None,
):
    """List sessions for a persona or all personas.

    Args:
        persona: Filter by persona name
        limit: Maximum number of sessions to return
        root_dir: Filter by root_dir (working directory)
    """
    sessions = []

    if persona:
        persona_dirs = [PERSONAS_DIR / persona]
    else:
        persona_dirs = [
            d
            for d in PERSONAS_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]

    for persona_dir in persona_dirs:
        history_dir = persona_dir / "history"
        if not history_dir.exists():
            continue

        for session_dir in history_dir.iterdir():
            if not session_dir.is_dir():
                continue

            root_file = session_dir / "root.json"
            if not root_file.exists():
                continue

            try:
                with open(root_file) as f:
                    data = json.load(f)

                metadata = data.get("metadata", {})
                messages = data.get("messages", [])
                session_root_dir = metadata.get("root_dir")

                # Filter by root_dir if specified
                if root_dir and session_root_dir != root_dir:
                    continue

                # Count sub-agent sessions
                subagent_files = list(session_dir.glob("toolu_*.json"))

                sessions.append(
                    {
                        "session_id": data.get("session_id", session_dir.name),
                        "persona": persona_dir.name,
                        "created_at": metadata.get("created_at"),
                        "last_updated": metadata.get("last_updated"),
                        "root_dir": session_root_dir,
                        "message_count": len(messages),
                        "subagent_count": len(subagent_files),
                        "has_active_plan": bool(data.get("active_plan_id")),
                        "model": data.get("model_spec", {}).get("model", "unknown"),
                    }
                )
            except (json.JSONDecodeError, IOError):
                continue

    # Sort by last_updated descending
    sessions.sort(
        key=lambda s: s.get("last_updated") or s.get("created_at") or "", reverse=True
    )

    # Return sessions with metadata about filtering
    return {
        "sessions": sessions[:limit],
        "filtered_by_root_dir": root_dir is not None,
        "total_before_limit": len(sessions),
    }


@app.get("/api/session/{persona}/{session_id}")
async def get_session(persona: str, session_id: str):
    """Get full session data."""
    session_dir = PERSONAS_DIR / persona / "history" / session_id
    root_file = session_dir / "root.json"

    if not root_file.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        with open(root_file) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read session: {e}")

    # Find sub-agent sessions
    subagent_files = {}
    for subagent_file in session_dir.glob("toolu_*.json"):
        tool_id = subagent_file.stem
        subagent_files[tool_id] = True

    # Get persona.md content if exists
    persona_md = None
    persona_file = PERSONAS_DIR / persona / "persona.md"
    if persona_file.exists():
        try:
            persona_md = persona_file.read_text()
        except IOError:
            pass

    return {
        "session": data,
        "subagent_files": subagent_files,
        "persona_md": persona_md,
        "session_dir": str(session_dir),
    }


@app.get("/api/session/{persona}/{session_id}/subagent/{tool_id}")
async def get_subagent_session(persona: str, session_id: str, tool_id: str):
    """Get sub-agent session data."""
    session_dir = PERSONAS_DIR / persona / "history" / session_id
    subagent_file = session_dir / f"{tool_id}.json"

    if not subagent_file.exists():
        raise HTTPException(status_code=404, detail="Sub-agent session not found")

    try:
        with open(subagent_file) as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to read sub-agent session: {e}"
        )

    return {"session": data}


@app.get("/api/tools")
async def get_tools():
    """Get tool schemas from silica."""
    try:
        from silica.developer.tools import ALL_TOOLS

        tools = []
        for tool in ALL_TOOLS:
            try:
                # Tools are functions decorated with @tool
                # They have a .schema attribute that is a callable returning the spec
                if hasattr(tool, "schema") and callable(tool.schema):
                    spec = tool.schema()
                    tools.append(
                        {
                            "name": spec.get(
                                "name", getattr(tool, "__name__", "unknown")
                            ),
                            "description": spec.get("description", ""),
                            "input_schema": spec.get("input_schema", {}),
                        }
                    )
                else:
                    # Fallback for tools without proper spec
                    tools.append(
                        {
                            "name": getattr(tool, "__name__", "unknown"),
                            "description": tool.__doc__ or "",
                            "input_schema": {},
                        }
                    )
            except Exception:
                # Fallback for any tool that fails
                tools.append(
                    {
                        "name": getattr(tool, "__name__", "unknown"),
                        "description": getattr(tool, "__doc__", "") or "",
                        "input_schema": {},
                    }
                )

        return {"tools": tools}
    except ImportError as e:
        return {"tools": [], "error": f"Could not import tools: {e}"}


@app.get("/api/file")
async def read_file(path: str, root_dir: str | None = None):
    """Read a file for @file-mention expansion."""
    # Resolve path relative to root_dir if provided
    if root_dir:
        file_path = Path(root_dir) / path
    else:
        file_path = Path(path)

    if not file_path.exists():
        return {"exists": False, "path": str(file_path)}

    if not file_path.is_file():
        return {"exists": False, "path": str(file_path), "error": "Not a file"}

    try:
        # Limit file size to 100KB
        if file_path.stat().st_size > 100 * 1024:
            return {
                "exists": True,
                "path": str(file_path),
                "truncated": True,
                "content": file_path.read_text()[: 100 * 1024] + "\n... (truncated)",
            }

        return {
            "exists": True,
            "path": str(file_path),
            "content": file_path.read_text(),
        }
    except IOError as e:
        return {"exists": True, "path": str(file_path), "error": str(e)}


def main():
    global ACTIVE_PERSONA, INITIAL_SESSION_ID, LAUNCH_CWD

    parser = argparse.ArgumentParser(description="Session state viewer for debugging")
    parser.add_argument("session_id", nargs="?", help="Session ID to view")
    parser.add_argument("--persona", "-p", help="Persona to filter by")
    parser.add_argument("--port", type=int, default=8000, help="Port to run on")
    parser.add_argument(
        "--cwd",
        help="Working directory to filter sessions by (default: current directory)",
    )

    args = parser.parse_args()

    ACTIVE_PERSONA = args.persona or "default"
    INITIAL_SESSION_ID = args.session_id
    LAUNCH_CWD = args.cwd or str(Path.cwd())

    print(f"Starting session viewer on http://localhost:{args.port}")
    if ACTIVE_PERSONA:
        print(f"Default persona: {ACTIVE_PERSONA}")
    if LAUNCH_CWD:
        print(f"Working directory: {LAUNCH_CWD}")
    if INITIAL_SESSION_ID:
        print(f"Initial session: {INITIAL_SESSION_ID}")

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
