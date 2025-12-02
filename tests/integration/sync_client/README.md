# Sync Client Integration Tests

## Overview

Comprehensive integration tests for the sync client that test against an **in-process memory proxy service** using moto for S3 mocking. These tests validate the full sync workflow with actual HTTP communication, storage operations, and state management.

## Architecture

The tests use:
- **In-process memory proxy** - A real FastAPI app running in a background thread via uvicorn
- **Moto S3 mock** - AWS S3 is mocked using moto, no real AWS credentials needed
- **Mocked authentication** - Auth service is mocked to always succeed
- **Real HTTP communication** - Tests make actual HTTP requests via httpx

This approach gives us true integration testing without external dependencies.

## Running Tests

### Run All Integration Tests

```bash
# Run all sync client integration tests
pytest tests/integration/sync_client/ -v

# Or use the marker
pytest -m integration tests/integration/sync_client/ -v
```

### Skip Integration Tests

```bash
# Run only unit tests (skip integration)
pytest -m "not integration"
```

### Run Specific Test Files

```bash
# Bootstrap scenarios
pytest tests/integration/sync_client/test_bootstrap.py -v

# Normal operations
pytest tests/integration/sync_client/test_normal_ops.py -v

# Staleness detection
pytest tests/integration/sync_client/test_staleness.py -v
```

## Test Structure

```
tests/integration/sync_client/
├── conftest.py                  # Fixtures: in-process proxy, moto S3, test helpers
├── test_bootstrap.py            # Bootstrap scenarios (7 tests)
├── test_download_after_clear.py # Index clearing edge case (1 test)
├── test_history_sync.py         # History-specific tests (5 tests)
├── test_memory_sync.py          # Memory-specific tests (5 tests)
├── test_namespace_first.py      # URL routing tests (4 tests)
├── test_normal_ops.py           # Upload/download/delete (9 tests)
├── test_staleness.py            # Manifest-on-write (4 tests)
└── test_state_mgmt.py           # Index/cache management (7 tests)
```

## Test Categories

### Bootstrap Tests (`test_bootstrap.py`)
Tests sync engine initialization scenarios:
- Bootstrap from existing local content only
- Bootstrap from remote content only
- Bidirectional merge (local + remote files)
- Content mismatch detection (same file, different content)

### Normal Operations (`test_normal_ops.py`)
Tests standard sync operations:
- Upload new and modified files
- Download new and modified files
- Delete propagation (local→remote, remote→local)
- Nested directory structures
- Multiple files in single sync

### Memory Sync (`test_memory_sync.py`)
Tests memory-specific sync behavior:
- Memory directory structure preservation
- persona.md inclusion in sync
- Proper namespace handling

### History Sync (`test_history_sync.py`)
Tests history-specific sync behavior:
- Session isolation (only target session synced)
- Conversation history files
- Session metadata handling

### State Management (`test_state_mgmt.py`)
Tests index and cache behavior:
- Index persistence across engine instances
- Index accuracy after operations
- MD5 cache integration
- Sync metadata file exclusion

### Staleness Detection (`test_staleness.py`)
Tests manifest-on-write optimization:
- Local index updates from write responses
- Concurrent modification detection
- No unnecessary fetches when in sync

## Key Fixtures

### `memory_proxy_server` (module-scoped)
Starts an in-process memory proxy:
- Runs on `http://127.0.0.1:18000` (avoids conflicts with default port)
- Uses moto for S3 storage
- Mocked authentication (always succeeds)
- Automatically cleaned up after tests

### `sync_client`
Pre-configured `MemoryProxyClient` connected to the test server.

### `memory_sync_engine` / `history_sync_engine`
Pre-configured `SyncEngine` instances for memory or history sync testing.

### `create_local_files` / `create_remote_files`
Helper functions to set up test data:
```python
# Create local files
create_local_files({
    "memory/notes.md": "# Notes",
    "memory/projects/alpha.md": "Alpha project"
})

# Create remote files
create_remote_files("memory", {
    "remote-only.md": "Content from remote"
})
```

### `clean_namespace`
Provides a unique namespace for each test to ensure isolation.

## Test Philosophy

These are **true integration tests** that test the full stack:
- ✅ Real HTTP requests via httpx
- ✅ Real MemoryProxyClient (not mocked)
- ✅ Real FastAPI application
- ✅ Real S3 operations (via moto)
- ✅ No external dependencies required

For unit tests with mocked HTTP, see `tests/developer/test_memory_sync.py`.

## CI/CD Integration

The tests run automatically in GitHub Actions. See `.github/workflows/integration-tests.yml`.

No special setup is required - the in-process server and moto handle everything.

## Troubleshooting

### Port Already in Use

If you see `OSError: address already in use`:
- Another test run may be using port 18000
- Kill any orphaned processes: `lsof -i :18000`

### Tests Hanging

The server fixture has a 5-second startup timeout. If tests hang:
- Check for import errors in the memory proxy code
- Ensure all dependencies are installed: `uv pip install -e ".[dev]"`

## Test Coverage

Current test suite covers:
- ✅ Bootstrap scenarios (local, remote, bidirectional)
- ✅ Normal operations (upload, download, delete)
- ✅ Memory sync specifics
- ✅ History sync specifics
- ✅ Index and cache state management
- ✅ Manifest-on-write optimization
- ✅ Namespace URL encoding

Total: **41 integration tests**
