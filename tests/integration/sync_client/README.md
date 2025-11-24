# Sync Client Integration Tests

## Overview

Comprehensive integration tests for the sync client that test against a **real memory proxy service**. These tests validate the full sync workflow with actual HTTP communication, storage operations, and state management.

**Important**: These are true integration tests - they require a running memory proxy service and will skip if the service is not available.

## Requirements

- **Running memory proxy service** (required)
- Properly configured S3 backend (can use moto, LocalStack, or real S3)

## Running Tests

### Prerequisites

You **must** start the memory proxy service before running tests:

```bash
# Terminal 1: Start memory proxy service
cd silica/memory_proxy
python -m silica.memory_proxy.app

# Or if you have a .env file configured:
python -m silica.memory_proxy.app
```

The service should start on `http://localhost:8000` by default.

### Default Configuration (localhost:8000)

```bash
# Terminal 2: Run integration tests
pytest tests/integration/sync_client/ -v

# Tests will skip with helpful message if proxy isn't running
```

### Custom Configuration

```bash
# Set environment variables
export MEMORY_PROXY_PORT=9000
export MEMORY_PROXY_HOST=test-proxy.local
export MEMORY_PROXY_TOKEN=custom-token

# Run tests
pytest tests/integration/sync_client/ -v
```

### Skip Integration Tests

```bash
# Run only unit tests (skip integration)
pytest -m "not integration"
```

### Run Specific Test Categories

```bash
# Memory sync tests only
pytest tests/integration/sync_client/ -v -m memory_sync

# History sync tests only
pytest tests/integration/sync_client/ -v -m history_sync

# Slow tests (performance)
pytest tests/integration/sync_client/ -v -m slow
```

## Test Structure

```
tests/integration/sync_client/
├── conftest.py              # Shared fixtures and configuration
├── test_bootstrap.py        # Bootstrap scenarios (6 tests)
├── test_normal_ops.py       # Upload/download/delete (12 tests)
├── test_memory_sync.py      # Memory-specific tests (5 tests)
├── test_history_sync.py     # History-specific tests (6 tests)
├── test_state_mgmt.py       # Index/cache management (7 tests)
└── test_staleness.py        # Manifest-on-write (4 tests)
```

## Test Categories

### Bootstrap Tests (`test_bootstrap.py`)
- Bootstrap from existing local content
- Bootstrap from remote content  
- Bidirectional merge scenarios

### Normal Operations (`test_normal_ops.py`)
- Upload new and modified files
- Download new and modified files
- Delete propagation (local→remote, remote→local)
- Nested directory structures

### Memory Sync (`test_memory_sync.py`)
- Memory directory structure preservation
- History file exclusion from memory sync
- persona.md inclusion in memory sync

### History Sync (`test_history_sync.py`)
- Session isolation (only target session synced)
- Multiple independent sessions
- Conversation history files
- Session metadata preservation

### State Management (`test_state_mgmt.py`)
- Index persistence across engine instances
- Index accuracy tracking
- MD5 cache integration and cleanup
- Sync metadata file exclusion

### Staleness Detection (`test_staleness.py`)
- Manifest-on-write optimization
- Concurrent modification detection
- No-op when already in sync
- Tombstone tracking via manifest

## Test Philosophy

These are **true integration tests** - they test the full stack:
- Real HTTP requests via `httpx`
- Real MemoryProxyClient (not mocked)
- Real FastAPI application (memory proxy)
- Real S3 storage (via moto, LocalStack, or actual S3)
- Real authentication flow

**We do NOT mock the memory proxy service.** If the service isn't running, tests skip with a helpful message.

This approach:
- ✅ Tests actual HTTP communication
- ✅ Catches real integration issues
- ✅ Validates complete workflows
- ✅ Ensures client and server are compatible
- ❌ Requires service to be running
- ❌ Slower than pure unit tests

For unit tests with mocks, see `tests/developer/test_memory_sync.py`.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MEMORY_PROXY_PORT` | 8000 | Memory proxy service port |
| `MEMORY_PROXY_HOST` | localhost | Memory proxy hostname |
| `MEMORY_PROXY_TOKEN` | test-integration-token | Auth token |

## Test Markers

- `@pytest.mark.integration` - Integration test (requires proxy)
- `@pytest.mark.requires_proxy` - Explicitly requires proxy service
- `@pytest.mark.slow` - Slow-running test (performance tests)
- `@pytest.mark.memory_sync` - Memory sync specific
- `@pytest.mark.history_sync` - History sync specific

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Integration Tests

on: [push, pull_request]

jobs:
  integration:
    runs-on: ubuntu-latest
    
    services:
      moto:
        image: motoserver/moto
        ports:
          - 5000:5000
    
    steps:
      - uses: actions/checkout@v2
      
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.11
      
      - name: Install dependencies
        run: |
          pip install -e .
          pip install pytest
      
      - name: Start memory proxy
        run: |
          python -m silica.memory_proxy.app &
          sleep 5
      
      - name: Run integration tests
        run: pytest tests/integration/sync_client/ -v -m integration
```

## Troubleshooting

### Tests Skip with "Memory proxy not accessible"

**Problem:** All tests are skipped with a message like:
```
SKIPPED [40] Memory proxy not accessible at http://localhost:8000
Start the service with: python -m silica.memory_proxy.app
```

**Solution:**
```bash
# 1. Ensure memory proxy dependencies are installed
pip install -e .

# 2. Configure the memory proxy (create .env file in silica/memory_proxy/)
cd silica/memory_proxy
cp .env.example .env
# Edit .env with your S3 and auth configuration

# 3. Start the memory proxy service
python -m silica.memory_proxy.app

# 4. Verify it's running
curl http://localhost:8000/health
# Should return: {"status":"ok","storage":"connected"}
```

**For testing with moto (mock S3):**
You can configure the memory proxy to use moto for S3 in tests. See `tests/memory_proxy/conftest.py` for examples.

### Connection Refused Errors

**Problem:** Tests fail with connection errors.

**Solution:** Verify proxy configuration:
```bash
# Check proxy is running on correct port
netstat -an | grep 8000

# Set correct environment variables
export MEMORY_PROXY_PORT=8000
export MEMORY_PROXY_HOST=localhost
```

### S3 Storage Errors

**Problem:** Tests fail with S3 errors.

**Solution:** Ensure moto or LocalStack is configured:
```bash
# Memory proxy should be configured with moto
# Check memory_proxy/config.py settings
```

## Test Coverage

Current test suite covers:
- ✅ Bootstrap scenarios (local, remote, bidirectional)
- ✅ Normal operations (upload, download, delete)
- ✅ Memory sync specifics
- ✅ History sync specifics  
- ✅ Index and cache state management
- ✅ Manifest-on-write optimization
- ✅ Error handling (basic)

Total: **40+ integration tests**

## Future Enhancements

- [ ] Conflict resolution tests (with LLM resolver)
- [ ] Network error handling (timeout, retry)
- [ ] Version conflict scenarios (412 errors)
- [ ] Performance tests (large files, many files)
- [ ] Multi-namespace concurrent tests
- [ ] Compression integration (when implemented)

## Notes

- Tests use temporary directories (cleaned up automatically)
- Each test gets a unique namespace (isolated)
- Tests are designed to be repeatable and non-flaky
- No manual cleanup required between test runs
