"""Cron module migration management."""

import os
import subprocess
from pathlib import Path
from typing import Optional

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect


class CronMigrationManager:
    """Smart migration manager with environment-aware behavior."""

    def __init__(self):
        self.module_name = "cron"
        self.cron_dir = Path(__file__).parent
        self.alembic_cfg_path = self.cron_dir / "alembic.ini"
        self.version_table = "cron_alembic_version"

    @property
    def is_production(self) -> bool:
        """Detect if running in production environment.

        Production must be explicitly indicated - we default to development for safety.
        """
        return any(
            [
                # Explicit production setting (most reliable)
                os.getenv("SILICA_ENVIRONMENT") == "production",
                # Common production platform indicators
                os.getenv("DYNO"),  # Heroku
                os.getenv("PIKU_APP_NAME"),  # Piku
                os.getenv("DOKKU_APP_NAME"),  # Dokku
                os.getenv("FLY_APP_NAME"),  # Fly.io
                os.getenv("RAILWAY_ENVIRONMENT"),  # Railway
                # Production database indicators (PostgreSQL = likely production)
                os.getenv("DATABASE_URL", "").startswith(
                    ("postgres://", "postgresql://")
                ),
                # Container/cloud indicators (be conservative)
                os.getenv("AWS_EXECUTION_ENV")
                and not os.getenv("AWS_SAM_LOCAL"),  # AWS but not local SAM
                os.getenv("GOOGLE_CLOUD_PROJECT")
                and os.getenv("GAE_APPLICATION"),  # Google Cloud App Engine
            ]
        )

    @property
    def is_development(self) -> bool:
        """Detect if running in development environment.

        Development is the default - safer to assume dev than prod.
        """
        # Default to development unless clearly in production
        return not self.is_production

    def get_database_url(self) -> str:
        """Get database URL with fallbacks.

        Uses file-based SQLite for development to support proper migration workflow.
        Only tests use in-memory SQLite for isolation.
        """
        # For tests only, use in-memory SQLite if no explicit URL
        if os.getenv("PYTEST_CURRENT_TEST"):
            return os.getenv("DATABASE_URL", "sqlite:///:memory:")

        # Priority order for all other environments (dev/prod)
        url = os.getenv("DATABASE_URL")
        if url:
            return url

        url = os.getenv("CRON_DATABASE_URL")
        if url:
            return url

        # Default to file-based SQLite for development
        # This allows proper migration workflow:
        # - Developers can rebuild: rm silica-cron.db && silica cron migrate upgrade
        # - Schema changes are auto-detected by Alembic
        # - Migration rollbacks work properly with real database state
        # - Developers can inspect database contents with sqlite3 CLI
        return "sqlite:///./silica-cron.db"

    def _get_engine(self):
        """Get SQLAlchemy engine for database operations."""
        database_url = self.get_database_url()
        connect_args = {}
        if database_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False

        return create_engine(database_url, connect_args=connect_args)

    def _get_alembic_config(self) -> Config:
        """Get Alembic configuration."""
        config = Config(str(self.alembic_cfg_path))
        config.set_main_option("sqlalchemy.url", self.get_database_url())
        return config

    def _get_current_revision(self, connection) -> Optional[str]:
        """Get current database revision."""
        try:
            from sqlalchemy import text

            result = connection.execute(
                text(f"SELECT version_num FROM {self.version_table} LIMIT 1")
            )
            row = result.fetchone()
            return row[0] if row else None
        except Exception:
            return None

    def needs_migration(self) -> bool:
        """Check if migrations need to be applied."""
        try:
            # Get current database revision
            engine = self._get_engine()
            with engine.connect() as connection:
                inspector = inspect(connection)
                if self.version_table not in inspector.get_table_names():
                    # No version table = needs initial migration
                    return True

                # Check current vs head revision
                config = self._get_alembic_config()
                script_dir = ScriptDirectory.from_config(config)
                head_revision = script_dir.get_current_head()

                current_revision = self._get_current_revision(connection)

                return current_revision != head_revision

        except Exception as e:
            print(f"Warning: Could not check migration status: {e}")
            return True  # Assume migration needed if we can't check

    def auto_migrate_if_needed(self) -> bool:
        """Automatically apply migrations if in production and needed."""
        if not self.is_production:
            if self.needs_migration():
                print(f"ℹ️  {self.module_name} database needs migration.")
                print("   Run: silica cron migrate upgrade")
                return False  # Don't auto-migrate in development
            return True

        # Production: auto-migrate if needed
        if self.needs_migration():
            print(
                f"🚀 Production detected: auto-applying {self.module_name} migrations..."
            )
            result = self.upgrade()
            if result == 0:
                print(f"✅ {self.module_name} migrations applied successfully")
                return True
            else:
                print(f"❌ {self.module_name} migration failed")
                return False

        print(f"✅ {self.module_name} database is up to date")
        return True

    def _run_alembic(self, command_args: list[str]) -> int:
        """Run alembic command with proper configuration."""
        cmd = ["alembic", "-c", str(self.alembic_cfg_path)] + command_args

        # Change to project root for consistent path resolution
        original_cwd = os.getcwd()
        try:
            # Change to the directory containing pyproject.toml
            project_root = self.cron_dir.parent.parent
            os.chdir(project_root)

            result = subprocess.run(cmd, capture_output=False)
            return result.returncode

        finally:
            os.chdir(original_cwd)

    def init(self) -> int:
        """Initialize cron migrations (stamp with head revision)."""
        print("Initializing cron module migrations...")
        return self._run_alembic(["stamp", "head"])

    def create(self, message: str) -> int:
        """Create a new cron migration."""
        print(f"Creating cron migration: {message}")
        return self._run_alembic(["revision", "--autogenerate", "-m", message])

    def upgrade(self, revision: str = "head") -> int:
        """Apply cron migrations."""
        print(f"Upgrading cron database to {revision}...")
        return self._run_alembic(["upgrade", revision])

    def downgrade(self, revision: str) -> int:
        """Rollback cron migrations."""
        print(f"Downgrading cron database to {revision}...")
        return self._run_alembic(["downgrade", revision])

    def current(self) -> int:
        """Show current cron migration."""
        return self._run_alembic(["current"])

    def history(self) -> int:
        """Show cron migration history."""
        return self._run_alembic(["history"])

    def show(self, revision: str) -> int:
        """Show specific cron migration."""
        return self._run_alembic(["show", revision])


# Convenience functions for use in other modules
def init_cron_migrations() -> int:
    """Initialize cron migrations."""
    return CronMigrationManager().init()


def upgrade_cron_database(revision: str = "head") -> int:
    """Upgrade cron database."""
    return CronMigrationManager().upgrade(revision)


def create_cron_migration(message: str) -> int:
    """Create new cron migration."""
    return CronMigrationManager().create(message)


def get_development_hints() -> list[str]:
    """Provide helpful hints for development setup."""
    manager = CronMigrationManager()
    hints = []

    if "sqlite" in manager.get_database_url():
        hints.append("Using SQLite database (development mode)")

    if os.path.exists(".git"):
        hints.append("Git repository detected (development mode)")

    if os.getenv("VIRTUAL_ENV"):
        hints.append("Virtual environment active")

    return hints
