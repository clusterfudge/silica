# Migration Troubleshooting Guide

## Quick Diagnosis

### Is your database working?
```bash
silica cron migrate status
```

**✅ "Cron database is up to date"** → You're good to go!  
**⚠️ "Cron database needs migration"** → Run `silica cron migrate upgrade`  
**❌ Error message** → See [Common Errors](#common-errors) below

## Decision Tree

### After `git pull` - New Migrations Available

```
git pull origin main
↓
silica cron migrate status
↓
⚠️ "needs migration" → silica cron migrate upgrade → ✅ Ready to develop
↓
❌ Error → See error-specific solutions below
```

### After Making Model Changes

```
Edit models in silica/cron/models/
↓
silica cron migrate create "describe change"
↓
Review generated migration file
↓
silica cron migrate upgrade
↓
Test: silica cron --bind-port 8080
```

### Before Pushing Changes

```
Test locally:
silica cron migrate downgrade -1  (test rollback)
silica cron migrate upgrade       (test re-apply)
↓
Commit migration files with code changes
↓
git push origin feature-branch
```

## Common Errors

### "database is locked"

**Cause**: Another process is using the database file, or permissions issue

**Solutions**:
```bash
# Check if silica is running
ps aux | grep silica
kill <process_id>  # if found

# Fix permissions
chmod 666 silica-cron.db

# If still locked, rebuild
rm silica-cron.db
silica cron migrate rebuild
```

### "table already exists"

**Cause**: Database and migrations are out of sync

**Diagnostic**:
```bash
# Check what's in database
sqlite3 silica-cron.db ".tables"

# Check what migration thinks should happen  
silica cron migrate current
silica cron migrate history
```

**Solutions**:

**Option 1 - Nuclear (destroys data)**:
```bash
silica cron migrate rebuild
```

**Option 2 - Manual fix**:
```bash
# Drop the problematic table manually
sqlite3 silica-cron.db "DROP TABLE table_name;"
silica cron migrate upgrade
```

**Option 3 - Skip migration**:
```bash
# If table is correct, mark migration as applied
# (Advanced - edit alembic version table)
```

### "column already exists"

**Similar to table exists**

**Quick fix**:
```bash
# Check current schema
sqlite3 silica-cron.db ".schema table_name"

# If column looks correct, rebuild to sync:
silica cron migrate rebuild
```

### Migration creates wrong SQL

**Cause**: Alembic auto-generated incorrect migration

**Solution**:
```bash
# Check the generated migration file
cat silica/cron/alembic/versions/latest_migration.py

# Edit the migration manually:
# Fix the upgrade() and downgrade() functions

# Test the corrected migration
silica cron migrate upgrade
```

### Can't rollback (SQLite limitations)

**Cause**: SQLite can't drop columns directly

**Solution**: Edit migration for table recreation
```python
def downgrade() -> None:
    # Instead of: op.drop_column('prompts', 'priority')
    
    # Create new table without the column
    op.rename_table('prompts', 'prompts_old')
    op.create_table('prompts',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        # ... other columns except 'priority'
    )
    
    # Copy data
    op.execute("""
        INSERT INTO prompts (id, name, ...)
        SELECT id, name, ... FROM prompts_old
    """)
    
    # Drop old table
    op.drop_table('prompts_old')
```

### Multiple migration branches

**Cause**: Two developers created migrations from same parent

**Symptom**:
```
Branch A: migration_001 -> migration_002a
Branch B: migration_001 -> migration_002b
```

**Solution**:
```bash
# Option 1: Reorder migrations
# Edit migration_002b file:
# Change: down_revision = 'migration_001'
# To:     down_revision = 'migration_002a'

# Option 2: Create merge migration
silica cron migrate create "merge branches"
# Edit to reference both parents in down_revision
```

### App won't start after migration

**Diagnostic steps**:
```bash
# 1. Check migration applied correctly
silica cron migrate current
silica cron migrate status

# 2. Check database schema matches models
sqlite3 silica-cron.db ".schema"

# 3. Check for Python errors
python -c "from silica.cron.models import Prompt; print('Models load OK')"

# 4. Try starting with more verbose output
PYTHONPATH=. python -m silica.cron.app
```

**Common fixes**:
- Import errors in `__init__.py` after adding new models
- Model field doesn't match database column
- Missing relationship definitions

## Environment-Specific Issues

### Development vs Production Mismatch

**Problem**: Works in dev, fails in production

**Cause**: Different database types (SQLite vs PostgreSQL)

**Solution**:
```bash
# Test with PostgreSQL locally (if available)
export DATABASE_URL="postgresql://user:pass@localhost/test_db"
silica cron migrate rebuild

# OR test migration SQL without applying
PYTHONPATH=. alembic -c silica/cron/alembic.ini upgrade head --sql
```

### Test Environment Issues

**Problem**: Tests interfere with development database

**Check**: Tests should use in-memory database
```bash
# This should show in-memory URL during tests
PYTEST_CURRENT_TEST=1 python -c "
from silica.cron.migration import CronMigrationManager
print(CronMigrationManager().get_database_url())
"
# Should output: sqlite:///:memory:
```

## Recovery Procedures

### Complete Reset (Nuclear Option)

**⚠️ WARNING: Destroys all data**

```bash
# 1. Backup any important data first
sqlite3 silica-cron.db ".dump" > backup.sql

# 2. Reset everything
rm silica-cron.db
git checkout HEAD -- silica/cron/models/  # Reset models if needed
silica cron migrate rebuild

# 3. Restore data if possible
sqlite3 silica-cron.db < backup.sql  # May need manual fixing
```

### Partial Reset (Safer)

```bash
# 1. Rollback to known good state
silica cron migrate downgrade <good_revision>

# 2. Remove problematic migration files
rm silica/cron/alembic/versions/problematic_migration.py

# 3. Recreate migration correctly
# Edit models as needed
silica cron migrate create "fixed version of change"

# 4. Apply and test
silica cron migrate upgrade
```

### Migration File Corruption

```bash
# 1. Check migration file syntax
python -m py_compile silica/cron/alembic/versions/migration_file.py

# 2. If corrupted, restore from git
git checkout HEAD -- silica/cron/alembic/versions/migration_file.py

# 3. If that doesn't work, recreate migration
rm silica/cron/alembic/versions/problematic_file.py
# Edit models to desired state
silica cron migrate create "recreate migration"
```

## Prevention Tips

### Before Making Changes
```bash
# Always start from clean state
silica cron migrate status  # Should be "up to date"
git status                  # Should be clean
```

### After Making Changes
```bash
# Test the full cycle
silica cron migrate upgrade      # Apply changes
silica cron --bind-port 8080    # Test app works
silica cron migrate downgrade -1 # Test rollback
silica cron migrate upgrade      # Test re-apply
```

### Before Pushing
```bash
# Ensure migration chain is clean
silica cron migrate history     # Check for conflicts
silica cron migrate rebuild     # Test full chain

# Test in fresh environment
git stash
git checkout main
git checkout stash -- .
# Test migration applies to main branch
```

### Team Coordination
- **Communicate**: Tell team about schema changes
- **Small Changes**: Keep migrations focused and small
- **Test Thoroughly**: Test both upgrade and downgrade paths
- **Document**: Use clear migration names and comments

## Getting Help

### Self-Service Debugging
1. **Check migration status**: `silica cron migrate status`
2. **Inspect database**: `sqlite3 silica-cron.db ".schema"`
3. **Review recent changes**: `git log --oneline silica/cron/`
4. **Check migration files**: `ls -la silica/cron/alembic/versions/`

### When to Ask for Help
- Multiple attempts at fixes haven't worked
- Production database is affected
- Data loss has occurred
- Migration conflicts across multiple branches

### What to Include When Asking for Help
```bash
# Collect this information:
silica cron migrate status
silica cron migrate current  
silica cron migrate history
git log --oneline -10 silica/cron/
ls -la silica/cron/alembic/versions/ | tail -5
sqlite3 silica-cron.db ".schema" | head -20
```

## Advanced Recovery

### Manual Database Repair

If you need to manually fix the database state:

```sql
-- Connect to database
sqlite3 silica-cron.db

-- Check current migration version
SELECT * FROM cron_alembic_version;

-- Manually set migration version (use carefully!)
UPDATE cron_alembic_version SET version_num = 'desired_revision';

-- Add missing columns manually
ALTER TABLE prompts ADD COLUMN priority INTEGER DEFAULT 1;

-- Exit
.quit
```

### Migration File Surgery

Sometimes you need to edit migration files:

```python
# Common patterns to fix in migration files:

# 1. Add missing imports
from sqlalchemy.dialects import postgresql

# 2. Fix column definitions
# Before: sa.Column('field', sa.String(length=50))
# After:  sa.Column('field', sa.String(50))

# 3. Add batch operations for complex changes
def upgrade():
    with op.batch_alter_table('table_name') as batch_op:
        batch_op.add_column(sa.Column('new_field', sa.Integer()))
        
# 4. Fix relationship issues
# Ensure foreign key constraints are handled properly
```

This troubleshooting guide should help you resolve most common migration issues. The key is to understand what state your database is in and what state it should be in, then find the safest path between them.