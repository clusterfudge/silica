#!/usr/bin/env python3
"""Test the minimalist cron web interface."""

import uvicorn
from silica.cron.app import app

if __name__ == "__main__":
    print("Starting minimalist cron interface on http://localhost:8080")
    print("Features:")
    print("- Minimalist dashboard with '+' button")
    print("- Clean navigation between prompts, jobs, and status")
    print("- Removed verbose descriptions and banners")
    print("- Moved help content to /help page")
    print("\nPress Ctrl+C to stop")

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8080,
        reload=False,
        log_level="info",
    )
