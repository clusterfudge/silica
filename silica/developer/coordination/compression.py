"""Compression utilities for large coordination payloads.

Provides transparent compression/decompression for messages that exceed
a size threshold.
"""

import base64
import gzip


# Default threshold for compression (10KB)
DEFAULT_COMPRESSION_THRESHOLD = 10 * 1024

# Compression method identifier
COMPRESSION_METHOD_GZIP = "gzip"


def compress_payload(
    data: str,
    threshold: int = DEFAULT_COMPRESSION_THRESHOLD,
) -> tuple[str, str | None]:
    """Compress a payload if it exceeds the threshold.

    Args:
        data: The string data to potentially compress
        threshold: Size threshold in bytes above which to compress

    Returns:
        Tuple of (payload, compression_method):
        - If compressed: (base64-encoded compressed data, "gzip")
        - If not compressed: (original data, None)
    """
    data_bytes = data.encode("utf-8")

    if len(data_bytes) <= threshold:
        return data, None

    compressed = gzip.compress(data_bytes)

    # Base64 encode for safe transport
    encoded = base64.b64encode(compressed).decode("ascii")

    # Only use compression if it actually reduces size after base64 encoding
    # (base64 adds ~33% overhead, so compressed must be significantly smaller)
    if len(encoded) >= len(data):
        return data, None

    return encoded, COMPRESSION_METHOD_GZIP


def decompress_payload(data: str, method: str | None) -> str:
    """Decompress a payload if compression method is specified.

    Args:
        data: The payload data (possibly compressed)
        method: Compression method used, or None if not compressed

    Returns:
        Decompressed string data

    Raises:
        ValueError: If compression method is unknown
    """
    if method is None:
        return data

    if method == COMPRESSION_METHOD_GZIP:
        compressed = base64.b64decode(data)
        decompressed = gzip.decompress(compressed)
        return decompressed.decode("utf-8")

    raise ValueError(f"Unknown compression method: {method}")


def estimate_compressed_size(data: str) -> int:
    """Estimate the compressed size of data without fully compressing.

    Useful for deciding whether to compress without the full overhead.
    This uses a simple heuristic based on data characteristics.

    Args:
        data: The string data to estimate

    Returns:
        Estimated compressed size in bytes
    """
    data_bytes = data.encode("utf-8")
    original_size = len(data_bytes)

    # Rough heuristic: JSON/text typically compresses to 20-40% of original
    # Use 35% as a conservative estimate
    return int(original_size * 0.35)
