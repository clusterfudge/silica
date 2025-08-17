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
def upgrade():
    """Upgrade cron database to latest migration."""
    manager = CronMigrationManager()
    return manager.upgrade()


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
