"""FastAPI application for Memory Proxy service."""

import logging
from typing import Dict

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from .auth import verify_token
from .config import Settings
from .models import (
    ErrorResponse,
    HealthResponse,
    PreconditionFailedResponse,
    SyncIndexResponse,
)
from .storage import (
    FileNotFoundError,
    PreconditionFailedError,
    S3Storage,
    StorageError,
)

# Get settings
settings = Settings()

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Memory Proxy Service",
    description="Remote KV proxy for blob storage with sync support and namespaces",
    version="0.2.0",
)

# Initialize storage
storage = S3Storage(settings)


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """
    Health check endpoint (no authentication required).

    Returns service health and storage connectivity status.
    """
    storage_ok = storage.health_check()

    if storage_ok:
        return HealthResponse(status="ok", storage="connected")
    else:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "error", "storage": "disconnected"},
        )


@app.get("/blob/{namespace}/{path:path}", tags=["blob"])
async def read_blob(
    namespace: str,
    path: str,
    user_info: Dict = Depends(verify_token),
):
    """
    Read a file from blob storage within a namespace.

    Args:
        namespace: Persona/namespace identifier (e.g., "default", "coding-agent")
        path: File path within namespace

    Returns file contents with ETag, Last-Modified, X-Version, and Content-Type headers.
    Returns 404 if file doesn't exist or is tombstoned.
    """
    try:
        content, md5, last_modified, content_type, version = storage.read_file(
            namespace, path
        )

        return Response(
            content=content,
            media_type=content_type,
            headers={
                "ETag": f'"{md5}"',
                "Last-Modified": last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT"),
                "X-Version": str(version),
            },
        )

    except FileNotFoundError as e:
        logger.warning(f"File not found: {namespace}/{path}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except StorageError as e:
        logger.error(f"Storage error reading {namespace}/{path}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Storage error",
        )


@app.put("/blob/{namespace}/{path:path}", tags=["blob"])
async def write_blob(
    namespace: str,
    path: str,
    request: Request,
    user_info: Dict = Depends(verify_token),
    content_md5: str | None = Header(default=None, alias="Content-MD5"),
    content_type: str | None = Header(default="application/octet-stream"),
):
    """
    Write or update a file in blob storage within a namespace.

    Args:
        namespace: Persona/namespace identifier
        path: File path within namespace

    Supports conditional writes via Content-MD5 header:
    - Omit header or use "new" for new files (fails if file exists)
    - Provide expected MD5 for updates (fails if current MD5 doesn't match)

    Returns 201 for new files, 200 for updates, 412 for precondition failures.
    Returns ETag and X-Version headers.
    """
    try:
        # Read request body
        content = await request.body()

        # Perform write with conditional check
        is_new, new_md5, version = storage.write_file(
            namespace=namespace,
            path=path,
            content=content,
            content_type=content_type,
            expected_md5=content_md5,
        )

        status_code = status.HTTP_201_CREATED if is_new else status.HTTP_200_OK

        return Response(
            status_code=status_code,
            headers={"ETag": f'"{new_md5}"', "X-Version": str(version)},
        )

    except PreconditionFailedError as e:
        logger.warning(f"Precondition failed for {namespace}/{path}: {e}")
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=PreconditionFailedResponse(
                detail=str(e),
                context={
                    "current_md5": e.current_md5,
                    "provided_md5": e.provided_md5,
                },
            ).model_dump(),
        )

    except StorageError as e:
        logger.error(f"Storage error writing {namespace}/{path}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Storage error",
        )


@app.delete(
    "/blob/{namespace}/{path:path}",
    tags=["blob"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_blob(
    namespace: str,
    path: str,
    user_info: Dict = Depends(verify_token),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    """
    Delete a file by creating a tombstone within a namespace.

    Args:
        namespace: Persona/namespace identifier
        path: File path within namespace

    Supports conditional delete via If-Match header with expected MD5.
    Returns 204 on success, 404 if file doesn't exist, 412 on precondition failure.
    """
    try:
        # Remove quotes from ETag if present
        expected_md5 = if_match.strip('"') if if_match else None

        storage.delete_file(namespace=namespace, path=path, expected_md5=expected_md5)

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except FileNotFoundError as e:
        logger.warning(f"File not found for delete: {namespace}/{path}")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    except PreconditionFailedError as e:
        logger.warning(f"Precondition failed for delete {namespace}/{path}: {e}")
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=PreconditionFailedResponse(
                detail=str(e),
                context={
                    "current_md5": e.current_md5,
                    "provided_md5": e.provided_md5,
                },
            ).model_dump(),
        )

    except StorageError as e:
        logger.error(f"Storage error deleting {namespace}/{path}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Storage error",
        )


@app.get("/sync/{namespace}", response_model=SyncIndexResponse, tags=["sync"])
async def get_sync_index(namespace: str, user_info: Dict = Depends(verify_token)):
    """
    Get the sync index with metadata for all files within a namespace.

    Args:
        namespace: Persona/namespace identifier

    Returns a map of file paths to metadata (MD5, last modified, size, version, deleted flag).
    Clients use this to determine which files need syncing.
    """
    try:
        sync_index = storage.get_sync_index(namespace)
        return sync_index

    except StorageError as e:
        logger.error(f"Storage error getting sync index for {namespace}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Storage error",
        )


# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with consistent error format."""
    # If detail is already a dict (from PreconditionFailedResponse), use it directly
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(detail=str(exc.detail)).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            detail="Internal server error", error_code="INTERNAL_ERROR"
        ).model_dump(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
