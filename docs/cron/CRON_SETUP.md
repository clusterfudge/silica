# Silica Cron Setup Guide

## Overview

Silica Cron provides a web-based interface for scheduling and managing agent prompts with SQLite + Litestream for bulletproof durability.

## Architecture

- **Database**: SQLite with WAL mode for concurrency
- **IDs**: heare-ids for all primary keys
- **Replication**: Litestream for continuous S3 backup
- **Web Interface**: FastAPI with Jinja2 templates
- **Scheduling**: APScheduler with cron expressions

## Quick Start

### 1. Install Dependencies

```bash
# Install with heare-ids support
uv pip install -e .
```

### 2. Configure Environment

Copy `.env.example` to `.env` and configure:

```bash
# Required: Anthropic API Key
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here

# Required: AWS credentials for Litestream
AWS_ACCESS_KEY_ID=your-access-key-id
AWS_SECRET_ACCESS_KEY=your-secret-access-key
AWS_REGION=us-west-2

# Optional: Customize settings
ENVIRONMENT=dev
S3_BUCKET=silica-cron-ls
```

### 3. Initialize Database

```bash
silica cron init
```

### 4. Start Application

```bash
# Development server
silica cron serve

# Or with custom settings
silica cron serve --host 0.0.0.0 --port 8080 --debug
```

### 5. Access Web Interface

Open http://localhost:8080 to access the dashboard.

## CLI Commands

```bash
# Initialize database and configuration
silica cron init

# Start web server
silica cron serve [--host HOST] [--port PORT] [--debug] [--enable-litestream]

# Test Litestream configuration and S3 connectivity
silica cron test-litestream

# Create manual backup (requires Litestream enabled)
silica cron backup

# Restore from backup
silica cron restore [--target PATH]

# Check status
silica cron status
```

## Database Schema

### Database File

- **File Path**: Always `data/silica-cron.db` (consistent across environments)
- **S3 Replication**: Environment-specific prefixes (`dev/`, `prod/`, `staging/`)

### Tables

- **prompts**: Agent prompts with scheduling configuration
- **scheduled_jobs**: Cron job definitions linked to prompts  
- **job_executions**: Execution history and results

### Key Features

- All tables use heare-style IDs (32-char hex) as primary keys
- Foreign key constraints enabled
- Optimized for Litestream replication
- WAL mode for concurrent access

## Litestream Configuration

Litestream provides continuous replication to S3:

- **Database**: Single file `data/silica-cron.db` for all environments
- **S3 Isolation**: Environment-specific prefixes (`dev/`, `prod/`, `staging/`)
- **Snapshots**: Created every hour
- **Retention**: 7 days (168 hours)
- **Validation**: Every 6 hours

## Development Workflow

### Local Development

```bash
# Set environment to dev (default)
echo "ENVIRONMENT=dev" >> .env

# Initialize and run (Litestream disabled by default in dev)
silica cron init
silica cron serve --debug

# Optional: Test Litestream connectivity
silica cron test-litestream

# Optional: Run with Litestream enabled for testing
silica cron serve --enable-litestream
```

### Production Deployment

```bash
# Set environment to prod
ENVIRONMENT=prod

# Enable Litestream for production
LITESTREAM_ENABLED=true

# Configure production S3 credentials
AWS_ACCESS_KEY_ID=prod-key
AWS_SECRET_ACCESS_KEY=prod-secret

# Deploy (uses same database file, different S3 prefix)
silica cron init
silica cron serve --host 0.0.0.0 --port 8080
```

**Note**: The database file (`data/silica-cron.db`) is the same across environments. Only the S3 replication path changes (`prod/silica-cron` vs `dev/silica-cron`) to provide environment isolation for backups.

## Monitoring

### Health Checks

```bash
# Application health
curl http://localhost:8080/health

# Comprehensive status
silica cron status
```

### Backup Verification

```bash
# List available snapshots
silica cron backup

# Test restore (to different location)
silica cron restore --target ./test-restore.db
```

## Troubleshooting

### Database Locked Errors

If you see "database is locked" errors:

1. Check that only one application instance is running
2. Verify WAL mode is enabled: `PRAGMA journal_mode;` should return `wal`
3. Increase busy timeout in database configuration

### Litestream Issues

1. **No snapshots**: Check AWS credentials and S3 bucket permissions
2. **Replication lag**: Monitor Prometheus metrics at `:9090/metrics`
3. **Config errors**: Run `silica cron status` to verify configuration

### Common Issues

```bash
# Verify database exists and is accessible
sqlite3 data/silica-cron.db "SELECT COUNT(*) FROM sqlite_master;"

# Check Litestream config generation
silica cron status

# Force backup to test S3 connectivity  
silica cron backup
```

## File Structure

```
silica/cron/
├── models/           # SQLAlchemy models
├── routes/           # FastAPI routes  
├── templates/        # Jinja2 templates
├── config/           # Settings management
├── scripts/          # Management scripts
└── cli.py           # CLI commands

config/
└── litestream.yml   # Litestream configuration template

data/
└── silica-cron.db         # Single database file (all environments)
```

## Next Steps

1. **Add Prompts**: Use web interface to create agent prompts
2. **Schedule Jobs**: Configure cron expressions for automated execution
3. **Monitor Execution**: View job history and results
4. **Configure Alerts**: Set up monitoring for backup health
5. **Scale**: Add load balancer for multiple instances (read-only replicas)
```