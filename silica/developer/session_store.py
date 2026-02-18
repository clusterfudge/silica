"""Session storage module for the split history file format.

Provides read/write primitives for the v2 session file layout:
  session.json          — session-level metadata
  <agent>.history.jsonl  — append-only complete message log
  <agent>.metadata.jsonl — per-turn usage/model metadata
  <agent>.context.jsonl  — current context window (rewritten on compaction)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Format version for session.json
SESSION_FORMAT_VERSION = 2


class PydanticJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles Pydantic models and other special types."""

    def default(self, o):
        if hasattr(o, "model_dump"):
            return o.model_dump()
        if hasattr(o, "dict"):
            return o.dict()
        return super().default(o)


class SessionStore:
    """Manages reading and writing session history in the v2 split-file format.

    Each agent (root or sub-agent) within a session has its own set of
    history, metadata, and context files. The session directory also
    contains a shared ``session.json`` for session-level metadata.

    Args:
        session_dir: Path to the session directory.
        agent_name: Identifier for this agent. Use ``"root"`` for the root
            agent or the sub-agent's session ID for sub-agents.
    """

    # Regex to extract the sequence number from a msg_id.
    _MSG_ID_SEQ_RE = re.compile(r"_(\d+)$")

    def __init__(self, session_dir: Path, agent_name: str = "root") -> None:
        self.session_dir = Path(session_dir)
        self.agent_name = agent_name

        # Determine the msg_id prefix for this agent.
        if agent_name == "root":
            self._id_prefix = "m_"
        else:
            # Use first 8 chars of sub-agent ID to namespace IDs.
            self._id_prefix = f"m_{agent_name[:8]}_"

        # Initialise the sequence counter from existing history.
        self._msg_seq = self._init_msg_seq()

    # ------------------------------------------------------------------
    # File path helpers
    # ------------------------------------------------------------------

    @property
    def session_meta_path(self) -> Path:
        return self.session_dir / "session.json"

    @property
    def history_path(self) -> Path:
        return self.session_dir / f"{self.agent_name}.history.jsonl"

    @property
    def metadata_path(self) -> Path:
        return self.session_dir / f"{self.agent_name}.metadata.jsonl"

    @property
    def context_path(self) -> Path:
        return self.session_dir / f"{self.agent_name}.context.jsonl"

    # For root agent, use friendlier names without the "root." prefix.
    # Actually — keep consistent naming. The file is "root.history.jsonl".
    # Consumers look for "<agent_name>.history.jsonl".

    # ------------------------------------------------------------------
    # Message ID management
    # ------------------------------------------------------------------

    def _init_msg_seq(self) -> int:
        """Scan existing history file to find the highest sequence number."""
        if not self.history_path.exists():
            return 0
        max_seq = 0
        for line in self._read_jsonl(self.history_path):
            msg_id = line.get("msg_id", "")
            m = self._MSG_ID_SEQ_RE.search(msg_id)
            if m:
                max_seq = max(max_seq, int(m.group(1)))
        return max_seq

    def next_msg_id(self) -> str:
        """Return the next sequential msg_id and advance the counter."""
        self._msg_seq += 1
        return f"{self._id_prefix}{self._msg_seq:04d}"

    def peek_msg_id(self) -> str:
        """Return what the next msg_id would be without advancing."""
        return f"{self._id_prefix}{self._msg_seq + 1:04d}"

    @property
    def last_msg_id(self) -> str | None:
        """Return the most recently assigned msg_id, or None if none assigned."""
        if self._msg_seq == 0:
            return None
        return f"{self._id_prefix}{self._msg_seq:04d}"

    # ------------------------------------------------------------------
    # session.json — session-level metadata
    # ------------------------------------------------------------------

    def write_session_meta(self, data: dict[str, Any]) -> None:
        """Write or update session.json.

        Automatically sets ``version`` and manages ``created_at`` / ``last_updated``.
        """
        self.session_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()
        data.setdefault("version", SESSION_FORMAT_VERSION)
        data.setdefault("created_at", now)
        data["last_updated"] = now

        # Preserve original created_at if file exists.
        if self.session_meta_path.exists():
            try:
                existing = json.loads(self.session_meta_path.read_text())
                if "created_at" in existing:
                    data["created_at"] = existing["created_at"]
            except (json.JSONDecodeError, OSError):
                pass

        self.session_meta_path.write_text(
            json.dumps(data, indent=2, cls=PydanticJSONEncoder) + "\n"
        )

    def read_session_meta(self) -> dict[str, Any] | None:
        """Read session.json, or return None if it doesn't exist."""
        if not self.session_meta_path.exists():
            return None
        try:
            return json.loads(self.session_meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    # history.jsonl — append-only message log
    # ------------------------------------------------------------------

    def append_messages(
        self,
        messages: list[dict[str, Any]],
        prev_msg_id: str | None = None,
    ) -> list[str]:
        """Append messages to the history file with msg_id and prev_msg_id.

        Each message gets a sequential ``msg_id``. The ``prev_msg_id`` field
        creates a linked list: the first message uses the provided
        *prev_msg_id* (``None`` for root agents, parent's msg_id for
        sub-agents); subsequent messages chain to the previous one.

        Args:
            messages: List of message dicts (role + content, Anthropic format).
            prev_msg_id: The msg_id to use as prev_msg_id for the first message.

        Returns:
            List of assigned msg_ids (one per message).
        """
        if not messages:
            return []

        now = datetime.now(timezone.utc).isoformat()
        records: list[dict[str, Any]] = []
        assigned_ids: list[str] = []
        current_prev = prev_msg_id

        for msg in messages:
            msg_id = self.next_msg_id()
            record = {
                "msg_id": msg_id,
                "prev_msg_id": current_prev,
                "timestamp": now,
                **msg,
            }
            records.append(record)
            assigned_ids.append(msg_id)
            current_prev = msg_id

        self._append_jsonl(self.history_path, records)
        return assigned_ids

    def read_history(self) -> list[dict[str, Any]]:
        """Read the full history file."""
        return self._read_jsonl(self.history_path)

    # ------------------------------------------------------------------
    # metadata.jsonl — per-turn metadata
    # ------------------------------------------------------------------

    def append_metadata(self, entries: list[dict[str, Any]]) -> None:
        """Append usage/model metadata entries to the metadata file.

        Each entry should include a ``msg_id`` field linking it to the
        corresponding assistant message in history.jsonl.
        """
        if not entries:
            return
        now = datetime.now(timezone.utc).isoformat()
        for entry in entries:
            entry.setdefault("timestamp", now)
        self._append_jsonl(self.metadata_path, entries)

    def read_metadata(self) -> list[dict[str, Any]]:
        """Read the full metadata file."""
        return self._read_jsonl(self.metadata_path)

    # ------------------------------------------------------------------
    # <agent>.context.jsonl — current context window
    # ------------------------------------------------------------------

    def write_context(self, messages: list[dict[str, Any]]) -> None:
        """Overwrite the context file with the current context window."""
        self._write_jsonl(self.context_path, messages)

    def read_context(self) -> list[dict[str, Any]]:
        """Read the current context window."""
        return self._read_jsonl(self.context_path)

    # ------------------------------------------------------------------
    # Legacy detection
    # ------------------------------------------------------------------

    def is_legacy(self) -> bool:
        """Return True if this session uses the legacy root.json format."""
        root_json = self.session_dir / "root.json"
        return root_json.exists() and not self.session_meta_path.exists()

    # ------------------------------------------------------------------
    # JSONL I/O helpers
    # ------------------------------------------------------------------

    def _append_jsonl(self, path: Path, records: list[dict[str, Any]]) -> None:
        """Append records to a JSONL file (one JSON object per line)."""
        self.session_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, cls=PydanticJSONEncoder) + "\n")

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict[str, Any]]:
        """Read all records from a JSONL file.

        Silently skips blank lines and lines that fail to parse.
        """
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # skip corrupted lines gracefully
        return records

    @staticmethod
    def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
        """Overwrite a JSONL file with the given records."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, cls=PydanticJSONEncoder) + "\n")


# ------------------------------------------------------------------
# Migration: legacy root.json → v2 split files
# ------------------------------------------------------------------


def migrate_session(session_dir: Path, dry_run: bool = False) -> dict[str, Any]:
    """Migrate a legacy session (root.json) to the v2 split-file format.

    Steps:
    1. Read root.json
    2. Write session.json (metadata)
    3. Write root.history.jsonl (all messages with msg_ids)
    4. Write root.metadata.jsonl (usage paired with assistant msg_ids)
    5. Write root.context.jsonl (same as history — no compaction yet)
    6. Rename root.json → root.json.legacy
    7. Migrate pre-compaction-*.json → pre-compaction-*.context.jsonl
    8. Migrate sub-agent *.json → *.history.jsonl + *.context.jsonl

    Args:
        session_dir: Path to the session directory containing root.json.
        dry_run: If True, report what would happen but don't write files.

    Returns:
        Dict with migration stats: message_count, usage_count, files_created, etc.

    Raises:
        FileNotFoundError: If root.json doesn't exist.
        ValueError: If session is already in v2 format.
    """
    session_dir = Path(session_dir)
    root_file = session_dir / "root.json"
    session_json = session_dir / "session.json"

    if session_json.exists():
        raise ValueError(
            f"Session already in v2 format (session.json exists): {session_dir}"
        )

    if not root_file.exists():
        raise FileNotFoundError(f"No root.json found in {session_dir}")

    # Read legacy data
    with open(root_file, "r", encoding="utf-8") as f:
        legacy_data = json.load(f)

    messages = legacy_data.get("messages", [])
    usage_data = legacy_data.get("usage", [])

    stats = {
        "session_dir": str(session_dir),
        "message_count": len(messages),
        "usage_count": len(usage_data),
        "files_created": [],
        "files_renamed": [],
        "dry_run": dry_run,
    }

    if dry_run:
        stats["files_created"] = [
            "session.json",
            "root.history.jsonl",
            "root.metadata.jsonl",
            "root.context.jsonl",
        ]
        stats["files_renamed"] = [("root.json", "root.json.legacy")]
        # Check for pre-compaction archives
        for f in session_dir.iterdir():
            if f.name.startswith("pre-compaction-") and f.suffix == ".json":
                stats["files_created"].append(f.stem + ".context.jsonl")
                stats["files_renamed"].append((f.name, f.name + ".legacy"))
        return stats

    # Create store for root agent
    store = SessionStore(session_dir, agent_name="root")

    # 1. Write history.jsonl with msg_ids
    msg_ids = store.append_messages(messages, prev_msg_id=None)
    stats["files_created"].append("root.history.jsonl")

    # 2. Write metadata.jsonl — pair usage with assistant msg_ids
    if usage_data:
        metadata_entries = []
        # Find assistant message msg_ids for pairing
        assistant_msg_ids = [
            mid for mid, msg in zip(msg_ids, messages) if msg.get("role") == "assistant"
        ]
        for i, (usage_entry, model_spec_entry) in enumerate(usage_data):
            entry = {}
            if isinstance(usage_entry, dict):
                entry["usage"] = usage_entry
            else:
                entry["usage"] = {"raw": str(usage_entry)}
            if isinstance(model_spec_entry, dict):
                entry["model"] = model_spec_entry.get("title", "unknown")
                entry["model_spec"] = model_spec_entry
            else:
                entry["model"] = "unknown"
                entry["model_spec"] = model_spec_entry
            # Pair with assistant msg_id if available
            if i < len(assistant_msg_ids):
                entry["msg_id"] = assistant_msg_ids[i]
            metadata_entries.append(entry)
        store.append_metadata(metadata_entries)
    stats["files_created"].append("root.metadata.jsonl")

    # 3. Write context.jsonl (same as messages for un-compacted, or just messages for compacted)
    store.write_context(messages)
    stats["files_created"].append("root.context.jsonl")

    # 4. Write session.json
    session_meta = {
        "session_id": legacy_data.get("session_id", session_dir.name),
        "parent_session_id": legacy_data.get("parent_session_id"),
        "model_spec": legacy_data.get("model_spec"),
        "thinking_mode": legacy_data.get("thinking_mode", "max"),
        "active_plan_id": legacy_data.get("active_plan_id"),
        "root_dir": legacy_data.get("metadata", {}).get("root_dir"),
        "cli_args": legacy_data.get("metadata", {}).get("cli_args"),
        "migrated_from": "root.json",
    }
    # Preserve compaction info
    if "compaction" in legacy_data:
        session_meta["compaction"] = legacy_data["compaction"]
    # Preserve created_at
    if "metadata" in legacy_data and "created_at" in legacy_data["metadata"]:
        session_meta["created_at"] = legacy_data["metadata"]["created_at"]
    store.write_session_meta(session_meta)
    stats["files_created"].append("session.json")

    # 5. Rename root.json → root.json.legacy
    root_file.rename(session_dir / "root.json.legacy")
    stats["files_renamed"].append(("root.json", "root.json.legacy"))

    # 6. Migrate pre-compaction archives
    for f in sorted(session_dir.iterdir()):
        if f.name.startswith("pre-compaction-") and f.suffix == ".json":
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    archive_data = json.load(fh)
                archive_messages = archive_data.get("messages", [])
                # Write as context.jsonl
                new_name = f.stem + ".context.jsonl"
                SessionStore._write_jsonl(session_dir / new_name, archive_messages)
                stats["files_created"].append(new_name)
                # Rename original
                f.rename(session_dir / (f.name + ".legacy"))
                stats["files_renamed"].append((f.name, f.name + ".legacy"))
            except (json.JSONDecodeError, OSError):
                continue  # skip corrupted archives

    # 7. Migrate sub-agent files (*.json that aren't root.json or pre-compaction)
    for f in sorted(session_dir.iterdir()):
        if (
            f.suffix == ".json"
            and f.name != "session.json"
            and not f.name.startswith("pre-compaction-")
            and f.name != "root.json.legacy"
        ):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    sub_data = json.load(fh)
                sub_messages = sub_data.get("messages", [])
                sub_id = f.stem  # e.g., "abc-123-def"
                sub_store = SessionStore(session_dir, agent_name=sub_id)
                sub_store.append_messages(sub_messages, prev_msg_id=None)
                sub_store.write_context(sub_messages)
                stats["files_created"].extend(
                    [
                        f"{sub_id}.history.jsonl",
                        f"{sub_id}.context.jsonl",
                    ]
                )
                f.rename(session_dir / (f.name + ".legacy"))
                stats["files_renamed"].append((f.name, f.name + ".legacy"))
            except (json.JSONDecodeError, OSError):
                continue

    return stats


def migrate_all_sessions(
    history_base_dir: Path,
    dry_run: bool = False,
    progress_callback=None,
) -> list[dict[str, Any]]:
    """Migrate all legacy sessions under a base directory.

    Args:
        history_base_dir: Base dir containing history/ subdirectory.
        dry_run: If True, report what would happen.
        progress_callback: Optional callable(session_dir, index, total) for progress.

    Returns:
        List of migration stats dicts (one per session).
    """
    history_dir = history_base_dir / "history"
    if not history_dir.exists():
        return []

    # Find all sessions that need migration
    sessions_to_migrate = []
    for session_dir in sorted(history_dir.iterdir()):
        if not session_dir.is_dir():
            continue
        root_file = session_dir / "root.json"
        session_json = session_dir / "session.json"
        if root_file.exists() and not session_json.exists():
            sessions_to_migrate.append(session_dir)

    results = []
    total = len(sessions_to_migrate)
    for i, session_dir in enumerate(sessions_to_migrate):
        if progress_callback:
            progress_callback(session_dir, i, total)
        try:
            stats = migrate_session(session_dir, dry_run=dry_run)
            stats["status"] = "ok"
        except Exception as e:
            stats = {
                "session_dir": str(session_dir),
                "status": "error",
                "error": str(e),
            }
        results.append(stats)

    return results
