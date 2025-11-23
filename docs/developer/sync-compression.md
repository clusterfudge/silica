# Compression Design for History Sync

## Problem
History directories can be ~100MB, which is expensive to transfer and store.
Some file trees are really large, so we need compression both in transit AND at rest in S3.

## Solution: Client-Side Compression with Dual MD5 Tracking

### Architecture

```
┌─────────────────┐
│  Sync Engine    │
│  - Reads file   │
│  - Calc MD5(raw)│ ← MD5 on uncompressed content
│  - Detects Δ    │
└────────┬────────┘
         │ upload(content, md5_raw)
         ▼
┌─────────────────┐
│ Proxy Client    │
│  - Compress     │ ← gzip content
│  - Calc MD5(gz) │ ← MD5 on compressed
│  - Add header   │ ← Content-Encoding: gzip
└────────┬────────┘
         │ HTTP PUT with gzip content
         ▼
┌─────────────────┐
│ Memory Proxy    │
│  - Store gz     │
│  - ETag=MD5(gz) │
│  - Metadata     │ ← Store original_md5
└─────────────────┘
```

### Key Changes

#### 1. Proxy Client (write_blob)
```python
def write_blob(self, namespace, path, content, expected_version, 
               content_md5=None, compress=True):
    # Compress if enabled and beneficial
    if compress and len(content) > 1024:  # Only compress >1KB
        compressed = gzip.compress(content)
        if len(compressed) < len(content) * 0.9:  # Only if >10% savings
            content_to_send = compressed
            headers["Content-Encoding"] = "gzip"
            # Send original MD5 in custom header
            headers["X-Original-MD5"] = content_md5 or hashlib.md5(content).hexdigest()
        else:
            content_to_send = content
    
    # Calculate MD5 of what we're sending
    transport_md5 = hashlib.md5(content_to_send).hexdigest()
    headers["Content-MD5"] = transport_md5
```

#### 2. Proxy Client (read_blob)
```python
def read_blob(self, namespace, path):
    response = self.client.get(url)
    content = response.content
    
    # Decompress if needed
    if response.headers.get("Content-Encoding") == "gzip":
        content = gzip.decompress(content)
    
    # Get original MD5 (for change detection)
    original_md5 = response.headers.get("X-Original-MD5")
    if not original_md5:
        # Fall back to ETag if no original MD5
        original_md5 = response.headers.get("ETag", "").strip('"')
    
    return content, original_md5, ...
```

#### 3. Memory Proxy Server
- Accept `Content-Encoding: gzip` header
- Store compressed data directly to S3 (at-rest compression)
- Store `X-Original-MD5` in S3 object metadata
- Return compression headers on reads
- S3 stores gzipped blobs, NOT plain text

#### 4. Sync Engine (no changes!)
- Continues to calculate MD5 on local uncompressed files
- Compares with original_md5 from remote
- Everything else works transparently

### Index Storage

LocalIndex already stores MD5, no changes needed:
```json
{
  "path/to/file.md": {
    "md5": "abc123...",  # MD5 of uncompressed content
    "size": 12345,        # Size of uncompressed content
    "version": 42
  }
}
```

### Benefits
1. ✅ **Transparent to sync engine** - No logic changes
2. ✅ **Correct MD5 comparisons** - Based on actual content
3. ✅ **At-rest storage savings** - ~70-90% compression in S3
4. ✅ **In-transit bandwidth savings** - Compressed transfers
5. ✅ **Selective compression** - Only when beneficial
6. ✅ **Backward compatible** - Falls back to uncompressed

### S3 Storage Details

The memory proxy server stores data compressed at rest:

```python
# In memory proxy storage layer
def write_blob_to_s3(namespace, path, content, metadata):
    # Content arrives already compressed from client
    # Store it compressed in S3
    s3_client.put_object(
        Bucket=bucket,
        Key=f"{namespace}/{path}",
        Body=content,  # Already gzipped
        ContentEncoding='gzip',  # Tell S3 it's compressed
        Metadata={
            'original-md5': metadata['original_md5'],
            'original-size': metadata['original_size'],
        }
    )
    
    # S3 now stores the gzipped bytes
    # Storage cost = size of compressed data
```

Key points:
- Client compresses → Server stores compressed → S3 holds compressed
- No decompression on server (just passes through)
- Massive S3 storage cost savings
- S3 serves compressed data with Content-Encoding header
- Client decompresses on download

### Implementation Order
1. Add compression to proxy client (`proxy_client.py`)
2. Update memory proxy server to store compressed in S3
3. Update memory proxy server to pass through compression headers
4. Add tests for compression (client + server)
5. Enable by default for history sync (large files)
6. Monitor compression ratios and adjust thresholds

### Compression Stats (estimated for history)
- Markdown/JSON: 70-90% compression
- 100MB → ~15MB in transit (bandwidth savings)
- 100MB → ~15MB in S3 (storage cost savings)
- Both at-rest AND in-transit compression
- S3 storage costs reduced by 85%+
