# Sync Compression

The memory sync system supports gzip compression for history files to reduce transfer times and storage costs.

## Overview

History files (conversation transcripts) can grow quite large - often several megabytes for long sessions. Compression typically achieves 70-85% reduction in file size, significantly improving sync performance.

## Configuration

Compression is controlled via the `compress` parameter in `SyncConfig`:

```python
from silica.developer.memory.sync_config import SyncConfig

# History sync has compression enabled by default
config = SyncConfig.for_history("my_persona", "session-123")
assert config.compress == True

# Memory sync has compression disabled (small files, not worth it)
config = SyncConfig.for_memory("my_persona")
assert config.compress == False

# Manual configuration
config = SyncConfig(
    namespace="custom/namespace",
    scan_paths=[Path("/my/files")],
    index_file=Path("/my/.sync-index.json"),
    base_dir=Path("/my"),
    compress=True,  # Enable compression
)
```

## How It Works

### Upload (Local → Remote)

1. File content is read from disk
2. Content is gzip compressed (level 6 - good balance of speed/size)
3. If compressed size < original size, upload compressed with `.gz` extension
4. If compression doesn't help (e.g., already compressed data), upload uncompressed
5. Content-Type is set to `application/gzip` for compressed files

```
Local: conversation.json (10MB)
  ↓ gzip compress
Remote: conversation.json.gz (2MB)
```

### Download (Remote → Local)

1. File is downloaded from remote
2. If path ends with `.gz` or Content-Type is `application/gzip`, decompress
3. Write decompressed content to local file (without `.gz` extension)

```
Remote: conversation.json.gz (2MB)
  ↓ gzip decompress
Local: conversation.json (10MB)
```

## Compression Effectiveness

Typical compression ratios for different content types:

| Content Type | Typical Reduction |
|-------------|------------------|
| JSON conversation logs | 70-85% |
| Markdown memory entries | 60-75% |
| Already compressed data | 0% (skipped) |

Example from real-world testing:
- 40MB JSON history → 6.5MB compressed (84% reduction)
- 15MB JSON history → 84KB compressed (99% reduction, highly repetitive)

## Server Configuration

### Dokku/Nginx

The memory proxy server needs sufficient upload limits to handle large files. For Dokku deployments:

```bash
# Set client_max_body_size (default is 1MB)
dokku nginx:set memory-proxy client-max-body-size 100m

# Optional: increase timeouts for large uploads
dokku nginx:set memory-proxy client-body-timeout 120s
dokku nginx:set memory-proxy proxy-read-timeout 120s

# Apply changes
dokku proxy:build-config memory-proxy

# Verify
dokku nginx:report memory-proxy
```

Even with compression, some files may exceed default limits. A 100MB limit provides headroom for:
- Large uncompressed files during initial sync
- Edge cases where compression is ineffective

## Backward Compatibility

The sync system handles both compressed and uncompressed remote files:

- Files with `.gz` extension are automatically decompressed on download
- Files without `.gz` extension are handled as raw content
- The local index tracks the remote path (including `.gz` if applicable)

This allows gradual migration - existing uncompressed files will work, and new uploads will be compressed.

## Troubleshooting

### HTTP 413 Errors

If you see "413 Request Entity Too Large" errors:

1. Check the file size being uploaded
2. Verify compression is enabled for history sync
3. Increase nginx `client_max_body_size` on the server

### Files Not Compressing

Compression is skipped if:
- `config.compress` is False
- Compressed size >= original size (no benefit)

Check logs for compression details:
```
DEBUG - Compressed test.json: 10000 -> 2500 bytes (75% reduction)
```

### Decompression Failures

If download fails with gzip errors:
- File may have `.gz` extension but not be gzip compressed
- Content-Type may be incorrect
- The sync system handles this gracefully, using raw content
