"""Test basic setup and configuration."""

import tempfile
from pathlib import Path
from sqlalchemy import text

from silica.cron.config.settings import Settings
from silica.cron.models import Base
from silica.cron.models.prompt import Prompt


def test_settings_configuration():
    """Test that settings work with defaults."""
    settings = Settings(environment="test")
    assert settings.environment == "test"
    assert settings.database_name == "silica-cron"
    # Database path should NOT contain environment (consistent across environments)
    assert str(settings.database_path) == "data/silica-cron.db"
    # But S3 path SHOULD contain environment
    assert settings.s3_replica_path == "test/silica-cron"


def test_database_creation():
    """Test database creation and basic operations."""
    # Create temporary database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
        temp_path = Path(tmp_db.name)

    try:
        # Override settings for test
        Settings(
            environment="test", data_dir=temp_path.parent, database_name=temp_path.stem
        )

        # Create engine for test database
        from sqlalchemy import create_engine

        test_engine = create_engine(
            f"sqlite:///{temp_path}", connect_args={"check_same_thread": False}
        )

        # Create tables
        Base.metadata.create_all(bind=test_engine)

        # Test basic insert
        with test_engine.connect() as conn:
            # Verify tables exist
            result = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
            tables = [row[0] for row in result]

            expected_tables = ["prompts", "scheduled_jobs", "job_executions"]
            for table in expected_tables:
                assert table in tables, f"Table {table} not found"

        # Test model creation with heare.ids
        from sqlalchemy.orm import sessionmaker
        from heare import ids

        SessionLocal = sessionmaker(bind=test_engine)

        with SessionLocal() as session:
            prompt = Prompt(
                name="Test Prompt",
                description="A test prompt",
                prompt_text="Hello world",
            )
            session.add(prompt)
            session.commit()

            # Verify heare.id was generated
            assert prompt.id is not None
            assert len(prompt.id) > 0
            assert isinstance(prompt.id, str)
            assert prompt.id.startswith("prompt_")
            assert ids.is_valid(prompt.id)

            # Parse the heare.id
            parsed = ids.parse(prompt.id)
            assert parsed.prefix == "prompt"
            assert parsed.generation == "0"

            # Verify we can query it back
            found = session.query(Prompt).filter_by(name="Test Prompt").first()
            assert found is not None
            assert found.id == prompt.id

    finally:
        # Cleanup
        if temp_path.exists():
            temp_path.unlink()


def test_litestream_config_generation():
    """Test Litestream configuration generation."""
    from silica.cron.scripts.litestream_manager import LitestreamManager

    # This will use default settings
    manager = LitestreamManager()

    try:
        config_path = manager.create_config_file()
        assert config_path.exists()

        # Read and verify content
        with open(config_path, "r") as f:
            content = f.read()

        # Should have substituted variables
        assert "${DATABASE_PATH}" not in content
        assert "${S3_BUCKET}" not in content
        assert "silica-cron-ls" in content  # Default bucket name

    finally:
        if config_path.exists():
            config_path.unlink()
