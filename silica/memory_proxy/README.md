# Memory Proxy Service

A dead-simple REST API for syncing memory system files to S3-compatible blob storage.

## Quick Start

### Local Development

1. **Install dependencies**:
   ```bash
   uv sync --dev
   ```

2. **Configure environment** (copy `.env.example` to `.env`):
   ```bash
   cp silica/memory_proxy/.env.example .env
   # Edit .env with your credentials
   ```

3. **Run the service**:
   ```bash
   uvicorn silica.memory_proxy.app:app --reload --port 8000
   ```

4. **Test**:
   ```bash
   # Health check (no auth required)
   curl http://localhost:8000/health
   
   # Write file
   curl -X PUT http://localhost:8000/blob/test.txt \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-MD5: new" \
     -d "Hello, World!"
   
   # Read file
   curl http://localhost:8000/blob/test.txt \
     -H "Authorization: Bearer YOUR_TOKEN"
   
   # Get sync index
   curl http://localhost:8000/sync \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```

### Dokku Deployment

1. **Create app**:
   ```bash
   dokku apps:create memory-proxy
   ```

2. **Configure environment variables**:
   ```bash
   dokku config:set memory-proxy \
     AWS_ACCESS_KEY_ID=your-key \
     AWS_SECRET_ACCESS_KEY=your-secret \
     AWS_REGION=us-east-1 \
     S3_BUCKET=my-memory-bucket \
     S3_PREFIX=memory \
     HEARE_AUTH_URL=https://auth.heare.io \
     HEARE_AUTH_APP_ID=memory-proxy
   ```

3. **Deploy**:
   ```bash
   git remote add dokku-memory dokku@your-server:memory-proxy
   git push dokku-memory feature/memory-proxy-service:master
   ```

4. **Configure domain** (optional):
   ```bash
   dokku domains:set memory-proxy memory.your-domain.com
   dokku letsencrypt:enable memory-proxy
   ```

## API Documentation

See [docs/developer/memory_proxy_service.md](../../docs/developer/memory_proxy_service.md) for complete API documentation.

## Testing

Run the test suite:

```bash
pytest tests/memory_proxy/ -v
```

All tests use moto to mock S3 operations.

## Design Philosophy

This service is intentionally **dead simple**:

- **No database**: Sync index stored as JSON in S3
- **No caching**: Direct S3 operations
- **Single-tenant**: One deployment per user/workspace
- **Strong consistency**: Relies on S3's guarantees
- **Minimal dependencies**: FastAPI + boto3 + httpx

## Architecture

```
┌─────────┐      ┌──────────────┐      ┌─────────────┐
│ Client  │─────▶│ Memory Proxy │─────▶│     S3      │
│         │◀─────│   Service    │◀─────│   Bucket    │
└─────────┘      └──────────────┘      └─────────────┘
                        │
                        ▼
                  ┌──────────┐
                  │  heare-  │
                  │   auth   │
                  └──────────┘
```

## Configuration

All configuration via environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AWS_ACCESS_KEY_ID` | Yes | - | S3 access key |
| `AWS_SECRET_ACCESS_KEY` | Yes | - | S3 secret key |
| `AWS_REGION` | No | `us-east-1` | AWS region |
| `S3_BUCKET` | Yes | - | S3 bucket name |
| `S3_PREFIX` | No | `memory` | S3 key prefix |
| `S3_ENDPOINT_URL` | No | - | Custom S3 endpoint (for MinIO, etc.) |
| `HEARE_AUTH_URL` | Yes | - | heare-auth service URL |
| `HEARE_AUTH_APP_ID` | Yes | - | Application ID for auth |
| `LOG_LEVEL` | No | `INFO` | Logging level |

## Sync Protocol

The service implements a simple sync protocol:

1. Client calls `GET /sync` to get index of all files
2. Client compares local files with index
3. Client uploads changed files with `PUT /blob/{path}` (using Content-MD5 for conditional writes)
4. Client handles 412 responses (precondition failed) by re-syncing
5. Client removes files marked `is_deleted: true` in index

See design document for detailed flow.

## License

MIT
