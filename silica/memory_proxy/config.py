"""Configuration management for Memory Proxy service."""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # S3 Configuration
    aws_access_key_id: str = Field(..., description="AWS access key ID")
    aws_secret_access_key: str = Field(..., description="AWS secret access key")
    aws_region: str = Field(default="us-east-1", description="AWS region")
    s3_bucket: str = Field(..., description="S3 bucket name")
    s3_prefix: str = Field(
        default="memory", description="S3 key prefix for all objects"
    )
    s3_endpoint_url: str | None = Field(
        default=None, description="Custom S3 endpoint URL (for S3-compatible services)"
    )

    # heare-auth Configuration
    heare_auth_url: str = Field(..., description="heare-auth service URL")

    # Application Configuration
    log_level: str = Field(default="INFO", description="Logging level")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }
