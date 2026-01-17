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


class ExecutePlanRequest(BaseModel):
    """Request model for executing a plan from a remote repository."""

    repo_url: str
    branch: str
    plan_id: str
    plan_title: str = ""


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


class PlanStatusResponse(BaseModel):
    """Response model for plan execution status."""

    plan_id: str
    plan_title: str
    plan_slug: str
    status: str  # "unknown", "draft", "in_progress", "completed", "abandoned"
    current_task: str | None = None  # Description of current task being worked on
    tasks_completed: int = 0
    tasks_verified: int = 0
    tasks_total: int = 0
    elapsed_seconds: float | None = None  # Time since plan started
    agent_status: str = "unknown"  # "idle", "working", "error"


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


@app.get("/capabilities")
async def get_capabilities():
    """Get server capabilities for feature detection.

    Clients should check this endpoint to determine which features
    are supported before using them.
    """
    return {
        "version": __version__,
        "workspace": config.get_workspace_name(),
        "capabilities": [
            "initialize",
            "tell",
            "status",
            "destroy",
            "execute-plan",  # Plan execution support
            "plan-status",  # Query plan execution status
        ],
    }


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


@app.post("/execute-plan", response_model=MessageResponse)
async def execute_plan(request: ExecutePlanRequest):
    """Initialize workspace and execute a plan.

    This endpoint:
    1. Clones/updates the repository on the specified branch
    2. Sets up the environment
    3. Starts the agent with instructions to execute the plan

    Args:
        request: Plan execution parameters

    Returns:
        Success/failure response
    """
    workspace_name = config.get_workspace_name()

    logger.info(
        "execute_plan_started",
        workspace_name=workspace_name,
        repo_url=request.repo_url,
        branch=request.branch,
        plan_id=request.plan_id,
        plan_title=request.plan_title,
    )

    try:
        # Step 1: Setup code directory and repository
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

        # Step 2: Setup development environment
        logger.info("environment_setup_starting", workspace_name=workspace_name)
        if not agent_manager.setup_environment():
            logger.error("environment_setup_failed", workspace_name=workspace_name)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to setup development environment",
            )

        # Step 3: Start tmux session
        logger.info("tmux_session_starting", workspace_name=workspace_name)
        if not agent_manager.start_tmux_session():
            logger.error("tmux_session_start_failed", workspace_name=workspace_name)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to start tmux session",
            )

        # Step 4: Send plan execution message to agent
        plan_title = request.plan_title or request.plan_id
        execution_message = f"""Execute plan "{plan_title}" (ID: {request.plan_id}).

The plan file should be in .agent/plans/active/{request.plan_id}.md or .silica/plans/active/{request.plan_id}.md.

Please:
1. Read the plan using `read_plan("{request.plan_id}")`
2. Start execution with `exit_plan_mode("{request.plan_id}", "execute")`
3. Work through each task, calling `complete_plan_task` and `verify_plan_task` as you go
4. When done, call `complete_plan("{request.plan_id}")`
5. Create a PR with your changes using `gh pr create`
6. Link the PR to the plan using `link_plan_pr("{request.plan_id}", "<pr_url>")`
"""

        if not agent_manager.send_message_to_session(execution_message):
            logger.error("execute_plan_send_failed", workspace_name=workspace_name)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to send plan execution message to agent",
            )

        logger.info(
            "execute_plan_completed",
            workspace_name=workspace_name,
            plan_id=request.plan_id,
        )
        return MessageResponse(
            success=True,
            message=f"Plan {request.plan_id} execution started in workspace {workspace_name}",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "execute_plan_unexpected_error",
            workspace_name=workspace_name,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Plan execution failed: {str(e)}",
        )


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


@app.get("/plan-status/{plan_id}", response_model=PlanStatusResponse)
async def get_plan_status(plan_id: str):
    """Get status of a plan being executed in this workspace.

    Args:
        plan_id: The ID of the plan to query

    Returns:
        Plan execution status including task progress
    """
    from pathlib import Path
    from datetime import datetime, timezone

    workspace_name = config.get_workspace_name()
    logger.debug(
        "get_plan_status_request", workspace_name=workspace_name, plan_id=plan_id
    )

    code_dir = config.get_code_directory()
    if not code_dir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not initialized",
        )

    # Look for the plan in the workspace's .silica/plans directory
    silica_dir = Path(code_dir) / ".silica"
    plans_active_dir = silica_dir / "plans" / "active"
    plans_completed_dir = silica_dir / "plans" / "completed"

    plan_file = None
    for search_dir in [plans_active_dir, plans_completed_dir]:
        candidate = search_dir / f"{plan_id}.md"
        if candidate.exists():
            plan_file = candidate
            break

    if not plan_file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan {plan_id} not found in workspace",
        )

    try:
        # Parse the plan file
        from silica.developer.plans import Plan

        plan_content = plan_file.read_text()
        plan = Plan.from_markdown(plan_content)

        # Calculate task stats
        tasks_completed = len([t for t in plan.tasks if t.completed])
        tasks_verified = len([t for t in plan.tasks if t.verified])
        tasks_total = len(plan.tasks)

        # Find current task (first incomplete task)
        current_task = None
        for task in plan.tasks:
            if not task.completed:
                current_task = task.description
                break

        # Calculate elapsed time if remote_started_at is set
        elapsed_seconds = None
        if plan.remote_started_at:
            elapsed_seconds = (
                datetime.now(timezone.utc) - plan.remote_started_at
            ).total_seconds()

        # Determine agent status based on tmux session
        agent_status = "unknown"
        try:
            tmux_status = agent_manager.get_workspace_status().get("tmux_session", {})
            if tmux_status.get("exists"):
                agent_status = "working"
            else:
                agent_status = "idle"
        except Exception:
            pass

        logger.info(
            "get_plan_status_success",
            workspace_name=workspace_name,
            plan_id=plan_id,
            status=plan.status.value,
            tasks_completed=tasks_completed,
            tasks_total=tasks_total,
        )

        return PlanStatusResponse(
            plan_id=plan.id,
            plan_title=plan.title,
            plan_slug=plan.get_slug(),
            status=plan.status.value,
            current_task=current_task,
            tasks_completed=tasks_completed,
            tasks_verified=tasks_verified,
            tasks_total=tasks_total,
            elapsed_seconds=elapsed_seconds,
            agent_status=agent_status,
        )

    except Exception as e:
        logger.error(
            "get_plan_status_error",
            workspace_name=workspace_name,
            plan_id=plan_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read plan status: {str(e)}",
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
@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Handle unexpected exceptions with workspace context."""
    from starlette.responses import JSONResponse

    # Don't override HTTPException - let FastAPI handle it
    if isinstance(exc, HTTPException):
        raise exc

    workspace_name = config.get_workspace_name()
    logger.error(
        "internal_server_error",
        workspace_name=workspace_name,
        error=str(exc),
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "workspace": workspace_name,
            "message": "An unexpected error occurred",
        },
    )


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
