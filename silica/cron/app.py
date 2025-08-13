"""Main FastAPI application."""

import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from os.path import join, dirname

from .models import Base, engine, get_db
from .routes import prompts, jobs, dashboard
from .scheduler import scheduler

# Configure logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# Create database tables
Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    logger.info("Starting cron application")
    scheduler.start()
    yield
    # Shutdown
    logger.info("Shutting down cron application")
    scheduler.stop()


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


@app.get("/", response_class=HTMLResponse)
async def root(request: Request, db: Session = Depends(get_db)):
    """Main dashboard page."""
    return templates.TemplateResponse(
        request, "dashboard.html", {"title": "Cron Dashboard"}
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "service": "cron"}


def entrypoint(
    bind_host: str = "127.0.0.1",
    bind_port: int = 8080,
    debug: bool = False,
    log_level: str = "info",
):
    """Entrypoint function."""
    uvicorn.run(
        app,
        host=bind_host,
        port=bind_port,
        reload=debug,  # Set to True for development
        log_level=log_level,
    )
