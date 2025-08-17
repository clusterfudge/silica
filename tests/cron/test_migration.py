"""Tests for cron module migration functionality."""

import pytest
import tempfile
import os
from unittest.mock import patch
from sqlalchemy import create_engine

from silica.cron.migration import CronMigrationManager


class TestCronMigrations:
    """Test cron module migration behavior."""

    @pytest.fixture
    def temp_db(self):
        """Temporary database for testing."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        # Set environment variable for test database
        original_url = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

        yield db_path

        # Cleanup
        if original_url:
            os.environ["DATABASE_URL"] = original_url
        else:
            os.environ.pop("DATABASE_URL", None)
        os.unlink(db_path)

    def test_environment_detection(self):
        """Test production vs development environment detection."""
        manager = CronMigrationManager()

        # Test development detection
        with patch.dict(os.environ, {"SILICA_ENVIRONMENT": "development"}, clear=False):
            assert manager.is_development is True
            assert manager.is_production is False

        # Test production detection with Heroku
        with patch.dict(os.environ, {"DYNO": "web.1"}, clear=False):
            assert manager.is_production is True
            assert manager.is_development is False

        # Test production detection with PostgreSQL
        with patch.dict(
            os.environ, {"DATABASE_URL": "postgresql://user:pass@host/db"}, clear=False
        ):
            assert manager.is_production is True

    def test_development_mode_behavior(self, temp_db):
        """Test that development mode requires explicit migration."""
        with patch.dict(os.environ, {"SILICA_ENVIRONMENT": "development"}, clear=False):
            manager = CronMigrationManager()

            # Should not auto-migrate in development
            result = manager.auto_migrate_if_needed()
            assert result is False  # Should warn, not migrate

    def test_production_mode_behavior(self, temp_db):
        """Test that production mode auto-migrates."""
        with patch.dict(os.environ, {"DYNO": "web.1"}, clear=False):  # Simulate Heroku
            manager = CronMigrationManager()

            # Should auto-migrate in production
            result = manager.auto_migrate_if_needed()
            assert result is True  # Should migrate automatically

    def test_migration_detection(self, temp_db):
        """Test migration need detection is accurate."""
        manager = CronMigrationManager()

        # Fresh database should need migration
        assert manager.needs_migration() is True

        # After migration, should not need migration
        manager.upgrade()
        assert manager.needs_migration() is False

    def test_database_url_fallbacks(self):
        """Test database URL resolution with various environment variables."""
        manager = CronMigrationManager()

        # Test DATABASE_URL priority
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://main/db",
                "CRON_DATABASE_URL": "postgresql://cron/db",
            },
            clear=False,
        ):
            assert manager.get_database_url() == "postgresql://main/db"

        # Test CRON_DATABASE_URL fallback
        with patch.dict(
            os.environ, {"CRON_DATABASE_URL": "postgresql://cron/db"}, clear=False
        ):
            if "DATABASE_URL" in os.environ:
                del os.environ["DATABASE_URL"]
            assert manager.get_database_url() == "postgresql://cron/db"

        # Test default fallback
        with patch.dict(os.environ, {}, clear=True):
            assert manager.get_database_url() == "sqlite:///./silica-cron.db"

    def test_schema_matches_models(self, temp_db):
        """Test that migrations produce schema matching models."""
        manager = CronMigrationManager()

        # Apply migrations
        result = manager.upgrade()
        assert result == 0

        # Verify we can create engine and tables exist
        engine = create_engine(f"sqlite:///{temp_db}")
        from sqlalchemy import inspect

        inspector = inspect(engine)

        tables = inspector.get_table_names()
        expected_tables = [
            "prompts",
            "scheduled_jobs",
            "job_executions",
            "cron_alembic_version",
        ]

        for table in expected_tables:
            assert table in tables, f"Table {table} should exist after migration"
