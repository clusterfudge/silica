"""Main FastAPI application."""

import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from os.path import join, dirname

from .config import get_settings
from .config.logging import setup_logging, get_logger
from .models import get_db
from .routes import prompts, jobs, dashboard
from .routes.jobs import get_recent_executions
from .scheduler import scheduler
from .scripts.litestream_manager import LitestreamManager

# Get settings
settings = get_settings()

# Configure logging
setup_logging()
logger = get_logger(__name__)

# Initialize Litestream manager
litestream_manager = LitestreamManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    logger.info("Starting cron application")

    # Initialize database tables
    from .models import init_database

    init_database()

    # Start Litestream replication if enabled
    litestream_process = None
    if settings.litestream_enabled:
        try:
            logger.info("Starting Litestream replication")
            litestream_process = litestream_manager.start_replication()
        except Exception as e:
            logger.error(f"Failed to start Litestream: {e}")
            # Continue without Litestream in development
            if settings.environment == "prod":
                raise

    scheduler.start()

    yield

    # Shutdown
    logger.info("Shutting down cron application")
    scheduler.stop()

    # Stop Litestream
    if litestream_process:
        logger.info("Stopping Litestream replication")
        litestream_process.terminate()
        litestream_process.wait(timeout=10)


# Initialize FastAPI app
app = FastAPI(
    title="cron",
    description="Cron-style scheduling of agent prompts",
    version="0.1.0",
    lifespan=lifespan,
)

# Mount static files
app.mount(
    "/static", StaticFiles(directory=join(dirname(__file__), "static")), name="static"
)

# Templates
templates = Jinja2Templates(directory=join(dirname(__file__), "templates"))

# Include routers
app.include_router(prompts.router, prefix="/api/prompts", tags=["prompts"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
app.include_router(dashboard.router, prefix="", tags=["dashboard"])


app.add_api_route(
    "/api/recent-executions", get_recent_executions, methods=["GET"], tags=["dashboard"]
)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request, db: Session = Depends(get_db)):
    """Main dashboard page."""
    return templates.TemplateResponse(
        request, "dashboard.html", {"title": "Cron Dashboard"}
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    health_status = {"status": "healthy", "service": "cron"}

    # Add Litestream health if enabled
    if settings.litestream_enabled:
        litestream_health = litestream_manager.health_check()
        health_status["litestream"] = litestream_health

    return health_status


def entrypoint(
    bind_host: str = None,
    bind_port: int = None,
    debug: bool = None,
    log_level: str = None,
    enable_litestream: bool = None,
):
    """Entrypoint function."""
    # Use settings defaults if not provided
    host = bind_host or settings.host
    port = bind_port or settings.port
    reload = debug if debug is not None else settings.debug
    level = log_level or settings.log_level

    # Override Litestream setting if explicitly provided
    # Use environment variable so it persists across reloads
    if enable_litestream is not None:
        import os

        os.environ["LITESTREAM_ENABLED"] = "true" if enable_litestream else "false"
        # Also set it directly for immediate use
        settings.litestream_enabled = enable_litestream

    if reload:
        # Use import string for reload mode
        uvicorn.run(
            "silica.cron.app:app",
            host=host,
            port=port,
            reload=True,
            log_level=level,
        )
    else:
        # Use app object for production
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=False,
            log_level=level,
        )
