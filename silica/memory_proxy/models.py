"""Pydantic models for request and response validation."""

from datetime import datetime
from typing import Dict

from pydantic import BaseModel, Field


class FileMetadata(BaseModel):
    """Metadata for a single file in the sync index."""

    md5: str = Field(..., description="MD5 hash of file content")
    last_modified: datetime = Field(..., description="Last modification timestamp")
    size: int = Field(..., description="File size in bytes")
    is_deleted: bool = Field(default=False, description="Whether file is tombstoned")


class SyncIndexResponse(BaseModel):
    """Response model for GET /sync endpoint."""

    files: Dict[str, FileMetadata] = Field(
        default_factory=dict, description="Map of file paths to metadata"
    )
    index_last_modified: datetime = Field(
        ..., description="When index was last updated"
    )


class HealthResponse(BaseModel):
    """Response model for GET /health endpoint."""

    status: str = Field(..., description="Health status")
    storage: str = Field(..., description="Storage connectivity status")


class ErrorResponse(BaseModel):
    """Standard error response format."""

    detail: str = Field(..., description="Human-readable error message")
    error_code: str | None = Field(
        default=None, description="Machine-readable error code"
    )
    context: Dict[str, str] | None = Field(
        default=None, description="Additional error context"
    )


class PreconditionFailedResponse(ErrorResponse):
    """Response for 412 Precondition Failed errors."""

    error_code: str = "PRECONDITION_FAILED"
    context: Dict[str, str] = Field(
        ..., description="Context with current_md5 and provided_md5"
    )
