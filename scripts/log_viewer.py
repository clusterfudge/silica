#!/usr/bin/env python3
"""Simple web-based log viewer for request/response logs.

Usage:
    python scripts/log_viewer.py requests.jsonl
    # Then open http://localhost:8000
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

# Global storage for logs
LOGS: List[Dict[str, Any]] = []
LOG_FILE: Path = None

app = FastAPI(title="Log Viewer", description="Request/Response Log Viewer")

# Get the directory where this script is located
SCRIPT_DIR = Path(__file__).parent
STATIC_DIR = SCRIPT_DIR / "log_viewer_static"

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def index():
    """Serve the index.html file."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/refresh")
async def refresh():
    """Reload logs from file."""
    load_logs()
    return {"status": "ok", "count": len(LOGS)}


@app.get("/api/logs")
async def get_logs():
    """Get logs as JSON."""
    return LOGS


@app.get("/api/stats")
async def get_stats():
    """Get log statistics."""
    stats = {
        "total": len(LOGS),
        "by_type": {},
    }

    for log in LOGS:
        log_type = log.get("type", "unknown")
        stats["by_type"][log_type] = stats["by_type"].get(log_type, 0) + 1

    return stats


def load_logs():
    """Load logs from the JSON Lines file."""
    global LOGS
    LOGS = []

    if not LOG_FILE.exists():
        print(f"Log file not found: {LOG_FILE}")
        return

    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    LOGS.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Failed to parse line: {e}")
                    continue


def main():
    global LOG_FILE

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    LOG_FILE = Path(sys.argv[1])

    if not LOG_FILE.exists():
        print(f"Error: Log file not found: {LOG_FILE}")
        sys.exit(1)

    print(f"Loading logs from: {LOG_FILE}")
    load_logs()
    print(f"Loaded {len(LOGS)} log entries")

    print("\nStarting web server on http://localhost:8000")
    print("Press Ctrl+C to stop")

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
