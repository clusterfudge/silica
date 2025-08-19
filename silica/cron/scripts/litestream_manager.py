"""Litestream management utilities."""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from ..config import get_settings


class LitestreamManager:
    """Manages Litestream operations."""

    def __init__(self):
        self.settings = get_settings()

    def create_config_file(self) -> Path:
        """Create a Litestream config file with environment variables substituted."""
        # Read template
        config_template_path = Path("config/litestream.yml")
        if not config_template_path.exists():
            raise FileNotFoundError(
                f"Litestream config template not found: {config_template_path}"
            )

        with open(config_template_path, "r") as f:
            config_content = f.read()

        # Substitute environment variables
        config_content = config_content.replace(
            "${DATABASE_PATH}", str(self.settings.database_path)
        )
        config_content = config_content.replace("${S3_BUCKET}", self.settings.s3_bucket)
        config_content = config_content.replace(
            "${S3_REPLICA_PATH}", self.settings.s3_replica_path
        )
        config_content = config_content.replace(
            "${AWS_REGION}", self.settings.aws_region
        )

        # Write to temporary file
        temp_config = (
            Path(tempfile.gettempdir()) / f"litestream-{self.settings.environment}.yml"
        )
        with open(temp_config, "w") as f:
            f.write(config_content)

        return temp_config

    def start_replication(self) -> subprocess.Popen:
        """Start Litestream replication in background."""
        if not self.settings.litestream_enabled:
            raise RuntimeError("Litestream is disabled in settings")

        config_file = self.create_config_file()

        env = os.environ.copy()
        if self.settings.aws_access_key_id:
            env["AWS_ACCESS_KEY_ID"] = self.settings.aws_access_key_id
        if self.settings.aws_secret_access_key:
            env["AWS_SECRET_ACCESS_KEY"] = self.settings.aws_secret_access_key

        # Try local litestream first, then system PATH
        litestream_cmd = (
            "./litestream" if Path("./litestream").exists() else "litestream"
        )
        cmd = [litestream_cmd, "replicate", "-config", str(config_file)]

        return subprocess.Popen(
            cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

    def create_manual_backup(self) -> str:
        """Create a manual backup snapshot."""
        config_file = self.create_config_file()

        env = os.environ.copy()
        if self.settings.aws_access_key_id:
            env["AWS_ACCESS_KEY_ID"] = self.settings.aws_access_key_id
        if self.settings.aws_secret_access_key:
            env["AWS_SECRET_ACCESS_KEY"] = self.settings.aws_secret_access_key

        litestream_cmd = (
            "./litestream" if Path("./litestream").exists() else "litestream"
        )
        cmd = [
            litestream_cmd,
            "snapshots",
            "-config",
            str(config_file),
            str(self.settings.database_path),
        ]

        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Backup failed: {result.stderr}")

        return result.stdout

    def restore_database(self, target_path: Optional[Path] = None) -> Path:
        """Restore database from latest backup."""
        if target_path is None:
            target_path = self.settings.database_path.with_suffix(".restored.db")

        env = os.environ.copy()
        if self.settings.aws_access_key_id:
            env["AWS_ACCESS_KEY_ID"] = self.settings.aws_access_key_id
        if self.settings.aws_secret_access_key:
            env["AWS_SECRET_ACCESS_KEY"] = self.settings.aws_secret_access_key

        s3_url = f"s3://{self.settings.s3_bucket}/{self.settings.s3_replica_path}"

        litestream_cmd = (
            "./litestream" if Path("./litestream").exists() else "litestream"
        )
        cmd = [
            litestream_cmd,
            "restore",
            "-if-replica-exists",
            s3_url,
            str(target_path),
        ]

        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Restore failed: {result.stderr}")

        return target_path

    def health_check(self) -> dict:
        """Check Litestream replication health."""
        try:
            snapshots = self.create_manual_backup()
            return {
                "status": "healthy",
                "last_snapshot": snapshots.strip().split("\n")[-1]
                if snapshots.strip()
                else None,
            }
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}
