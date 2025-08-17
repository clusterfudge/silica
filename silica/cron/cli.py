"""Cron module CLI commands."""

import cyclopts
from .migration import CronMigrationManager


app = cyclopts.App()


@app.command
def current():
    """Show current migration revision."""
    manager = CronMigrationManager()
    return manager.current()


@app.command
def history():
    """Show migration history."""
    manager = CronMigrationManager()
    return manager.history()


@app.command
def create(message: str):
    """Create a new migration with the given message."""
    manager = CronMigrationManager()
    result = manager.create(message)
    if result == 0:
        print("✅ Migration created successfully")
        print("   Review the generated migration file before applying")
    return result


@app.command
def rebuild():
    """Rebuild database from scratch using migrations (development only).

    This will:
    1. Remove the existing database file
    2. Run all migrations from the beginning

    WARNING: This will destroy all data in the database!
    """
    manager = CronMigrationManager()

    if manager.is_production:
        print("❌ Rebuild command is not available in production")
        print("   Use migration commands for production database changes")
        return 1

    database_url = manager.get_database_url()
    if database_url.startswith("sqlite:///"):
        # Extract database file path
        db_path = database_url.replace("sqlite:///", "")
        if db_path.startswith("./"):
            db_path = db_path[2:]

        # Remove database file if it exists
        import os

        if os.path.exists(db_path):
            os.remove(db_path)
            print(f"🗑️  Removed existing database: {db_path}")
        else:
            print("ℹ️  No existing database found")

        # Run migrations from scratch
        print("🔄 Rebuilding database from migrations...")
        result = manager.upgrade()

        if result == 0:
            print("✅ Database rebuilt successfully from migrations")
            print(f"   Database location: {db_path}")
        else:
            print("❌ Failed to rebuild database")

        return result
    else:
        print("❌ Rebuild only supports SQLite databases")
        print(f"   Current database: {database_url}")
        return 1


@app.command
def upgrade():
    """Upgrade cron database to latest migration."""
    manager = CronMigrationManager()
    return manager.upgrade()


@app.command
def downgrade(revision: str):
    """Downgrade cron database to a previous migration."""
    manager = CronMigrationManager()

    if manager.is_production:
        print("⚠️  Production environment detected")
        print("   Downgrade operations should be done carefully in production")
        print("   Consider the impact on data and dependent systems")

    return manager.downgrade(revision)


@app.command
def status():
    """Quick status check for cron database."""
    manager = CronMigrationManager()
    if manager.needs_migration():
        print("⚠️  Cron database needs migration")
        print("   Run: silica cron migrate upgrade")
        return 1
    else:
        print("✅ Cron database is up to date")
        return 0


@app.command
def init():
    """Initialize cron database migrations."""
    manager = CronMigrationManager()
    return manager.init()
