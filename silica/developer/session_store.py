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
