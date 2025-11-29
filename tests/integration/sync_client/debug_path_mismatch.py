"""Debug script to understand path mismatch in sync."""

import tempfile
from pathlib import Path
from silica.developer.memory.sync_config import SyncConfig
from silica.developer.memory.sync import SyncEngine
from silica.developer.memory.proxy_client import MemoryProxyClient

# Set up temp directory
temp_dir = Path(tempfile.mkdtemp())
persona_dir = temp_dir / "personas" / "test-persona"
memory_dir = persona_dir / "memory"
memory_dir.mkdir(parents=True)

# Create test files
(memory_dir / "test.md").write_text("test content")
(persona_dir / "persona.md").write_text("Test Persona")

# Create sync config
namespace = "test-namespace/memory"
config = SyncConfig(
    namespace=namespace,
    scan_paths=[
        persona_dir / "memory",
        persona_dir / "persona.md",
    ],
    index_file=persona_dir / ".sync-index-memory.json",
    base_dir=persona_dir,
)

# Create mock client (we'll use conftest's mock)
client = MemoryProxyClient(base_url="http://localhost:9876", token="test-token")

# Create sync engine
engine = SyncEngine(client=client, config=config)

# Scan local files
print("=== Scanning local files ===")
local_files = engine._scan_local_files()
for path, info in local_files.items():
    print(f"  {path}: md5={info.md5[:8]}, size={info.size}")

print("\n=== Config ===")
print(f"base_dir: {config.base_dir}")
print(f"scan_paths: {config.scan_paths}")
print(f"namespace: {config.namespace}")

# Now simulate what happens after upload
print("\n=== After simulated upload ===")
# Simulate returned sync_index - what keys would it have?
# When we upload path="memory/test.md" to namespace="test-namespace/memory",
# the remote stores it as "memory/test.md" in that namespace

# But wait - the namespace is "test-namespace/memory", so maybe the remote
# strips the "memory/" part and just stores "test.md"?

print("\nQuestions:")
print("1. When we upload path='memory/test.md' to namespace='test-namespace/memory',")
print("   what key does the remote use in sync_index?")
print("2. Should it be 'test.md' or 'memory/test.md'?")
