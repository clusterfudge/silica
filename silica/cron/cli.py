"""CLI commands for silica-cron management."""

from pathlib import Path
import cyclopts
from typing import Optional

from .config import get_settings, setup_logging
from .scripts.litestream_manager import LitestreamManager

cron = cyclopts.App(name="cron", help="Silica Cron management commands")


@cron.command
def serve(
    host: Optional[str] = None,
    port: Optional[int] = None,
    debug: Optional[bool] = None,
    enable_litestream: bool = False,
):
    """Start the cron web application."""
    # Setup logging first
    setup_logging()

    from .app import entrypoint

    entrypoint(
        bind_host=host, bind_port=port, debug=debug, enable_litestream=enable_litestream
    )


@cron.command
def backup():
    """Create a manual backup snapshot."""
    manager = LitestreamManager()
    try:
        result = manager.create_manual_backup()
        print("Backup created successfully:")
        print(result)
    except Exception as e:
        print(f"Backup failed: {e}")
        raise SystemExit(1)


@cron.command
def restore(target: Optional[str] = None):
    """Restore database from latest backup."""
    manager = LitestreamManager()
    try:
        target_path = Path(target) if target else None
        restored_path = manager.restore_database(target_path)
        print(f"Database restored to: {restored_path}")
    except Exception as e:
        print(f"Restore failed: {e}")
        raise SystemExit(1)


@cron.command
def status():
    """Show application and backup status."""
    settings = get_settings()
    manager = LitestreamManager()

    print("=== Silica Cron Status ===")
    print(f"Environment: {settings.environment}")
    print(f"Database: {settings.database_path}")
    print(f"Database exists: {settings.database_path.exists()}")

    if settings.litestream_enabled:
        print(f"S3 Bucket: {settings.s3_bucket}")
        print(f"S3 Path: {settings.s3_replica_path}")

        health = manager.health_check()
        print(f"Litestream Status: {health['status']}")
        if health.get("last_snapshot"):
            print(f"Last Snapshot: {health['last_snapshot']}")
        if health.get("error"):
            print(f"Error: {health['error']}")
    else:
        print("Litestream: Disabled")


@cron.command
def init():
    """Initialize the database and configuration."""
    settings = get_settings()

    # Create data directory
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    print(f"Created data directory: {settings.data_dir}")

    # Create database tables
    from .models import init_database

    init_database()
    print(f"Initialized database: {settings.database_path}")

    # Show next steps
    print("\nNext steps:")
    print("1. Run 'silica cron serve' to start the application")
    print("2. Check status with 'silica cron status'")
    if settings.environment == "dev":
        print("3. For backup testing: 'silica cron test-litestream'")
    else:
        print("3. Configure AWS credentials in .env for Litestream")


@cron.command
def test_litestream():
    """Test Litestream configuration and S3 connectivity."""
    settings = get_settings()

    if not settings.aws_access_key_id or not settings.aws_secret_access_key:
        print("❌ AWS credentials not configured")
        print("Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env")
        return

    print("🧪 Testing Litestream configuration...")
    print(f"Environment: {settings.environment}")
    print(f"S3 Bucket: {settings.s3_bucket}")
    print(f"S3 Path: {settings.s3_replica_path}")

    # Temporarily enable Litestream for testing
    original_setting = settings.litestream_enabled
    settings.litestream_enabled = True

    try:
        manager = LitestreamManager()
        health = manager.health_check()

        if health["status"] == "healthy":
            print("✅ Litestream configuration is working!")
            if health.get("last_snapshot"):
                print(f"📸 Last snapshot: {health['last_snapshot']}")
        else:
            print("❌ Litestream test failed:")
            print(f"Error: {health.get('error', 'Unknown error')}")

    finally:
        # Restore original setting
        settings.litestream_enabled = original_setting
