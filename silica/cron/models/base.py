"""Database configuration and base model with smart migration detection."""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def get_database_url() -> str:
    """Get database URL with proper defaults.

    Uses file-based SQLite for development to support proper migration workflow.
    Only tests use in-memory SQLite for isolation.
    """
    # For tests only, use in-memory SQLite if no explicit URL
    if os.getenv("PYTEST_CURRENT_TEST"):
        return os.getenv("DATABASE_URL", "sqlite:///:memory:")

    # Priority: environment variable, then config, then default
    url = os.getenv("DATABASE_URL")
    if url:
        return url

    url = os.getenv("CRON_DATABASE_URL")
    if url:
        return url

    # Default to file-based SQLite for development
    # This supports proper migration workflow:
    # - Developers can rebuild: rm silica-cron.db && silica cron migrate upgrade
    # - Schema changes are auto-detected by Alembic
    # - Migration rollbacks work with real database state
    # - Database can be inspected with sqlite3 CLI tools
    return "sqlite:///./silica-cron.db"


# Database configuration with fallbacks
DATABASE_URL = get_database_url()

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_database_ready() -> bool:
    """Ensure database is ready for use.

    Development: Warns if migrations needed, falls back to create_all
    Production: Automatically applies migrations

    Returns:
        bool: True if database is ready, False if setup failed
    """
    try:
        from ..migration import CronMigrationManager

        manager = CronMigrationManager()

        # Try smart migration first
        if manager.auto_migrate_if_needed():
            return True

        # Fallback: basic table creation for development
        if manager.is_development:
            print("⚠️  Falling back to basic table creation for development")
            print("   Consider running migrations for full database features")
            Base.metadata.create_all(bind=engine)
            return True

        # Production fallback failed
        return False

    except Exception as e:
        print(f"Error setting up database: {e}")

        # Last resort fallback
        try:
            Base.metadata.create_all(bind=engine)
            print("⚠️  Used basic table creation as fallback")
            return True
        except Exception as fallback_error:
            print(f"Database setup failed completely: {fallback_error}")
            return False


def init_database():
    """Initialize database with current schema.

    This creates tables if they don't exist, but doesn't handle migrations.
    Use `silica cron migrate upgrade` for proper migration management.
    """
    Base.metadata.create_all(bind=engine)
