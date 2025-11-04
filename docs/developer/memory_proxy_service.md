# Memory Proxy Service

A minimal REST API for syncing memory system files to S3-compatible blob storage. Provides one-way sync (client → server) with strong consistency via conditional writes.

## Architecture

- **Framework**: FastAPI
- **Storage**: S3 (via boto3)
- **Auth**: heare-auth token validation
- **Deployment**: Dokku (12-factor app)

## Features

- **Conditional Writes**: Content-MD5 based precondition checks
- **Tombstones**: Soft deletes tracked in sync index
- **Sync Index**: Single JSON file in S3 tracking all file metadata
- **Single Tenant**: One deployment per user/workspace
- **Strong Consistency**: S3 provides read-after-write consistency

## API Endpoints

### `GET /health`
Health check (no auth required).

**Response**: `200 OK`
```json
{"status": "ok", "storage": "connected"}
```

---

### `GET /blob/{path}`
Read a file from blob storage.

**Auth**: Required  
**Headers Response**:
- `ETag`: Content MD5
- `Last-Modified`: HTTP date
- `Content-Type`: File content type

**Response**: 
- `200 OK`: File contents
- `404 Not Found`: File doesn't exist or is tombstoned

---

### `PUT /blob/{path}`
Write or update a file with conditional write support.

**Auth**: Required  
**Headers Request**:
- `Content-MD5`: Expected MD5 (use "new" for new files, current MD5 for updates)
- `Content-Type`: File content type (optional)

**Request Body**: File contents

**Response**:
- `201 Created`: New file created
- `200 OK`: Existing file updated
- `412 Precondition Failed`: MD5 mismatch

---

### `DELETE /blob/{path}`
Delete a file (creates tombstone).

**Auth**: Required  
**Headers Request** (optional):
- `If-Match`: Expected MD5 for conditional delete

**Response**:
- `204 No Content`: File tombstoned
- `404 Not Found`: File doesn't exist
- `412 Precondition Failed`: MD5 mismatch

---

### `GET /sync`
Get sync index listing all files and their metadata.

**Auth**: Required

**Response**: `200 OK`
```json
{
  "files": {
    "memory/topics/knowledge/ai": {
      "md5": "5d41402abc4b2a76b9719d911017c592",
      "last_modified": "2024-01-15T10:30:00.123Z",
      "size": 1234,
      "is_deleted": false
    }
  },
  "index_last_modified": "2024-01-15T11:00:00.456Z"
}
```

## Configuration

All configuration via environment variables:

### Required
- `AWS_ACCESS_KEY_ID`: S3 access key
- `AWS_SECRET_ACCESS_KEY`: S3 secret key
- `AWS_REGION`: S3 region (e.g., us-east-1)
- `S3_BUCKET`: S3 bucket name
- `HEARE_AUTH_URL`: Auth service URL
- `HEARE_AUTH_APP_ID`: Application ID for auth

### Optional
- `S3_PREFIX`: Path prefix for all objects (default: "memory")
- `S3_ENDPOINT_URL`: Custom S3 endpoint (for S3-compatible services)
- `LOG_LEVEL`: Logging level (default: INFO)

## Deployment

### Dokku Deployment (Automated via CLI)

The easiest way to deploy the memory proxy is using the built-in CLI commands:

1. **Run setup** (interactive configuration):
   ```bash
   silica memory-proxy setup dokku@your-server
   ```

   This will:
   - Prompt for all required configuration (AWS credentials, S3 bucket, etc.)
   - Create deployment files in `~/.silica/memory-proxy`
   - Initialize a git repository
   - Save configuration to `~/.silica/config.env`

2. **Deploy to Dokku**:
   ```bash
   silica memory-proxy deploy
   ```

   This will:
   - Push the code to dokku (creating the app automatically on first push)
   - Set all configuration variables
   - Deploy the service

3. **Check status**:
   ```bash
   silica memory-proxy status
   ```

4. **Upgrade to a new version**:
   ```bash
   silica memory-proxy upgrade 0.8.0
   ```

### Dokku Deployment (Manual)

For manual deployment or customization:

1. **Create app**:
   ```bash
   dokku apps:create memory-proxy
   ```

2. **Set environment variables**:
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
   git push dokku-memory main:master
   ```

4. **Configure domain** (optional):
   ```bash
   dokku domains:set memory-proxy memory.your-domain.com
   dokku letsencrypt:enable memory-proxy
   ```

### Local Development

1. **Create `.env` file**:
   ```env
   AWS_ACCESS_KEY_ID=test-key
   AWS_SECRET_ACCESS_KEY=test-secret
   AWS_REGION=us-east-1
   S3_BUCKET=test-bucket
   S3_PREFIX=memory
   S3_ENDPOINT_URL=http://localhost:9000  # For MinIO/LocalStack
   HEARE_AUTH_URL=http://localhost:8001
   HEARE_AUTH_APP_ID=memory-proxy-dev
   LOG_LEVEL=DEBUG
   ```

2. **Run with uvicorn**:
   ```bash
   uvicorn silica.memory_proxy.app:app --reload --port 8000
   ```

3. **Test with curl**:
   ```bash
   # Health check (no auth)
   curl http://localhost:8000/health
   
   # Write file (with auth)
   curl -X PUT http://localhost:8000/blob/test/file.txt \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-MD5: new" \
     -d "Hello, World!"
   
   # Read file
   curl http://localhost:8000/blob/test/file.txt \
     -H "Authorization: Bearer YOUR_TOKEN"
   
   # Get sync index
   curl http://localhost:8000/sync \
     -H "Authorization: Bearer YOUR_TOKEN"
   
   # Delete file
   curl -X DELETE http://localhost:8000/blob/test/file.txt \
     -H "Authorization: Bearer YOUR_TOKEN"
   ```

## Client Sync Protocol

### Sync Flow

1. **Fetch Index**: `GET /sync` → Get list of all files with metadata
2. **Compare**: Client compares local files against index
3. **Upload Changes**: For each locally modified file:
   - Calculate MD5 of local content
   - `PUT /blob/{path}` with `Content-MD5: {old_md5}`
   - Handle 412 by re-fetching and retrying (or manual resolution)
4. **Download Changes**: For each file newer on server (future):
   - `GET /blob/{path}`
   - Save locally
5. **Handle Deletes**: For files marked `is_deleted` in index:
   - Remove from local filesystem
6. **Repeat**: Periodically (e.g., every 30 seconds)

### Conflict Avoidance

- Client tracks last-synced MD5 for each file
- Only sends updates if local MD5 differs from last-synced MD5
- On 412 response, client decides: retry with new MD5, or abandon local changes

## Storage Details

### S3 Object Structure

Each file is stored as an S3 object:
- **Key**: `{S3_PREFIX}/{path}`
- **Body**: File contents (empty for tombstones)
- **Metadata**:
  - `content-md5`: MD5 hash of content
  - `is-deleted`: "true" for tombstones
  - `last-modified`: Managed by S3

### Sync Index

Stored at `{S3_PREFIX}/.sync-index.json`:
```json
{
  "files": {
    "path/to/file": {
      "md5": "abc123...",
      "last_modified": "2024-01-15T10:30:00.123Z",
      "size": 1234,
      "is_deleted": false
    }
  },
  "index_last_modified": "2024-01-15T11:00:00.456Z"
}
```

**Index Update Strategy**: Last-write-wins (acceptable as individual blobs have strong consistency).

## Testing

### Unit Tests

```bash
pytest tests/memory_proxy/ -v
```

Uses `moto` to mock S3 operations.

### Integration Tests

```bash
# Set up LocalStack or MinIO
docker run -p 9000:9000 minio/minio server /data

# Run integration tests
pytest tests/memory_proxy/ -m integration
```

## Future Enhancements

- **Lifecycle Management**: S3 lifecycle policy to permanently delete old tombstones
- **Versioning**: Keep multiple versions of files
- **Compression**: Compress files before storing
- **Batch Operations**: Upload/download multiple files in one request
- **WebSocket Sync**: Real-time sync notifications
- **Multi-tenancy**: Support multiple users/workspaces
- **Metrics Dashboard**: Prometheus/Grafana

## Troubleshooting

### "Authentication service unavailable"
- Check that `HEARE_AUTH_URL` is correct and accessible
- Verify auth service is running

### "Storage disconnected"
- Check AWS credentials are valid
- Verify S3 bucket exists and is accessible
- Check network connectivity to S3

### 412 Precondition Failed
- Client's local MD5 doesn't match server's
- Another client modified the file
- Client should re-fetch and retry or resolve manually

### Index seems stale
- Index updates use last-write-wins
- Race conditions are acceptable - index is eventually consistent
- Individual blob operations are strongly consistent
