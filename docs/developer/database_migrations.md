# Database Migrations with Alembic

## Overview

Silica uses Alembic for database schema migrations, providing professional database management with proper versioning, rollback capabilities, and environment-aware behavior.

## Architecture

### Module-Namespaced Migrations
Each Silica module manages its own database migrations independently:
- **Cron Module**: `silica/cron/alembic/` with `cron_alembic_version` table
- **Future Modules**: Each gets its own migration namespace to avoid conflicts

### Environment Detection
- **Development (Default)**: Explicit migration control, file-based SQLite
- **Production (Explicit)**: Auto-migration at startup, PostgreSQL/explicit config  
- **Testing**: Isolated in-memory SQLite via `PYTEST_CURRENT_TEST`

## Development Workflow

### Initial Setup
```bash
# Clone repository and set up environment
git clone <repo>
cd <repo>
uv sync

# Check migration status
silica cron migrate status
# → ℹ️ cron database needs migration
# → Run: silica cron migrate upgrade

# Apply all migrations to get current schema
silica cron migrate upgrade
# → ✅ cron migrations applied successfully

# Verify database is ready
silica cron migrate status  
# → ✅ Cron database is up to date
```

### Making Schema Changes

#### 1. Modify Models
Edit the SQLAlchemy models in `silica/cron/models/`:
```python
# silica/cron/models/prompt.py
class Prompt(Base):
    # ... existing fields ...
    
    # Add new field
    priority = Column(Integer, nullable=False, default=1)
```

#### 2. Generate Migration
```bash
# Auto-generate migration from model changes
silica cron migrate create "add priority field to prompts"
# → ✅ Migration created successfully
# → Review the generated migration file before applying
```

#### 3. Review Generated Migration
Check the generated file in `silica/cron/alembic/versions/`:
```python
def upgrade() -> None:
    op.add_column('prompts', sa.Column('priority', sa.Integer(), nullable=False))

def downgrade() -> None:
    op.drop_column('prompts', 'priority')
```

#### 4. Apply Migration
```bash
# Apply the new migration
silica cron migrate upgrade
# → INFO [alembic.runtime.migration] Running upgrade ... -> ..., add priority field to prompts
```

### Database Inspection
```bash
# View current migration status
silica cron migrate current
# → 34065a4cc718 (head)

# View migration history  
silica cron migrate history
# → fc0bfa77ff5a -> 34065a4cc718 (head), add priority field to prompts
# → 5d8b746712b6 -> fc0bfa77ff5a, add new feature
# → <base> -> 5d8b746712b6, initial_cron_schema

# Inspect database directly (SQLite)
sqlite3 silica-cron.db ".schema prompts"
sqlite3 silica-cron.db "SELECT * FROM cron_alembic_version;"
```

### Migration Rollbacks
```bash
# Rollback to previous migration
silica cron migrate downgrade fc0bfa77ff5a
# → INFO [alembic.runtime.migration] Running downgrade ..., add priority field to prompts

# Rollback multiple steps
silica cron migrate downgrade base  # Back to beginning
```

### Database Rebuild
```bash
# Completely rebuild database from migrations (DESTRUCTIVE)
silica cron migrate rebuild
# → 🗑️ Removed existing database: silica-cron.db  
# → 🔄 Rebuilding database from migrations...
# → ✅ Database rebuilt successfully from migrations
```

## Available Commands

### Core Migration Commands
```bash
silica cron migrate create "description"    # Create new migration
silica cron migrate upgrade                 # Apply pending migrations
silica cron migrate downgrade <revision>    # Rollback to revision
silica cron migrate current                 # Show current revision
silica cron migrate history                 # Show migration history
```

### Utility Commands  
```bash
silica cron migrate status                  # Check migration status
silica cron migrate init                    # Initialize migration tracking
silica cron migrate rebuild                 # Rebuild database from scratch (dev only)
```

## Database URLs

### Priority Order
1. **Tests**: `PYTEST_CURRENT_TEST` → `sqlite:///:memory:`
2. **Explicit**: `DATABASE_URL` environment variable  
3. **Module-specific**: `CRON_DATABASE_URL` environment variable
4. **Development default**: `sqlite:///./silica-cron.db`

### Configuration Examples
```bash
# Development (default)
# Uses: sqlite:///./silica-cron.db

# Custom development database
export CRON_DATABASE_URL="sqlite:///./my-dev-db.db"

# Production PostgreSQL
export DATABASE_URL="postgresql://user:pass@host:5432/database"

# Explicit production mode
export SILICA_ENVIRONMENT=production
```

## Production Behavior

### Automatic Migration
Production environments automatically apply migrations at application startup:
```bash
# Deploy to production
git push production main

# Application startup log:
# 🚀 Production detected: auto-applying cron migrations...
# INFO [alembic.runtime.migration] Running upgrade ...
# ✅ cron migrations applied successfully
# INFO: Application startup complete
```

### Production Detection
Production is detected by:
- `SILICA_ENVIRONMENT=production`
- Platform variables (`DYNO`, `PIKU_APP_NAME`, `DOKKU_APP_NAME`)
- PostgreSQL database URLs (`postgres://`, `postgresql://`)
- Cloud platform indicators

## Best Practices

### Migration Creation
- **Descriptive Names**: Use clear, descriptive migration names
- **Review Generated Code**: Always review auto-generated migrations
- **Test Both Directions**: Test both upgrade and downgrade
- **Atomic Changes**: Keep migrations focused on single logical changes

### Development Workflow  
- **Regular Commits**: Commit migration files with related code changes
- **Database Rebuilds**: Use `rebuild` to test full migration chain
- **Branch Coordination**: Coordinate migrations across feature branches

### Production Safety
- **Test in Staging**: Always test migrations in staging environment
- **Backup Before Deploy**: Database backups before production deploys
- **Monitoring**: Monitor application startup for migration failures
- **Rollback Plan**: Have rollback procedures for failed migrations

## Troubleshooting

### Common Issues

#### Migration Conflicts
```bash
# If multiple branches create migrations
silica cron migrate history  # Check for conflicts
# Resolve by rebasing or merging migration files
```

#### Database Out of Sync
```bash
# If database schema doesn't match migrations
silica cron migrate rebuild  # Nuclear option: rebuild from migrations
# OR manually fix database and stamp current revision
```

#### Production Migration Failures
```bash
# Check application logs for migration errors
# Use explicit migration commands if auto-migration fails
SILICA_ENVIRONMENT=production silica cron migrate upgrade
```

## Integration with CI/CD

### GitHub Actions Example
```yaml
- name: Test Migrations  
  run: |
    uv run silica cron migrate upgrade
    uv run silica cron migrate downgrade base
    uv run silica cron migrate upgrade
```

### Docker Integration
```dockerfile
# Migrations happen at runtime, not build time
CMD ["uv", "run", "silica", "cron"]
```

This migration system provides professional database management while maintaining the simplicity needed for rapid development and reliable deployments.