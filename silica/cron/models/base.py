"""Database configuration and base model."""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

from ..config import get_settings

# Get settings
settings = get_settings()

# Create engine with Litestream-compatible configuration
engine = create_engine(
    settings.database_url,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,  # 30 second timeout for better concurrency
    },
    pool_pre_ping=True,
    pool_recycle=300,
    echo=settings.debug,
)


# Configure SQLite for optimal Litestream compatibility
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Set SQLite pragmas for Litestream compatibility."""
    if settings.database_url.startswith("sqlite"):
        cursor = dbapi_connection.cursor()
        # Essential for Litestream compatibility
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")  # Faster, still safe with WAL
        cursor.execute("PRAGMA busy_timeout=30000")  # 30 seconds
        cursor.execute(
            "PRAGMA wal_autocheckpoint=0"
        )  # Let Litestream handle checkpoints
        cursor.execute("PRAGMA foreign_keys=ON")  # Enable foreign key constraints
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """Initialize database tables. Call this when cron functionality is needed."""
    import logging

    logger = logging.getLogger(__name__)
    settings = get_settings()
    logger.info(f"Creating database tables at {settings.database_path}")
    Base.metadata.create_all(bind=engine)
