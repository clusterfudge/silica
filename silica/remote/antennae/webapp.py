"""FastAPI web application for antennae workspace management.

Provides HTTP endpoints to manage a single workspace containing a tmux session
running silica developer. Each antennae instance manages exactly one workspace.
"""

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from typing import Dict, Any
import structlog

from .config import config
from .agent_manager import agent_manager

# Import version from silica
try:
    from silica._version import __version__
except ImportError:
    __version__ = "unknown"

# Configure structured logging with proper handler setup
import logging
import sys

# Set up basic logging configuration for structlog to work properly
logging.basicConfig(
    format="%(message)s",
    stream=sys.stderr,
    level=logging.INFO,
)

# Configure structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Antennae Workspace Manager",
    description="HTTP API for managing remote development workspaces with silica developer",
    version=__version__,
)


# Request/Response Models
class InitializeRequest(BaseModel):
    """Request model for workspace initialization."""

    repo_url: str
    branch: str = "main"


class TellRequest(BaseModel):
    """Request model for sending messages to agent."""

    message: str


class StatusResponse(BaseModel):
    """Response model for workspace status."""

    workspace_name: str
    code_directory: str
    code_directory_exists: bool
    repository: Dict[str, Any]
    tmux_session: Dict[str, Any]
    agent_command: str
    version: str


class ConnectionResponse(BaseModel):
    """Response model for connection information."""

    session_name: str
    working_directory: str
    code_directory: str
    tmux_running: bool


class MessageResponse(BaseModel):
    """Generic response model for operation results."""

    success: bool
    message: str


@app.get("/")
async def root():
    """Root endpoint providing basic information."""
    return {
        "service": "antennae",
        "workspace": config.get_workspace_name(),
        "version": __version__,
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "workspace": config.get_workspace_name()}


@app.post("/initialize", response_model=MessageResponse)
async def initialize_workspace(request: InitializeRequest):
    """Initialize workspace by cloning repository, setting up environment, and starting tmux session.

    This method is idempotent - it can be called multiple times safely:
    - If repository already exists, it will be preserved (no destructive re-cloning)
    - If no repository exists, it will be cloned fresh
    - If environment setup fails, initialization fails with error
    - If tmux session exists, it will be preserved (avoids killing active agents)

    Args:
        request: Initialization parameters

    Returns:
        Success/failure response
    """
    workspace_name = config.get_workspace_name()

    # Log the request parameters in detail
    logger.info(
        "initialize_workspace_started",
        workspace_name=workspace_name,
        repo_url=request.repo_url,
        branch=request.branch,
        request_body=request.model_dump(),
    )

    try:
        # Step 1: Setup code directory and repository (idempotent)
        logger.info(
            "repository_setup_starting",
            workspace_name=workspace_name,
            repo_url=request.repo_url,
            branch=request.branch,
        )
        if not agent_manager.clone_repository(request.repo_url, request.branch):
            logger.error(
                "repository_setup_failed",
                workspace_name=workspace_name,
                repo_url=request.repo_url,
                branch=request.branch,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to setup repository",
            )
        logger.info(
            "repository_setup_completed",
            workspace_name=workspace_name,
            repo_url=request.repo_url,
        )

        # Step 2: Setup development environment (idempotent)
        logger.info("environment_setup_starting", workspace_name=workspace_name)
        if not agent_manager.setup_environment():
            logger.error("environment_setup_failed", workspace_name=workspace_name)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to setup development environment",
            )
        logger.info("environment_setup_completed", workspace_name=workspace_name)

        # Step 3: Start tmux session with agent (idempotent - preserves existing sessions)
        logger.info("tmux_session_starting", workspace_name=workspace_name)
        if not agent_manager.start_tmux_session():
            logger.error("tmux_session_start_failed", workspace_name=workspace_name)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to start tmux session",
            )

        logger.info(
            "initialize_workspace_completed",
            workspace_name=workspace_name,
            success=True,
        )
        return MessageResponse(
            success=True,
            message=f"Workspace {workspace_name} initialized successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "initialize_workspace_unexpected_error",
            workspace_name=workspace_name,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Initialization failed: {str(e)}",
        )


@app.post("/tell", response_model=MessageResponse)
async def tell_agent(request: TellRequest):
    """Send a message to the agent running in the tmux session.

    Args:
        request: Message to send to agent

    Returns:
        Success/failure response
    """
    workspace_name = config.get_workspace_name()

    # Log the request parameters for the tell endpoint
    logger.info(
        "tell_agent_request",
        workspace_name=workspace_name,
        message_length=len(request.message),
        request_body=request.model_dump(),
    )

    if not agent_manager.is_tmux_session_running():
        logger.warning("tell_agent_session_not_running", workspace_name=workspace_name)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tmux session is not running. Initialize the workspace first.",
        )

    if not agent_manager.send_message_to_session(request.message):
        logger.error("tell_agent_send_failed", workspace_name=workspace_name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send message to agent",
        )

    logger.info("tell_agent_success", workspace_name=workspace_name)
    return MessageResponse(success=True, message="Message sent to agent successfully")


@app.get("/status", response_model=StatusResponse)
async def get_workspace_status():
    """Get comprehensive status of the workspace.

    Returns:
        Detailed workspace status
    """
    workspace_name = config.get_workspace_name()
    logger.debug("get_workspace_status_request", workspace_name=workspace_name)

    status_info = agent_manager.get_workspace_status()

    return StatusResponse(
        workspace_name=status_info["workspace_name"],
        code_directory=status_info["code_directory"],
        code_directory_exists=status_info["code_directory_exists"],
        repository=status_info["repository"],
        tmux_session=status_info["tmux_session"],
        agent_command=status_info["agent_command"],
        version=__version__,
    )


@app.post("/destroy", response_model=MessageResponse)
async def destroy_workspace():
    """Destroy workspace by killing tmux session and cleaning up files.

    Returns:
        Success/failure response
    """
    workspace_name = config.get_workspace_name()
    logger.info("destroy_workspace_request", workspace_name=workspace_name)

    try:
        if not agent_manager.cleanup_workspace():
            logger.warning(
                "workspace_cleanup_partial_failure", workspace_name=workspace_name
            )
            return MessageResponse(
                success=True, message="Workspace destroyed (with some cleanup failures)"
            )

        logger.info("destroy_workspace_success", workspace_name=workspace_name)
        return MessageResponse(success=True, message="Workspace destroyed successfully")

    except Exception as e:
        logger.error(
            "destroy_workspace_error",
            workspace_name=workspace_name,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to destroy workspace: {str(e)}",
        )


@app.get("/connect", response_model=ConnectionResponse)
async def get_connection_info():
    """Get connection information for direct tmux access.

    Returns:
        Connection details for tmux session
    """
    workspace_name = config.get_workspace_name()
    logger.debug("get_connection_info_request", workspace_name=workspace_name)

    conn_info = agent_manager.get_connection_info()

    return ConnectionResponse(
        session_name=conn_info["session_name"],
        working_directory=conn_info["working_directory"],
        code_directory=conn_info["code_directory"],
        tmux_running=conn_info["tmux_running"],
    )


# Error handlers
@app.exception_handler(404)
async def not_found_handler(request, exc):
    """Handle 404 errors with workspace context."""
    return {
        "error": "Not found",
        "workspace": config.get_workspace_name(),
        "message": "The requested endpoint was not found",
    }


@app.exception_handler(500)
async def internal_server_error_handler(request, exc):
    """Handle 500 errors with workspace context."""
    workspace_name = config.get_workspace_name()
    logger.error(
        "internal_server_error",
        workspace_name=workspace_name,
        error=str(exc),
        exc_info=True,
    )
    return {
        "error": "Internal server error",
        "workspace": workspace_name,
        "message": "An unexpected error occurred",
    }


if __name__ == "__main__":
    import uvicorn

    # Get port from environment or default to 8000
    import os

    port = int(os.environ.get("PORT", "8000"))

    workspace_name = config.get_workspace_name()
    logger.info("starting_antennae_webapp", workspace_name=workspace_name, port=port)

    uvicorn.run(
        "silica.remote.antennae.webapp:app", host="0.0.0.0", port=port, log_level="info"
    )
