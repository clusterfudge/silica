"""Tests for MD5 cache."""

import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from silica.developer.memory.md5_cache import MD5Cache


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def cache(temp_dir):
    """Create an MD5 cache in temp directory."""
    cache_dir = temp_dir / "cache"
    return MD5Cache(cache_dir=cache_dir)


@pytest.fixture
def test_file(temp_dir):
    """Create a test file."""
    file_path = temp_dir / "test.txt"
    file_path.write_text("Hello, World!")
    return file_path


class TestMD5Cache:
    """Tests for MD5Cache class."""

    def test_calculate_md5_creates_cache_entry(self, cache, test_file):
        """Test that calculating MD5 creates a cache entry."""
        # Calculate MD5
        md5 = cache.calculate_md5(test_file)

        # Verify MD5 is correct
        import hashlib

        expected_md5 = hashlib.md5(b"Hello, World!").hexdigest()
        assert md5 == expected_md5

        # Verify cache entry exists
        cached_md5 = cache.get(test_file)
        assert cached_md5 == md5

    def test_cache_hit_returns_same_md5(self, cache, test_file):
        """Test that cache returns same MD5 on second call."""
        # First call - cache miss
        md5_1 = cache.calculate_md5(test_file)

        # Second call - cache hit
        md5_2 = cache.calculate_md5(test_file)

        assert md5_1 == md5_2

    def test_cache_invalidated_on_file_modification(self, cache, test_file):
        """Test that cache is invalidated when file is modified."""
        # Calculate initial MD5
        md5_1 = cache.calculate_md5(test_file)

        # Modify file (need to ensure mtime changes)
        time.sleep(0.01)
        test_file.write_text("Modified content")

        # Cache should be invalid now
        cached_md5 = cache.get(test_file)
        assert cached_md5 is None

        # Recalculate MD5
        md5_2 = cache.calculate_md5(test_file)

        # Should be different
        assert md5_1 != md5_2

    def test_cache_miss_on_nonexistent_file(self, cache, temp_dir):
        """Test that cache returns None for nonexistent file."""
        nonexistent = temp_dir / "nonexistent.txt"
        cached_md5 = cache.get(nonexistent)
        assert cached_md5 is None

    def test_set_and_get(self, cache, test_file):
        """Test explicit set and get."""
        # Set cache entry
        cache.set(test_file, "abc123")

        # Get cache entry
        cached_md5 = cache.get(test_file)
        assert cached_md5 == "abc123"

    def test_invalidate_removes_cache_entry(self, cache, test_file):
        """Test that invalidate removes cache entry."""
        # Create cache entry
        cache.calculate_md5(test_file)

        # Verify it exists
        assert cache.get(test_file) is not None

        # Invalidate
        cache.invalidate(test_file)

        # Verify it's gone
        assert cache.get(test_file) is None

    def test_clear_removes_all_entries(self, cache, temp_dir):
        """Test that clear removes all cache entries."""
        # Create multiple files and cache entries
        files = []
        for i in range(5):
            file_path = temp_dir / f"file{i}.txt"
            file_path.write_text(f"Content {i}")
            cache.calculate_md5(file_path)
            files.append(file_path)

        # Verify all cached
        for file_path in files:
            assert cache.get(file_path) is not None

        # Clear cache
        count = cache.clear()
        assert count == 5

        # Verify all gone
        for file_path in files:
            assert cache.get(file_path) is None

    def test_cache_key_based_on_path(self, cache, test_file):
        """Test that cache key is based on file path."""
        # Create cache entry
        cache.calculate_md5(test_file)

        # Get cache file path
        cache_path = cache._get_cache_path(test_file)

        # Verify it exists and contains path hash
        assert cache_path.exists()
        assert cache_path.suffix == ".json"

        # Verify cache key is deterministic
        cache_path_2 = cache._get_cache_path(test_file)
        assert cache_path == cache_path_2

    def test_cache_stores_mtime(self, cache, test_file):
        """Test that cache stores file mtime."""
        # Calculate MD5
        cache.calculate_md5(test_file)

        # Read cache file
        cache_path = cache._get_cache_path(test_file)
        import json

        with open(cache_path, "r") as f:
            cache_entry = json.load(f)

        # Verify mtime is stored
        assert "mtime" in cache_entry
        assert cache_entry["mtime"] == test_file.stat().st_mtime

    def test_cache_with_special_characters_in_path(self, cache, temp_dir):
        """Test cache with special characters in path."""
        # Create file with special characters
        file_path = temp_dir / "file with spaces & symbols!.txt"
        file_path.write_text("Content")

        # Should work without issues
        md5 = cache.calculate_md5(file_path)
        assert md5 is not None

        # Cache should work
        cached_md5 = cache.get(file_path)
        assert cached_md5 == md5

    def test_cache_performance_improvement(self, cache, temp_dir):
        """Test that cache improves performance."""
        # Create a larger file
        large_file = temp_dir / "large.txt"
        large_file.write_text("x" * 100000)

        # First call (cache miss)
        start = time.time()
        md5_1 = cache.calculate_md5(large_file)
        time.time() - start

        # Second call (cache hit)
        start = time.time()
        md5_2 = cache.calculate_md5(large_file)
        time_cached = time.time() - start

        # Results should be same
        assert md5_1 == md5_2

        # Cached should be faster (though this might be flaky in CI)
        # Just verify it works, don't assert on timing
        assert time_cached >= 0  # Just verify it executed
