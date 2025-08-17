# Migration FAQ - Frequently Asked Questions

## Getting Started

### Q: I'm new to the project. How do I set up the database?

**A**: Simple 3-step process:
```bash
git clone <repo> && cd silica && uv sync    # Setup environment
silica cron migrate upgrade                 # Apply all migrations  
silica cron                                 # Start development
```

Your database will be created as `silica-cron.db` in the project root.

### Q: What's the difference between `silica-cron.db` and the models?

**A**: 
- **Models** (`silica/cron/models/`) = Python code defining table structure
- **Database** (`silica-cron.db`) = Actual SQLite file with data
- **Migrations** (`silica/cron/alembic/versions/`) = Scripts to evolve database schema

Think of it as: Models = blueprint, Database = house, Migrations = renovation instructions.

### Q: Can I just delete the database file and start over?

**A**: Yes! For development:
```bash
rm silica-cron.db
silica cron migrate upgrade  # Rebuilds from migrations
```

Or use the convenience command:
```bash
silica cron migrate rebuild  # Does the same thing
```

## Daily Development

### Q: I pulled new code and the app won't start. What do I do?

**A**: Probably new migrations to apply:
```bash
silica cron migrate status    # Check if migrations needed
silica cron migrate upgrade   # Apply them
silica cron                   # Should work now
```

### Q: How do I add a new field to an existing table?

**A**: Follow the 3-step process:

**Step 1 - Edit the model**:
```python
# In silica/cron/models/prompt.py
class Prompt(Base):
    # ... existing fields ...
    new_field = Column(Integer, nullable=False, default=0)
```

**Step 2 - Generate migration**:
```bash
silica cron migrate create "add new_field to prompts"
```

**Step 3 - Apply migration**:
```bash
silica cron migrate upgrade
```

### Q: How do I see what's in my database?

**A**: Several ways:
```bash
# Quick table list
sqlite3 silica-cron.db ".tables"

# See table structure  
sqlite3 silica-cron.db ".schema prompts"

# Query data
sqlite3 silica-cron.db "SELECT * FROM prompts;"

# Interactive session
sqlite3 silica-cron.db
# Then use SQL commands like: SELECT * FROM prompts;
```

### Q: How do I check what migrations have been applied?

**A**: Use these status commands:
```bash
silica cron migrate status     # ✅ or ⚠️ status
silica cron migrate current    # Current revision ID  
silica cron migrate history    # Full timeline
```

## Schema Changes

### Q: Can Alembic automatically detect all types of changes?

**A**: Alembic auto-detects:
- ✅ New tables
- ✅ New columns  
- ✅ Column type changes
- ✅ New indexes

Alembic does NOT auto-detect:
- ❌ Column renames (sees as drop + add)
- ❌ Table renames (sees as drop + add) 
- ❌ Data migrations
- ❌ Complex constraint changes

For these, you'll need to manually edit the generated migration.

### Q: How do I rename a column without losing data?

**A**: Edit the generated migration manually:
```python
def upgrade() -> None:
    # Don't drop and recreate - use alter_column
    op.alter_column('prompts', 'old_name', new_column_name='new_name')

def downgrade() -> None:
    op.alter_column('prompts', 'new_name', new_column_name='old_name')
```

### Q: How do I add data during a migration?

**A**: Use `op.execute()` in your migration:
```python
def upgrade() -> None:
    # First, add the column
    op.add_column('prompts', sa.Column('status', sa.String(50)))
    
    # Then, populate it with data
    op.execute("UPDATE prompts SET status = 'active' WHERE status IS NULL")

def downgrade() -> None:
    op.drop_column('prompts', 'status')
```

### Q: My migration is trying to create a table that already exists. What happened?

**A**: Database and migrations are out of sync. Usually happens when:
- Someone created tables manually
- Migration files were deleted/modified incorrectly
- Database was restored from backup

**Solution**: `silica cron migrate rebuild` (loses data) or manually fix the sync issue.

## Rollbacks and Testing

### Q: How do I undo a migration I just applied?

**A**: Use downgrade:
```bash
silica cron migrate downgrade -1  # Go back one migration
```

To go back to a specific migration:
```bash
silica cron migrate history       # Find the revision ID
silica cron migrate downgrade <revision-id>
```

### Q: I can't roll back a migration. It says "can't drop column".

**A**: SQLite limitation. You need to recreate the table in your downgrade:
```python
def downgrade() -> None:
    # Instead of: op.drop_column('prompts', 'priority')
    
    # Recreate table without the column:
    op.rename_table('prompts', 'prompts_old')
    op.create_table('prompts',
        sa.Column('id', sa.Integer, primary_key=True),
        # ... list all columns EXCEPT the one being removed
    )
    op.execute('INSERT INTO prompts SELECT id, name, ... FROM prompts_old')
    op.drop_table('prompts_old')
```

### Q: How do I test that my migration works correctly?

**A**: Test the full cycle:
```bash
# Start from current state
silica cron migrate status  # Should be "up to date"

# Apply your new migration
silica cron migrate upgrade

# Test the app works
silica cron --bind-port 8080

# Test rollback works
silica cron migrate downgrade -1

# Test re-apply works  
silica cron migrate upgrade

# Final app test
silica cron --bind-port 8080
```

## Team Collaboration

### Q: Someone else added a migration. How do I get it?

**A**: Standard git workflow:
```bash
git pull origin main             # Get their changes
silica cron migrate upgrade      # Apply their migrations
```

### Q: We both created migrations from the same starting point. Now what?

**A**: Migration conflict. One of you needs to reorder:

**Check the problem**:
```bash
silica cron migrate history
# You might see two migrations with same parent
```

**Fix it**:
```bash
# Edit one of the migration files
# Change: down_revision = 'abc123'  
# To:     down_revision = 'xyz789'  (the other person's migration)
```

**Test the fix**:
```bash
silica cron migrate rebuild  # Test full chain
```

### Q: Should I commit the migration files?

**A**: **YES!** Always commit migration files with your code changes:
```bash
git add silica/cron/models/          # Your model changes
git add silica/cron/alembic/versions/  # Generated migration
git commit -m "feat: add priority field with migration"
```

## Production and Deployment

### Q: Do migrations run automatically in production?

**A**: Yes! When you deploy:
```bash
git push production main
```

The app will automatically detect it's in production and apply migrations before starting.

### Q: What if a migration fails in production?

**A**: The app won't start, which is safer than running with wrong schema.

**Recovery options**:
1. **Fix the migration** and redeploy
2. **Rollback the deployment** to previous version
3. **Manual intervention** (SSH to server, fix database, restart app)

### Q: How does the system know it's in production?

**A**: It detects production environment through:
- `SILICA_ENVIRONMENT=production`
- Platform variables (`DYNO`, `PIKU_APP_NAME`, etc.)
- PostgreSQL database URLs
- Cloud platform indicators

### Q: Can I run migrations manually in production?

**A**: Yes, if needed:
```bash
# SSH to production server
SILICA_ENVIRONMENT=production silica cron migrate upgrade
```

## Troubleshooting

### Q: I get "database is locked" error. What do I do?

**A**: Usually means another process is using the database:
```bash
# Check if silica is running
ps aux | grep silica
kill <process_id>  # if needed

# Fix permissions if needed
chmod 666 silica-cron.db

# Last resort - rebuild
rm silica-cron.db && silica cron migrate rebuild
```

### Q: The app is trying to create tables that already exist.

**A**: Database and migration tracking are out of sync:
```bash
# Quick fix (loses data):
silica cron migrate rebuild

# Or diagnose and fix manually:
sqlite3 silica-cron.db "SELECT * FROM cron_alembic_version;"
silica cron migrate history
# Figure out why they don't match
```

### Q: I accidentally deleted a migration file. Now what?

**A**: If it hasn't been applied:
```bash
# Just recreate it
silica cron migrate create "recreate the migration"
```

If it was already applied:
```bash
# Check git history
git log --oneline silica/cron/alembic/versions/
git checkout <commit> -- path/to/deleted/migration.py

# Or manually edit the alembic version table (advanced)
```

### Q: My models and database are completely out of sync. Help!

**A**: Nuclear option:
```bash
# 1. Backup any important data
sqlite3 silica-cron.db ".dump" > backup.sql

# 2. Reset everything  
rm silica-cron.db
silica cron migrate rebuild

# 3. Your models now match the database exactly
```

## Advanced Usage

### Q: How do I create a migration with custom SQL?

**A**: Use `op.execute()`:
```python
def upgrade() -> None:
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_prompts_fulltext 
        ON prompts USING gin(to_tsvector('english', prompt_text))
    """)

def downgrade() -> None:
    op.execute("DROP INDEX ix_prompts_fulltext")
```

### Q: How do I seed the database with initial data?

**A**: Create a data migration:
```bash
silica cron migrate create "add initial data"
```

Then edit the migration:
```python
def upgrade() -> None:
    # Insert default data
    op.execute("""
        INSERT INTO prompts (name, prompt_text, model, persona) VALUES
        ('Default Prompt', 'Hello world', 'haiku', 'basic_agent')
    """)

def downgrade() -> None:
    op.execute("DELETE FROM prompts WHERE name = 'Default Prompt'")
```

### Q: Can I have multiple databases?

**A**: The current setup uses one database per module. To use multiple:
```bash
export CRON_DATABASE_URL="sqlite:///./special-cron.db"
silica cron migrate upgrade  # Will use the special database
```

### Q: How do I change from SQLite to PostgreSQL?

**A**: 
```bash
# 1. Set up PostgreSQL database
export DATABASE_URL="postgresql://user:pass@localhost/mydb"

# 2. Run all migrations on the new database
silica cron migrate upgrade

# Your app will now use PostgreSQL
```

## Performance and Best Practices  

### Q: My migration is taking forever. How do I speed it up?

**A**: For large datasets:
- Add indexes AFTER bulk data changes
- Use batch operations
- Consider breaking into smaller migrations
- Test migration time: `time silica cron migrate upgrade`

### Q: What's the best way to name migrations?

**A**: Be descriptive and specific:
- ✅ `"add priority field to prompts"`
- ✅ `"create job_templates table"`  
- ✅ `"add index on prompts.created_at"`
- ❌ `"database changes"`
- ❌ `"update schema"`
- ❌ `"fixes"`

### Q: How often should I create migrations?

**A**: 
- **Per logical change**: One migration per feature/bug fix
- **Before pushing**: Always have migrations with your code changes
- **Keep them small**: Easier to review and rollback
- **Test thoroughly**: Both upgrade and downgrade paths

### Q: Any tips for working with migrations in a team?

**A**:
- **Communicate schema changes** before making them
- **Pull before creating migrations** to avoid conflicts  
- **Test migration chains** with `silica cron migrate rebuild`
- **Use descriptive names** so others understand the change
- **Document complex migrations** with code comments

This FAQ covers the most common questions developers have about database migrations. For more detailed information, see the [Migration Guide](database_migration_guide.md) and [Quick Reference](migration_quick_reference.md).