"""MD5 cache for efficient file change detection.

This module provides a cache for file MD5 hashes to avoid recomputing
them on every sync operation. The cache stores MD5 values keyed by
a hash of the file path, allowing fast lookups.

Cache location: ~/.silica/cache/memory-md5/
Cache key: MD5(file_path) → filename in cache
Cache value: MD5(file_content)
"""

import hashlib
import json
from pathlib import Path
from typing import Optional


class MD5Cache:
    """Cache for MD5 hashes of files.

    The cache maps file paths to their MD5 hashes. To avoid filesystem
    issues with special characters in paths, the cache filename is the
    MD5 hash of the path itself.

    File structure:
        ~/.silica/cache/memory-md5/<md5_of_path>.json
        Contains: {"path": "original/path", "md5": "content_md5", "mtime": 123.456}
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize MD5 cache.

        Args:
            cache_dir: Optional cache directory. If None, uses default
                      (~/.silica/cache/memory-md5/)
        """
        if cache_dir is None:
            cache_dir = Path.home() / ".silica" / "cache" / "memory-md5"

        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, file_path: Path) -> Path:
        """Get cache file path for a given file path.

        Args:
            file_path: Original file path

        Returns:
            Path to cache file
        """
        # Use MD5 of the file path as the cache filename
        path_hash = hashlib.md5(str(file_path).encode()).hexdigest()
        return self.cache_dir / f"{path_hash}.json"

    def get(self, file_path: Path) -> Optional[str]:
        """Get cached MD5 for a file if still valid.

        Args:
            file_path: File to get MD5 for

        Returns:
            Cached MD5 if valid, None otherwise
        """
        if not file_path.exists():
            return None

        cache_path = self._get_cache_path(file_path)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, "r") as f:
                cache_entry = json.load(f)

            # Verify the cache is for the same file
            if cache_entry.get("path") != str(file_path):
                return None

            # Check if file has been modified since cache
            current_mtime = file_path.stat().st_mtime
            cached_mtime = cache_entry.get("mtime")

            if cached_mtime is None or current_mtime != cached_mtime:
                # File modified, cache invalid
                return None

            return cache_entry.get("md5")

        except (OSError, json.JSONDecodeError, KeyError):
            # Cache corrupted or unreadable
            return None

    def set(self, file_path: Path, md5: str) -> None:
        """Store MD5 in cache for a file.

        Args:
            file_path: File to cache MD5 for
            md5: MD5 hash of file content
        """
        if not file_path.exists():
            return

        cache_path = self._get_cache_path(file_path)

        cache_entry = {
            "path": str(file_path),
            "md5": md5,
            "mtime": file_path.stat().st_mtime,
        }

        try:
            with open(cache_path, "w") as f:
                json.dump(cache_entry, f)
        except OSError:
            # If cache write fails, just continue without caching
            pass

    def invalidate(self, file_path: Path) -> None:
        """Invalidate cache entry for a file.

        Args:
            file_path: File to invalidate cache for
        """
        cache_path = self._get_cache_path(file_path)
        if cache_path.exists():
            try:
                cache_path.unlink()
            except OSError:
                pass

    def clear(self) -> int:
        """Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        count = 0
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                cache_file.unlink()
                count += 1
            except OSError:
                pass
        return count

    def cleanup_deleted_files(self) -> int:
        """Remove cache entries for files that no longer exist.

        This is useful for cleaning up cache entries for files that were
        deleted outside the sync system. MD5s themselves don't go stale -
        they're deterministic hashes - but cache entries can become orphaned
        when files are deleted.

        Returns:
            Number of entries removed
        """
        count = 0

        for cache_file in self.cache_dir.glob("*.json"):
            try:
                # Check if original file still exists
                with open(cache_file, "r") as f:
                    cache_entry = json.load(f)

                original_path = Path(cache_entry.get("path", ""))
                if not original_path.exists():
                    cache_file.unlink()
                    count += 1

            except (OSError, json.JSONDecodeError, KeyError):
                # Cache file corrupted, remove it
                try:
                    cache_file.unlink()
                    count += 1
                except OSError:
                    pass

        return count

    def calculate_md5(self, file_path: Path) -> str:
        """Calculate MD5 of file, using cache if valid.

        This is the main method to use - it handles caching transparently.

        Args:
            file_path: File to calculate MD5 for

        Returns:
            MD5 hash of file content

        Raises:
            FileNotFoundError: If file doesn't exist
            OSError: If file cannot be read
        """
        # Try cache first
        cached_md5 = self.get(file_path)
        if cached_md5 is not None:
            return cached_md5

        # Calculate MD5
        md5_hash = hashlib.md5()
        with open(file_path, "rb") as f:
            # Read in chunks for memory efficiency
            for chunk in iter(lambda: f.read(8192), b""):
                md5_hash.update(chunk)

        md5 = md5_hash.hexdigest()

        # Cache the result
        self.set(file_path, md5)

        return md5


# Global cache instance for convenience
_global_cache: Optional[MD5Cache] = None


def get_global_cache() -> MD5Cache:
    """Get the global MD5 cache instance.

    Returns:
        Global MD5Cache instance
    """
    global _global_cache
    if _global_cache is None:
        _global_cache = MD5Cache()
    return _global_cache
