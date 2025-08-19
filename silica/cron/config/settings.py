"""Application settings using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import ConfigDict, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    # Environment
    environment: str = Field(default="dev", description="Environment (dev, prod, etc.)")
    debug: bool = Field(default=False, description="Debug mode")

    # Database
    data_dir: Path = Field(default=Path("./data"), description="Data directory path")
    database_name: str = Field(
        default="silica-cron", description="Database name (without .db)"
    )

    # S3 Configuration for Litestream
    s3_bucket: str = Field(
        default="silica-cron-ls", description="S3 bucket for backups"
    )
    aws_access_key_id: Optional[str] = Field(
        default=None, description="AWS Access Key ID"
    )
    aws_secret_access_key: Optional[str] = Field(
        default=None, description="AWS Secret Access Key"
    )
    aws_region: str = Field(default="us-west-2", description="AWS region")

    # Litestream
    litestream_enabled: bool = Field(
        default=False, description="Enable Litestream replication"
    )
    litestream_config_path: Path = Field(
        default=Path("./config/litestream.yml"),
        description="Litestream configuration file path",
    )

    # Application
    host: str = Field(default="127.0.0.1", description="Host to bind to")
    port: int = Field(default=8080, description="Port to bind to")
    log_level: str = Field(default="info", description="Log level")
    log_to_file: bool = Field(default=True, description="Enable file logging")
    log_dir: Path = Field(default=Path("./logs"), description="Log directory path")

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_path(self) -> Path:
        """Get the full database file path."""
        self.data_dir.mkdir(exist_ok=True, parents=True)
        return self.data_dir / f"{self.database_name}.db"

    @property
    def database_url(self) -> str:
        """Get SQLAlchemy database URL."""
        return f"sqlite:///{self.database_path}"

    @property
    def s3_replica_path(self) -> str:
        """Get S3 path for Litestream replica."""
        return f"{self.environment}/{self.database_name}"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
