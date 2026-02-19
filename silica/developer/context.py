import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from anthropic.types import Usage, MessageParam

from silica.developer.models import ModelSpec
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.user_interface import UserInterface
from pydantic import BaseModel
from silica.developer.memory import MemoryManager

# Keys added by SessionStore or the agent loop that must be stripped before
# sending messages to the Anthropic API (which rejects extra fields).
_INTERNAL_MSG_KEYS = frozenset({"msg_id", "prev_msg_id", "timestamp", "anthropic_id"})
from silica.developer.session_store import SessionStore, PydanticJSONEncoder


def _find_root_dir() -> str:
    """Find the git repo root or fall back to cwd."""
    try:
        current_dir = os.path.abspath(os.getcwd())
        d = current_dir
        while d != os.path.dirname(d):
            if os.path.isdir(os.path.join(d, ".git")):
                return d
            d = os.path.dirname(d)
        return current_dir
    except Exception:
        return os.path.abspath(os.getcwd())


@dataclass
class AgentContext:
    parent_session_id: str | None
    session_id: str
    model_spec: ModelSpec
    sandbox: Sandbox
    user_interface: UserInterface
    usage: list[tuple[Any, Any]]
    memory_manager: "MemoryManager"
    cli_args: list[str] = None
    thinking_mode: str = "max"  # "off", "normal", "ultra", or "max"
    history_base_dir: Path | None = None
    active_plan_id: str | None = None
    toolbox: Any = None
    _chat_history: list[MessageParam] = None
    _tool_result_buffer: list[dict] = None
    # v2 storage tracking
    _session_store: SessionStore | None = field(default=None, repr=False)
    _last_flushed_msg_count: int = 0
    _last_flushed_usage_count: int = 0

    def __post_init__(self):
        if self._chat_history is None:
            self._chat_history = []
        if self._tool_result_buffer is None:
            self._tool_result_buffer = []

    def _get_history_dir(self) -> Path:
        """Get the history directory for this context."""
        if self.history_base_dir:
            base = (
                Path(self.history_base_dir)
                if not isinstance(self.history_base_dir, Path)
                else self.history_base_dir
            )
        else:
            base = Path.home() / ".silica" / "personas" / "default"
        context_dir = (
            self.parent_session_id if self.parent_session_id else self.session_id
        )
        return base / "history" / context_dir

    def _get_or_create_store(self) -> SessionStore:
        """Get or lazily create the SessionStore for this context."""
        if self._session_store is None:
            history_dir = self._get_history_dir()
            agent_name = "root" if self.parent_session_id is None else self.session_id
            self._session_store = SessionStore(history_dir, agent_name=agent_name)
        return self._session_store

    @property
    def chat_history(self) -> list[MessageParam]:
        return self._chat_history

    @property
    def tool_result_buffer(self) -> list[dict]:
        return self._tool_result_buffer

    @staticmethod
    def create(
        model_spec: ModelSpec,
        sandbox_mode: SandboxMode,
        sandbox_contents: list[str],
        user_interface: UserInterface,
        session_id: str = None,
        cli_args: list[str] = None,
        persona_base_directory: Path = None,
    ) -> "AgentContext":
        sandbox = Sandbox(
            sandbox_contents[0] if sandbox_contents else os.getcwd(),
            mode=sandbox_mode,
            permission_check_callback=user_interface.permission_callback,
            permission_check_rendering_callback=user_interface.permission_rendering_callback,
        )
        memory_manager = MemoryManager(base_dir=persona_base_directory / "memory")
        context_session_id = session_id if session_id else str(uuid4())

        context = AgentContext(
            session_id=context_session_id,
            parent_session_id=None,
            model_spec=model_spec,
            sandbox=sandbox,
            user_interface=user_interface,
            usage=[],
            memory_manager=memory_manager,
            cli_args=cli_args.copy() if cli_args else None,
            history_base_dir=persona_base_directory,
        )

        if session_id:
            loaded_context = load_session_data(
                session_id, context, history_base_dir=persona_base_directory
            )
            if loaded_context and loaded_context.chat_history:
                user_interface.handle_system_message(
                    f"Resumed session {session_id} with {len(loaded_context.chat_history)} messages"
                )
                return loaded_context
            else:
                user_interface.handle_system_message(
                    "Starting new session.", markdown=False
                )

        return context

    def with_user_interface(
        self, user_interface: UserInterface, keep_history=False, session_id: str = None
    ) -> "AgentContext":
        # Capture parent's last msg_id for sub-agent prev_msg_id linking
        parent_last_msg_id = None
        if self._session_store is not None:
            parent_last_msg_id = self._session_store.last_msg_id

        child = AgentContext(
            session_id=session_id if session_id else str(uuid4()),
            parent_session_id=self.session_id,
            model_spec=self.model_spec,
            sandbox=self.sandbox,
            user_interface=user_interface,
            usage=self.usage,
            memory_manager=self.memory_manager,
            cli_args=self.cli_args.copy() if self.cli_args else None,
            history_base_dir=self.history_base_dir,
            _chat_history=self.chat_history.copy() if keep_history else [],
            _tool_result_buffer=self.tool_result_buffer.copy() if keep_history else [],
        )
        # Store parent's msg_id so the sub-agent's first message can link back
        child._parent_msg_id = parent_last_msg_id
        return child

    def _report_usage(self, usage: Usage, model_spec: ModelSpec):
        self.usage.append((usage, model_spec))

    def report_usage(self, usage: Usage, model_spec: ModelSpec | None = None):
        self._report_usage(usage, model_spec or self.model_spec)

    def _prop_or_dict_entry(self, obj, name):
        if hasattr(obj, name):
            return getattr(obj, name)
        else:
            return obj[name]

    def get_api_context(self, tool_names: list[str] | None = None) -> dict[str, Any]:
        """Get the complete context that would be sent to the Anthropic API."""
        from silica.developer.prompt import create_system_message
        from silica.developer.toolbox import Toolbox
        from silica.developer.agent_loop import _process_file_mentions

        system_message = create_system_message(self)
        if hasattr(self, "toolbox") and self.toolbox is not None and tool_names is None:
            tools = self.toolbox.agent_schema
        else:
            toolbox = Toolbox(self, tool_names=tool_names, show_warnings=False)
            tools = toolbox.agent_schema
        processed_messages = _process_file_mentions(self.chat_history, self)
        return {
            "system": system_message,
            "tools": tools,
            "messages": processed_messages,
        }

    def usage_summary(self) -> dict[str, Any]:
        usage_summary = {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_thinking_tokens": 0,
            "total_cost": 0.0,
            "thinking_cost": 0.0,
            "cached_tokens": 0,
            "model_breakdown": {},
        }
        for usage_entry, model_spec in self.usage:
            model_name = model_spec["title"]
            pricing = model_spec["pricing"]
            cache_pricing = model_spec["cache_pricing"]
            thinking_pricing = model_spec.get("thinking_pricing", {"thinking": 0.0})

            input_tokens = self._prop_or_dict_entry(usage_entry, "input_tokens")
            output_tokens = self._prop_or_dict_entry(usage_entry, "output_tokens")
            cache_creation_input_tokens = self._prop_or_dict_entry(
                usage_entry, "cache_creation_input_tokens"
            )
            cache_read_input_tokens = self._prop_or_dict_entry(
                usage_entry, "cache_read_input_tokens"
            )

            thinking_tokens = 0
            if hasattr(usage_entry, "thinking_tokens"):
                thinking_tokens = usage_entry.thinking_tokens
            elif isinstance(usage_entry, dict) and "thinking_tokens" in usage_entry:
                thinking_tokens = usage_entry["thinking_tokens"]

            usage_summary["total_input_tokens"] += input_tokens
            usage_summary["total_output_tokens"] += output_tokens
            usage_summary["total_thinking_tokens"] += thinking_tokens
            usage_summary["cached_tokens"] += cache_read_input_tokens

            thinking_cost = thinking_tokens * thinking_pricing["thinking"]
            total_cost = (
                input_tokens * pricing["input"]
                + output_tokens * pricing["output"]
                + cache_pricing["read"] * cache_read_input_tokens
                + cache_pricing["write"] * cache_creation_input_tokens
                + thinking_cost
            )

            if model_name not in usage_summary["model_breakdown"]:
                usage_summary["model_breakdown"][model_name] = {
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_thinking_tokens": 0,
                    "total_cost": 0.0,
                    "thinking_cost": 0.0,
                    "cached_tokens": 0,
                    "token_breakdown": {},
                }
            mb = usage_summary["model_breakdown"][model_name]
            mb["total_input_tokens"] += input_tokens
            mb["total_output_tokens"] += output_tokens
            mb["total_thinking_tokens"] += thinking_tokens
            mb["cached_tokens"] += cache_read_input_tokens
            mb["total_cost"] += total_cost
            mb["thinking_cost"] += thinking_cost
            usage_summary["total_cost"] += total_cost
            usage_summary["thinking_cost"] += thinking_cost

        usage_summary["total_cost"] /= 1_000_000
        usage_summary["thinking_cost"] /= 1_000_000
        for mb in usage_summary["model_breakdown"].values():
            mb["total_cost"] /= 1_000_000
            mb["thinking_cost"] /= 1_000_000
        return usage_summary

    def rotate(
        self,
        archive_suffix: str,
        new_messages: list[MessageParam],
        compaction_metadata: dict | None = None,
    ) -> str:
        """Archive the current conversation and update with compacted messages.

        For root contexts only. Archives the current context file, then writes
        compacted messages as the new context.
        """
        if self.parent_session_id is not None:
            raise ValueError(
                "rotate() can only be called on root contexts, not sub-agent contexts"
            )

        store = self._get_or_create_store()
        history_dir = self._get_history_dir()

        # Archive the current context file
        archive_ctx = history_dir / f"{archive_suffix}.context.jsonl"
        if store.context_path.exists():
            import shutil

            shutil.copy2(store.context_path, archive_ctx)

        # Also archive legacy root.json if it exists (transition period)
        root_file = history_dir / "root.json"
        if root_file.exists():
            archive_json = history_dir / f"{archive_suffix}.json"
            try:
                with open(root_file, "r") as f:
                    existing_data = json.load(f)
                with open(archive_json, "w") as f:
                    json.dump(existing_data, f, indent=2)
            except (json.JSONDecodeError, FileNotFoundError):
                pass

        # Update context in place
        self._chat_history = new_messages
        self._tool_result_buffer.clear()
        # Reset flush counters — compacted context is a fresh start
        self._last_flushed_msg_count = 0
        self._last_flushed_usage_count = len(self.usage)
        self.flush(new_messages, compact=False)

        if compaction_metadata:
            self._compaction_metadata = compaction_metadata

        return f"{archive_suffix}.context.jsonl"

    def compact_in_place(
        self,
        new_messages: list[MessageParam],
        compaction_metadata: dict | None = None,
    ) -> None:
        """Replace conversation history with compacted messages (no archive)."""
        self._chat_history = new_messages
        self._tool_result_buffer.clear()
        # Reset flush counters
        self._last_flushed_msg_count = 0
        self._last_flushed_usage_count = len(self.usage)
        self.flush(new_messages, compact=False)

        if compaction_metadata:
            self._compaction_metadata = compaction_metadata

    def flush(self, chat_history, compact=True):
        """Save agent context and chat history using the v2 split-file format.

        Writes:
        - New messages to <agent>.history.jsonl (append-only)
        - New usage entries to <agent>.metadata.jsonl (append-only)
        - Full current context to <agent>.context.jsonl (overwrite)
        - Session metadata to session.json (overwrite)
        - Legacy root.json for backward compatibility (overwrite)
        """
        if not chat_history:
            return

        store = self._get_or_create_store()
        history_dir = self._get_history_dir()
        history_dir.mkdir(parents=True, exist_ok=True)

        # --- v2 format: split files ---

        # 1. Append NEW messages to history.jsonl
        new_msg_count = len(chat_history)
        if new_msg_count > self._last_flushed_msg_count:
            new_messages = chat_history[self._last_flushed_msg_count :]
            # Chain from last written msg, or parent's msg_id for first sub-agent flush
            prev_id = store.last_msg_id
            if prev_id is None and hasattr(self, "_parent_msg_id"):
                prev_id = self._parent_msg_id
            store.append_messages(new_messages, prev_msg_id=prev_id)

        # 2. Append NEW usage entries to metadata.jsonl
        new_usage_count = len(self.usage)
        if new_usage_count > self._last_flushed_usage_count:
            new_usage = self.usage[self._last_flushed_usage_count :]
            metadata_entries = []
            for usage_entry, model_spec_entry in new_usage:
                entry = {"model": model_spec_entry.get("title", "unknown")}
                # Serialize usage — handle both SDK objects and dicts
                if hasattr(usage_entry, "model_dump"):
                    entry["usage"] = usage_entry.model_dump()
                elif isinstance(usage_entry, dict):
                    entry["usage"] = usage_entry
                else:
                    entry["usage"] = {
                        "input_tokens": getattr(usage_entry, "input_tokens", 0),
                        "output_tokens": getattr(usage_entry, "output_tokens", 0),
                        "cache_creation_input_tokens": getattr(
                            usage_entry, "cache_creation_input_tokens", 0
                        ),
                        "cache_read_input_tokens": getattr(
                            usage_entry, "cache_read_input_tokens", 0
                        ),
                    }
                entry["model_spec"] = model_spec_entry
                # Try to associate with the latest assistant msg_id
                if store.last_msg_id:
                    entry["msg_id"] = store.last_msg_id
                metadata_entries.append(entry)
            store.append_metadata(metadata_entries)

        # 3. Overwrite context file with current full context window
        store.write_context(chat_history)

        # 4. Update session.json
        compaction_metadata = getattr(self, "_compaction_metadata", None)
        session_meta = {
            "session_id": self.session_id,
            "parent_session_id": self.parent_session_id,
            "model_spec": self.model_spec,
            "thinking_mode": self.thinking_mode,
            "active_plan_id": self.active_plan_id,
            "root_dir": _find_root_dir(),
            "cli_args": self.cli_args.copy() if self.cli_args else None,
        }
        if compaction_metadata:
            session_meta["compaction"] = {
                "is_compacted": True,
                "original_message_count": compaction_metadata.original_message_count,
                "original_token_count": compaction_metadata.original_token_count,
                "compacted_message_count": compaction_metadata.compacted_message_count,
                "summary_token_count": compaction_metadata.summary_token_count,
                "compaction_ratio": compaction_metadata.compaction_ratio,
                "pre_compaction_archive": compaction_metadata.archive_name,
            }
            del self._compaction_metadata
        store.write_session_meta(session_meta)

        # Update flush counters
        self._last_flushed_msg_count = new_msg_count
        self._last_flushed_usage_count = new_usage_count

        # Legacy root.json dual-write removed — all consumers now read v2 format.


def load_session_data(
    session_id: str,
    base_context: Optional[AgentContext] = None,
    history_base_dir: Optional[Path] = None,
) -> Optional[AgentContext]:
    """Load session data and return an updated AgentContext.

    Tries v2 format (session.json) first, falls back to legacy (root.json).
    """
    base = (
        history_base_dir
        if history_base_dir
        else (Path.home() / ".silica" / "personas" / "default")
    )
    history_dir = base / "history" / session_id

    if not base_context:
        return None

    # Try v2 format first
    store = SessionStore(history_dir, agent_name="root")
    session_meta = store.read_session_meta()

    if session_meta and session_meta.get("version", 0) >= 2:
        return _load_v2_session(
            session_id, store, session_meta, base_context, history_base_dir
        )

    # Auto-migrate legacy sessions on resume
    root_file = history_dir / "root.json"
    if root_file.exists() and not (history_dir / "session.json").exists():
        try:
            from silica.developer.session_store import migrate_session

            migrate_session(history_dir)
            print(f"Auto-migrated session {session_id} to v2 format")
            # Now load as v2
            store = SessionStore(history_dir, agent_name="root")
            session_meta = store.read_session_meta()
            if session_meta:
                return _load_v2_session(
                    session_id,
                    store,
                    session_meta,
                    base_context,
                    history_base_dir,
                )
        except Exception as e:
            print(f"Auto-migration failed, falling back to legacy: {e}")

    # Fall back to legacy format
    return _load_legacy_session(session_id, history_dir, base_context, history_base_dir)


def _load_v2_session(
    session_id: str,
    store: SessionStore,
    session_meta: dict,
    base_context: AgentContext,
    history_base_dir: Optional[Path],
) -> Optional[AgentContext]:
    """Load a session from v2 split-file format."""
    try:
        # Read context window (what the agent currently sees)
        chat_history = store.read_context()
        if not chat_history:
            # Context might be empty if session just started — try history
            chat_history = [
                {k: v for k, v in msg.items() if k not in _INTERNAL_MSG_KEYS}
                for msg in store.read_history()
            ]

        # Strip internal fields from context messages for API compat
        clean_history = []
        for msg in chat_history:
            clean = {k: v for k, v in msg.items() if k not in _INTERNAL_MSG_KEYS}
            clean_history.append(clean)

        # Read usage from metadata.jsonl — reconstruct (usage, model_spec) tuples
        usage_data = []
        for entry in store.read_metadata():
            usage_dict = entry.get("usage", {})
            model_spec_dict = entry.get("model_spec", base_context.model_spec)
            usage_data.append((usage_dict, model_spec_dict))

        # Clean up orphaned tool blocks
        from silica.developer.compaction_validation import strip_orphaned_tool_blocks

        original_count = len(clean_history)
        clean_history = strip_orphaned_tool_blocks(clean_history)
        if len(clean_history) != original_count:
            print(
                f"Cleaned up orphaned tool blocks: {original_count} -> {len(clean_history)} messages"
            )

        model_spec = session_meta.get("model_spec", base_context.model_spec)
        parent_id = session_meta.get("parent_session_id")
        cli_args = session_meta.get("cli_args")
        thinking_mode = session_meta.get("thinking_mode", "max")
        active_plan_id = session_meta.get("active_plan_id")

        updated_context = AgentContext(
            session_id=session_id,
            parent_session_id=parent_id,
            model_spec=model_spec,
            sandbox=base_context.sandbox,
            user_interface=base_context.user_interface,
            usage=usage_data if usage_data else base_context.usage,
            memory_manager=base_context.memory_manager,
            cli_args=cli_args.copy() if cli_args else None,
            thinking_mode=thinking_mode,
            history_base_dir=history_base_dir,
            active_plan_id=active_plan_id,
            _chat_history=clean_history,
            _tool_result_buffer=[],
            _session_store=store,
            _last_flushed_msg_count=len(clean_history),
            _last_flushed_usage_count=len(usage_data),
        )

        if hasattr(base_context.user_interface, "handle_system_message"):
            base_context.user_interface.handle_system_message(
                f"Successfully loaded session {session_id} with {len(clean_history)} messages"
            )
        return updated_context

    except Exception as e:
        print(f"Error loading v2 session: {str(e)}")
        return None


def _load_legacy_session(
    session_id: str,
    history_dir: Path,
    base_context: AgentContext,
    history_base_dir: Optional[Path],
) -> Optional[AgentContext]:
    """Load a session from legacy root.json format."""
    root_file = history_dir / "root.json"
    if not root_file.exists():
        print(f"Session file not found: {root_file}")
        return None

    try:
        with open(root_file, "r") as f:
            session_data = json.load(f)

        if "metadata" not in session_data:
            print("Session lacks metadata (pre-HDEV-58)")
            return None

        chat_history = session_data.get("messages", [])
        usage_data = session_data.get("usage", [])
        model_spec = session_data.get("model_spec", base_context.model_spec)
        parent_id = session_data.get("parent_session_id")
        cli_args = session_data.get("metadata", {}).get("cli_args")
        thinking_mode = session_data.get("thinking_mode", "max")
        active_plan_id = session_data.get("active_plan_id")

        from silica.developer.compaction_validation import strip_orphaned_tool_blocks

        original_count = len(chat_history)
        chat_history = strip_orphaned_tool_blocks(chat_history)
        if len(chat_history) != original_count:
            print(
                f"Cleaned up orphaned tool blocks in session: {original_count} -> {len(chat_history)} messages"
            )

        updated_context = AgentContext(
            session_id=session_id,
            parent_session_id=parent_id,
            model_spec=model_spec,
            sandbox=base_context.sandbox,
            user_interface=base_context.user_interface,
            usage=usage_data if usage_data else base_context.usage,
            memory_manager=base_context.memory_manager,
            cli_args=cli_args.copy() if cli_args else None,
            thinking_mode=thinking_mode,
            history_base_dir=history_base_dir,
            active_plan_id=active_plan_id,
            _chat_history=chat_history,
            _tool_result_buffer=[],
        )

        if hasattr(base_context.user_interface, "handle_system_message"):
            base_context.user_interface.handle_system_message(
                f"Successfully loaded session {session_id} with {len(chat_history)} messages"
            )
        return updated_context

    except json.JSONDecodeError as e:
        print(f"Invalid session file format: {e}")
    except FileNotFoundError:
        print(f"Session file not found: {root_file}")
    except Exception as e:
        print(f"Error loading session: {str(e)}")
    return None
