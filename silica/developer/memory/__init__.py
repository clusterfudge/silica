"""Memory management and synchronization.

This module provides memory management capabilities including:
- MemoryManager: Local memory storage and retrieval
- MemoryProxyClient: HTTP client for remote memory proxy
- MemoryProxyConfig: Configuration for remote sync
- SyncStrategy: Strategy pattern for transparent sync integration
"""

from silica.developer.memory.manager import MemoryManager
from silica.developer.memory.proxy_client import (
    AuthenticationError,
    ConnectionError,
    FileMetadata,
    MemoryProxyClient,
    MemoryProxyError,
    NotFoundError,
    SyncIndexResponse,
    VersionConflictError,
)
from silica.developer.memory.proxy_config import MemoryProxyConfig
from silica.developer.memory.sync_strategy import (
    NoOpSync,
    RemoteSync,
    SyncStrategy,
    create_sync_strategy,
)

__all__ = [
    # Memory Manager
    "MemoryManager",
    # Proxy Client
    "MemoryProxyClient",
    "FileMetadata",
    "SyncIndexResponse",
    # Proxy Config
    "MemoryProxyConfig",
    # Sync Strategy
    "SyncStrategy",
    "NoOpSync",
    "RemoteSync",
    "create_sync_strategy",
    # Exceptions
    "MemoryProxyError",
    "ConnectionError",
    "AuthenticationError",
    "VersionConflictError",
    "NotFoundError",
]
