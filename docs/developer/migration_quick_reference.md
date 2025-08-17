# Migration Quick Reference Card

## Daily Commands

### Starting Work
```bash
git pull origin main           # Get latest code
uv sync                        # Update dependencies  
silica cron migrate status     # Check migration status
silica cron migrate upgrade    # Apply any new migrations
silica cron                    # Start development server
```

### Making Schema Changes
```bash
# 1. Edit models in silica/cron/models/
# 2. Generate migration:
silica cron migrate create "describe your change"

# 3. Review generated file in silica/cron/alembic/versions/
# 4. Apply migration:
silica cron migrate upgrade

# 5. Test your changes:
silica cron --bind-port 8080
```

### Database Status
```bash
silica cron migrate status     # ✅ up to date OR ⚠️ needs migration
silica cron migrate current    # Show current revision
silica cron migrate history    # Show all migrations
```

### Database Inspection  
```bash
sqlite3 silica-cron.db ".schema"              # View all tables
sqlite3 silica-cron.db ".schema prompts"      # View specific table  
sqlite3 silica-cron.db "SELECT * FROM prompts;"  # Query data
sqlite3 silica-cron.db                        # Interactive shell
```

## Emergency Commands

### Database Problems
```bash
# Corrupted database:
silica cron migrate rebuild    # ⚠️ DESTROYS DATA - rebuilds from migrations

# Migration conflicts after git pull:
git log --oneline silica/cron/alembic/versions/  # Check recent migrations
silica cron migrate rebuild                      # Nuclear option
```

### Undo Changes
```bash
silica cron migrate downgrade fc0bfa77ff5a  # Rollback to specific revision
silica cron migrate downgrade -1            # Rollback one step
silica cron migrate downgrade base          # Rollback everything
silica cron migrate upgrade                 # Re-apply migrations
```

## Command Reference

| Command | Purpose | Example |
|---------|---------|---------|
| `status` | Check if migrations needed | `silica cron migrate status` |
| `create` | Generate new migration | `silica cron migrate create "add priority field"` |
| `upgrade` | Apply migrations | `silica cron migrate upgrade` |
| `downgrade` | Rollback migrations | `silica cron migrate downgrade -1` |
| `current` | Show current revision | `silica cron migrate current` |
| `history` | Show migration timeline | `silica cron migrate history` |
| `rebuild` | Rebuild from scratch | `silica cron migrate rebuild` |

## Environment Files

| File | Purpose |
|------|---------|
| `silica-cron.db` | Development SQLite database |
| `silica/cron/models/` | SQLAlchemy model definitions |
| `silica/cron/alembic/versions/` | Migration scripts |
| `silica/cron/alembic.ini` | Alembic configuration |

## Common Patterns

### Adding Column
```python
# In model file:
new_field = Column(Integer, nullable=False, default=0)
```
```bash
silica cron migrate create "add new_field to table"
silica cron migrate upgrade
```

### Renaming Column  
```python
# In migration file (manual edit):
def upgrade():
    op.alter_column('table_name', 'old_name', new_column_name='new_name')
```

### Adding Table
```python
# Create new model class in silica/cron/models/
# Update __init__.py imports
```
```bash
silica cron migrate create "add new_table"
silica cron migrate upgrade
```

## Error Recovery

| Error | Solution |
|-------|----------|
| "database is locked" | `chmod 666 silica-cron.db` |
| "table already exists" | `silica cron migrate rebuild` |
| Migration conflicts | Edit migration files, fix `down_revision` |
| "can't rollback" | Use table recreation in downgrade |

## Production Notes

- **Auto-Migration**: Production environments apply migrations automatically on startup
- **No Manual Steps**: Just `git push production main` 
- **Rollback Planning**: Test rollbacks in development first
- **Monitoring**: Check application logs for migration status

## Getting Help

1. **Check status**: `silica cron migrate status`
2. **View database**: `sqlite3 silica-cron.db ".schema"`
3. **Check migrations**: `ls -la silica/cron/alembic/versions/`
4. **Nuclear option**: `silica cron migrate rebuild` (⚠️ destroys data)
5. **Documentation**: `docs/developer/database_migration_guide.md`