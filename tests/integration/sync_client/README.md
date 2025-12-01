# Sync Client Integration Tests

## Overview

Integration test infrastructure for the sync client that tests against an **in-process memory proxy service** using moto for S3 mocking. These tests validate HTTP communication with the actual memory proxy API.

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

## Key Fixtures (in conftest.py)

### `memory_proxy_server` (module-scoped)
Starts an in-process memory proxy:
- Runs on `http://127.0.0.1:18000` (avoids conflicts with default port)
- Uses moto for S3 storage
- Mocked authentication (always succeeds)
- Automatically cleaned up after tests

### `sync_client`
Pre-configured `MemoryProxyClient` connected to the test server.

### `clean_namespace`
Provides a unique namespace for each test to ensure isolation.

## Current Tests

### Namespace URL Routing (`test_namespace_first.py`)
Tests the namespace-first URL pattern:
- `/{namespace}/blob/{path}` route works correctly
- Namespaces with slashes are properly URL-encoded

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

## Adding New Tests

1. Create a new test file in this directory
2. Use the `@pytest.mark.integration` decorator
3. Use fixtures from `conftest.py` for the proxy server and clients
4. Each test gets a unique namespace via `clean_namespace` fixture

Example:
```python
@pytest.mark.integration
def test_my_feature(sync_client, clean_namespace):
    # sync_client is connected to the in-process memory proxy
    # clean_namespace provides a unique namespace for this test
    pass
```
