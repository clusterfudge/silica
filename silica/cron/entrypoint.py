"""Cron module entrypoint with database migration integration."""

import cyclopts
import uvicorn
from .app import app as fastapi_app
from .cli import app as migration_cli
from .models.base import ensure_database_ready


app = cyclopts.App()


@app.default
def serve(
    bind_host: str = "127.0.0.1",
    bind_port: int = 8080,
    debug: bool = False,
    log_level: str = "info",
):
    """Start the cron web application.

    Automatically handles database migrations in production.
    """
    # Ensure database is ready (smart migration handling)
    if not ensure_database_ready():
        print("❌ Failed to prepare cron database")
        return 1

    print(f"🚀 Starting cron application on {bind_host}:{bind_port}")
    uvicorn.run(
        fastapi_app,
        host=bind_host,
        port=bind_port,
        reload=debug,
        log_level=log_level,
    )


# Add migration commands as subcommands
app.command(migration_cli, name="migrate")
