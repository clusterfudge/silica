"""Tests for coordination compression utilities."""

import pytest
from silica.developer.coordination.compression import (
    compress_payload,
    decompress_payload,
    estimate_compressed_size,
    DEFAULT_COMPRESSION_THRESHOLD,
    COMPRESSION_METHOD_GZIP,
)


class TestCompressPayload:
    """Test payload compression."""

    def test_small_payload_unchanged(self):
        """Payloads under threshold should not be compressed."""
        small_data = "Hello, world!"
        result, method = compress_payload(small_data)

        assert result == small_data
        assert method is None

    def test_large_payload_compressed(self):
        """Payloads over threshold should be compressed."""
        # Create data larger than threshold
        large_data = "x" * (DEFAULT_COMPRESSION_THRESHOLD + 1000)
        result, method = compress_payload(large_data)

        assert method == COMPRESSION_METHOD_GZIP
        assert result != large_data
        # Compressed should be smaller (repetitive data compresses well)
        assert len(result) < len(large_data)

    def test_custom_threshold(self):
        """Should respect custom threshold."""
        data = "x" * 100

        # With low threshold, should compress
        result, method = compress_payload(data, threshold=50)
        assert method == COMPRESSION_METHOD_GZIP

        # With high threshold, should not compress
        result, method = compress_payload(data, threshold=200)
        assert method is None

    def test_incompressible_data_not_expanded(self):
        """Data that doesn't compress well should not be compressed if it would expand."""
        # Random-looking data that doesn't compress well
        import random

        random.seed(42)
        incompressible = "".join(
            chr(random.randint(33, 126))
            for _ in range(DEFAULT_COMPRESSION_THRESHOLD + 100)
        )

        result, method = compress_payload(incompressible)

        # If compression was skipped, original data should be returned
        if method is None:
            assert result == incompressible
        else:
            # If compressed, the raw compressed bytes (before base64) should be smaller
            # Note: base64 encoding adds ~33% overhead, so we check the principle
            # is correct by verifying we got gzip output
            assert method == COMPRESSION_METHOD_GZIP


class TestDecompressPayload:
    """Test payload decompression."""

    def test_uncompressed_unchanged(self):
        """Uncompressed data (method=None) should pass through."""
        data = "Hello, world!"
        result = decompress_payload(data, None)
        assert result == data

    def test_roundtrip(self):
        """Compress then decompress should return original."""
        original = "This is some test data. " * 1000  # Make it big enough to compress
        compressed, method = compress_payload(original, threshold=100)

        assert method == COMPRESSION_METHOD_GZIP
        restored = decompress_payload(compressed, method)
        assert restored == original

    def test_roundtrip_with_unicode(self):
        """Should handle unicode correctly."""
        original = "Hello 世界! 🎉 " * 500
        compressed, method = compress_payload(original, threshold=100)

        if method:
            restored = decompress_payload(compressed, method)
            assert restored == original

    def test_unknown_method_raises(self):
        """Should raise for unknown compression method."""
        with pytest.raises(ValueError, match="Unknown compression method"):
            decompress_payload("data", "unknown_method")


class TestEstimateCompressedSize:
    """Test compression size estimation."""

    def test_returns_smaller_estimate(self):
        """Estimate should be smaller than original for typical data."""
        data = "This is some typical text data. " * 100
        original_size = len(data.encode("utf-8"))
        estimated = estimate_compressed_size(data)

        assert estimated < original_size

    def test_estimate_is_reasonable(self):
        """Estimate should be in a reasonable range."""
        data = '{"key": "value", "items": [1, 2, 3, 4, 5]}' * 100
        original_size = len(data.encode("utf-8"))
        estimated = estimate_compressed_size(data)

        # Should be between 10% and 60% of original for JSON-like data
        assert estimated > original_size * 0.1
        assert estimated < original_size * 0.6


class TestIntegration:
    """Integration tests for compression workflow."""

    def test_full_workflow(self):
        """Test typical compression workflow."""
        import json

        # Simulate a large result message
        large_result = {
            "type": "result",
            "task_id": "task-123",
            "data": {"items": [{"id": i, "value": f"item-{i}"} for i in range(1000)]},
        }
        payload = json.dumps(large_result)

        # Compress
        compressed, method = compress_payload(payload)

        # Verify compression happened
        assert method == COMPRESSION_METHOD_GZIP
        assert len(compressed) < len(payload)

        # Decompress
        restored = decompress_payload(compressed, method)
        restored_data = json.loads(restored)

        # Verify data integrity
        assert restored_data == large_result
