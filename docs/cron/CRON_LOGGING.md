# Cron Application Logging Configuration

The Silica Cron system includes comprehensive logging configuration to provide visibility into application behavior while minimizing noise from third-party libraries.

## Features

### Structured Logging
- **Environment-aware formatting**: Simple format for development, detailed for production
- **Multiple log levels**: DEBUG, INFO, WARNING, ERROR support
- **Rotating file logs**: Automatic log rotation with size limits and backup retention
- **Separate error logs**: Dedicated error log file for easier troubleshooting

### Third-Party Noise Suppression
- **HTTP library suppression**: httpx, urllib3, and requests logs are limited to WARNING level
- **Database query suppression**: SQLAlchemy logs suppressed unless in debug mode  
- **Uvicorn access logs**: Suppressed to reduce noise during API testing
- **AWS/S3 library suppression**: Boto3 and S3 transfer logs minimized

### Flexible Configuration
- **File logging toggle**: Can disable file logging for containerized environments
- **Configurable log directory**: Specify custom log location
- **Per-environment settings**: Different log levels for dev vs production

## Configuration

### Environment Variables

```bash
# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=info

# Enable/disable file logging
LOG_TO_FILE=true

# Custom log directory
LOG_DIR=./logs
```

### Settings in .env

```env
# Basic application settings
ENVIRONMENT=dev
DEBUG=true
LOG_LEVEL=info
LOG_TO_FILE=true
LOG_DIR=./logs
```

## Log Files

When file logging is enabled, the following files are created:

### `logs/cron.log`
- **Content**: All application logs at configured level
- **Format**: Detailed with timestamps, module names, and line numbers
- **Rotation**: 10MB max size, 5 backup files retained

### `logs/cron-errors.log`
- **Content**: ERROR level logs only
- **Purpose**: Quick access to critical issues
- **Rotation**: Same as main log file

## Logger Hierarchy

### Application Loggers
- **`silica.cron`**: Main application logger
  - Development: DEBUG level
  - Production: Configured level (INFO by default)

### Third-Party Loggers
- **`httpx`**: WARNING level (suppresses HTTP request logs)
- **`urllib3`**: WARNING level (suppresses connection pool logs)
- **`uvicorn.access`**: WARNING level (suppresses access logs)
- **`sqlalchemy`**: WARNING level (INFO/DEBUG only in debug mode)
- **`fastapi`**: INFO level (important framework messages only)

## Usage Examples

### Getting a Logger

```python
from silica.cron.config.logging import get_logger

logger = get_logger(__name__)
logger.info("Application started")
logger.debug("Debug information")
logger.error("Something went wrong")
```

### Console vs File Output

**Development (console output):**
```
INFO - Application started
DEBUG - Processing request  
ERROR - Database connection failed
```

**Production (file output):**
```
2024-01-01 12:00:00 - silica.cron.app - INFO - main:45 - Application started
2024-01-01 12:00:01 - silica.cron.scheduler - DEBUG - execute_job:123 - Processing request
2024-01-01 12:00:02 - silica.cron.models - ERROR - get_db:67 - Database connection failed
```

## Testing Configuration

During tests, logging is configured to minimize noise:

```python
# In conftest.py
from silica.cron.config.logging import configure_test_logging

configure_test_logging()  # Suppresses httpx and other test noise
```

This ensures test output is clean and focused on actual test results.

## Troubleshooting

### No Log Files Created
- Check `LOG_TO_FILE=true` in environment variables
- Verify log directory permissions
- Ensure `LOG_DIR` path is writable

### Too Much Noise in Logs
- Increase log level: `LOG_LEVEL=warning`
- Check third-party logger configuration
- Consider using ERROR-only log file

### Missing Application Logs
- Verify `silica.cron` logger level
- Check if propagate is disabled
- Use `get_logger(__name__)` for module loggers

### Debugging Third-Party Issues
Temporarily enable detailed logging for specific libraries:

```python
import logging
logging.getLogger("httpx").setLevel(logging.DEBUG)
logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)
```

## Production Recommendations

1. **Set appropriate log level**: Use INFO or WARNING in production
2. **Enable file logging**: Essential for troubleshooting production issues
3. **Monitor log file sizes**: Ensure rotation is working properly
4. **Consider log aggregation**: Ship logs to centralized system
5. **Separate error alerting**: Monitor error log file for critical issues

## Log Rotation

Log files automatically rotate when they exceed 10MB:

- **Maximum size**: 10MB per file
- **Backup count**: 5 historical files kept
- **Naming pattern**: `cron.log.1`, `cron.log.2`, etc.
- **Automatic cleanup**: Oldest files are deleted when limit exceeded

This prevents logs from consuming excessive disk space while maintaining sufficient history for debugging.