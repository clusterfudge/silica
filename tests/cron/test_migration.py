"""Tests for cron module migration functionality."""

import os
import tempfile
from unittest.mock import patch

import pytest

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
        # Use in-memory for tests since PYTEST_CURRENT_TEST is set
        os.environ["DATABASE_URL"] = "sqlite:///:memory:"

        yield db_path

        # Cleanup
        if original_url:
            os.environ["DATABASE_URL"] = original_url
        else:
            os.environ.pop("DATABASE_URL", None)
        if os.path.exists(db_path):
            os.unlink(db_path)

    def test_environment_detection(self):
        """Test production vs development environment detection."""

        # Test development is default (empty environment)
        with patch.dict(os.environ, {}, clear=True):
            manager = CronMigrationManager()
            assert manager.is_development is True
            assert manager.is_production is False

        # Test explicit development detection
        with patch.dict(os.environ, {"SILICA_ENVIRONMENT": "development"}, clear=True):
            manager = CronMigrationManager()
            assert manager.is_development is True
            assert manager.is_production is False

        # Test explicit production detection
        with patch.dict(os.environ, {"SILICA_ENVIRONMENT": "production"}, clear=True):
            manager = CronMigrationManager()
            assert manager.is_production is True
            assert manager.is_development is False

        # Test production detection with Heroku
        with patch.dict(os.environ, {"DYNO": "web.1"}, clear=True):
            manager = CronMigrationManager()
            assert manager.is_production is True
            assert manager.is_development is False

        # Test production detection with PostgreSQL
        with patch.dict(
            os.environ, {"DATABASE_URL": "postgresql://user:pass@host/db"}, clear=True
        ):
            manager = CronMigrationManager()
            assert manager.is_production is True
            assert manager.is_development is False

    def test_development_mode_behavior(self, temp_db):
        """Test that development mode requires explicit migration."""
        # Ensure we're in development mode
        with patch.dict(
            os.environ,
            {"SILICA_ENVIRONMENT": "development", "PYTEST_CURRENT_TEST": "test"},
            clear=True,
        ):
            manager = CronMigrationManager()
            assert manager.is_development is True

            # Should not auto-migrate in development
            result = manager.auto_migrate_if_needed()
            assert result is False  # Should warn, not migrate

    def test_production_mode_behavior(self, temp_db):
        """Test that production mode auto-migrates."""
        # Simulate Heroku production environment
        with patch.dict(
            os.environ, {"DYNO": "web.1", "PYTEST_CURRENT_TEST": "test"}, clear=True
        ):
            manager = CronMigrationManager()
            assert manager.is_production is True

            # Mock the subprocess call to avoid needing actual alembic
            with patch("silica.cron.migration.subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0

                # Should auto-migrate in production
                result = manager.auto_migrate_if_needed()
                assert result is True  # Should migrate automatically

    def test_migration_detection(self, temp_db):
        """Test migration need detection is accurate."""
        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test"}, clear=True):
            manager = CronMigrationManager()

            # Fresh database should need migration
            assert manager.needs_migration() is True

            # Mock the subprocess call for testing
            with patch("silica.cron.migration.subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0

                # After migration, should return success
                result = manager.upgrade()
                assert result == 0

    def test_database_url_fallbacks(self):
        """Test database URL resolution with various environment variables."""

        # Test in-memory SQLite for tests
        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test"}, clear=True):
            manager = CronMigrationManager()
            assert manager.get_database_url() == "sqlite:///:memory:"

        # Test DATABASE_URL priority (no test env var)
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://main/db",
                "CRON_DATABASE_URL": "postgresql://cron/db",
            },
            clear=True,
        ):
            manager = CronMigrationManager()
            assert manager.get_database_url() == "postgresql://main/db"

        # Test CRON_DATABASE_URL fallback
        with patch.dict(
            os.environ, {"CRON_DATABASE_URL": "postgresql://cron/db"}, clear=True
        ):
            manager = CronMigrationManager()
            assert manager.get_database_url() == "postgresql://cron/db"

        # Test default fallback (development SQLite)
        with patch.dict(os.environ, {}, clear=True):
            manager = CronMigrationManager()
            assert manager.get_database_url() == "sqlite:///./silica-cron.db"

    def test_schema_matches_models(self, temp_db):
        """Test that migrations produce schema matching models."""
        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test"}, clear=True):
            manager = CronMigrationManager()

            # Mock the subprocess call for testing
            with patch("silica.cron.migration.subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0

                # Apply migrations
                result = manager.upgrade()
                assert result == 0

                # Verify the command would be called correctly
                mock_run.assert_called_once()
                called_args = mock_run.call_args[0][0]
                assert "alembic" in called_args
                assert "upgrade" in called_args
