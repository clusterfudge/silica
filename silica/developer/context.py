import json
import os
from dataclasses import dataclass
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


class PydanticJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, BaseModel):
            # For Pydantic v2
            if hasattr(obj, "model_dump"):
                return obj.model_dump()
            # For Pydantic v1
            return obj.dict()
        return super().default(obj)


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
    _chat_history: list[MessageParam] = None
    _tool_result_buffer: list[dict] = None

    def __post_init__(self):
        """Initialize the chat history and tool result buffer if they are None."""
        if self._chat_history is None:
            self._chat_history = []
        if self._tool_result_buffer is None:
            self._tool_result_buffer = []

    @property
    def chat_history(self) -> list[MessageParam]:
        """Get the chat history."""
        return self._chat_history

    @property
    def tool_result_buffer(self) -> list[dict]:
        """Get the tool result buffer."""
        return self._tool_result_buffer

    @staticmethod
    def create(
        model_spec: ModelSpec,
        sandbox_mode: SandboxMode,
        sandbox_contents: list[str],
        user_interface: UserInterface,
        session_id: str = None,
        cli_args: list[str] = None,
    ) -> "AgentContext":
        sandbox = Sandbox(
            sandbox_contents[0] if sandbox_contents else os.getcwd(),
            mode=sandbox_mode,
            permission_check_callback=user_interface.permission_callback,
            permission_check_rendering_callback=user_interface.permission_rendering_callback,
        )

        memory_manager = MemoryManager()

        # Use provided session_id or generate a new one
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
        )

        # If a session_id was provided, attempt to load that session
        if session_id:
            # Load the session data
            loaded_context = load_session_data(session_id, context)

            # If loading was successful, update message count for UI feedback
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
        self, user_interface: UserInterface, keep_history=False
    ) -> "AgentContext":
        return AgentContext(
            session_id=str(uuid4()),
            parent_session_id=self.session_id,
            model_spec=self.model_spec,
            sandbox=self.sandbox,
            user_interface=user_interface,
            usage=self.usage,
            memory_manager=self.memory_manager,
            cli_args=self.cli_args.copy() if self.cli_args else None,
            _chat_history=self.chat_history.copy() if keep_history else [],
            _tool_result_buffer=self.tool_result_buffer.copy() if keep_history else [],
        )

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
        """Get the complete context that would be sent to the Anthropic API.

        This includes system message, tools, and processed messages,
        matching exactly what the agent sends in API calls.

        Args:
            tool_names: Optional list of tool names to limit tools (for sub-agents)

        Returns:
            Dict with 'system', 'tools', and 'messages' keys
        """
        from silica.developer.prompt import create_system_message
        from silica.developer.toolbox import Toolbox
        from silica.developer.agent_loop import _inline_latest_file_mentions

        # Create system message
        system_message = create_system_message(self)

        # Create toolbox and get tool schemas
        toolbox = Toolbox(self, tool_names=tool_names)
        tools = toolbox.agent_schema

        # Process messages with inlined file mentions
        processed_messages = _inline_latest_file_mentions(self.chat_history)

        return {
            "system": system_message,
            "tools": tools,
            "messages": processed_messages,
        }

    def usage_summary(self) -> dict[str, Any]:
        usage_summary = {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost": 0.0,
            "cached_tokens": 0,
            "model_breakdown": {},
        }

        for usage_entry, model_spec in self.usage:
            model_name = model_spec["title"]
            pricing = model_spec["pricing"]
            cache_pricing = model_spec["cache_pricing"]

            input_tokens = self._prop_or_dict_entry(usage_entry, "input_tokens")
            output_tokens = self._prop_or_dict_entry(usage_entry, "output_tokens")
            cache_creation_input_tokens = self._prop_or_dict_entry(
                usage_entry, "cache_creation_input_tokens"
            )
            cache_read_input_tokens = self._prop_or_dict_entry(
                usage_entry, "cache_read_input_tokens"
            )

            usage_summary["total_input_tokens"] += input_tokens
            usage_summary["total_output_tokens"] += output_tokens
            usage_summary["cached_tokens"] += cache_read_input_tokens

            total_cost = (
                input_tokens * pricing["input"]
                + output_tokens * pricing["output"]
                + cache_pricing["read"] * cache_read_input_tokens
                + cache_pricing["write"] * cache_creation_input_tokens
            )

            if model_name not in usage_summary["model_breakdown"]:
                usage_summary["model_breakdown"][model_name] = {
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_cost": 0.0,
                    "cached_tokens": 0,
                    "token_breakdown": {},
                }

            model_breakdown = usage_summary["model_breakdown"][model_name]
            model_breakdown["total_input_tokens"] += input_tokens
            model_breakdown["total_output_tokens"] += output_tokens
            model_breakdown["cached_tokens"] += cache_read_input_tokens

            model_breakdown["total_cost"] += total_cost

            usage_summary["total_cost"] += total_cost

        usage_summary["total_cost"] /= 1_000_000

        return usage_summary

    def flush(self, chat_history, compact=True):
        """Save the agent context and chat history to a file.

        For root contexts (parent_session_id is None), saves to:
            ~/.hdev/history/{session_id}/root.json

        For sub-agent contexts (parent_session_id is not None), saves to:
            ~/.hdev/history/{parent_session_id}/{session_id}.json

        Args:
            chat_history: The chat history to save
            compact: Whether to check and perform compaction on long conversations
                    Note: As of the compaction transition update, compaction is now
                    handled explicitly in the agent loop, so this parameter is
                    maintained for backward compatibility but typically not used.
        """
        if not chat_history:
            return

        # Note: Compaction is now handled explicitly in the agent loop rather than
        # as a side effect of flush. This allows for proper session transitions.
        compaction_summary = None

        # Base history directory
        history_dir = Path.home() / ".hdev" / "history"

        # For root contexts, use their own session_id
        # For sub-agent contexts, use the parent_session_id
        context_dir = (
            self.parent_session_id if self.parent_session_id else self.session_id
        )
        history_dir = history_dir / context_dir

        # Create the directory if it doesn't exist
        history_dir.mkdir(parents=True, exist_ok=True)

        # Filename is root.json for root contexts, or {session_id}.json for sub-agent contexts
        filename = (
            "root.json" if self.parent_session_id is None else f"{self.session_id}.json"
        )
        history_file = history_dir / filename

        # Get the current time for metadata
        current_time = datetime.now(timezone.utc).isoformat()

        # Try to determine the root directory
        root_dir = None
        try:
            # Try to find git repository root
            current_dir = os.path.abspath(os.getcwd())
            potential_git_dir = current_dir

            # Walk up directories looking for .git folder
            while potential_git_dir != os.path.dirname(
                potential_git_dir
            ):  # Stop at filesystem root
                if os.path.isdir(os.path.join(potential_git_dir, ".git")):
                    root_dir = potential_git_dir
                    break
                potential_git_dir = os.path.dirname(potential_git_dir)

            # If no git root found, use current working directory
            if root_dir is None:
                root_dir = current_dir
        except Exception:
            # Fallback to current working directory if any error occurs
            root_dir = os.path.abspath(os.getcwd())

        # Prepare the data to save
        context_data = {
            "session_id": self.session_id,
            "parent_session_id": self.parent_session_id,
            "model_spec": self.model_spec,
            "usage": self.usage,
            "messages": chat_history,
            "metadata": {
                "created_at": current_time,
                "last_updated": current_time,
                "root_dir": root_dir,
                "cli_args": self.cli_args.copy() if self.cli_args else None,
            },
        }

        # Add compaction metadata if available
        if compaction_summary:
            context_data["compaction"] = {
                "original_session_id": self.parent_session_id,
                "original_message_count": compaction_summary.original_message_count,
                "original_token_count": compaction_summary.original_token_count,
                "summary_token_count": compaction_summary.summary_token_count,
                "compaction_ratio": compaction_summary.compaction_ratio,
                "timestamp": str(
                    Path(history_file).stat().st_mtime
                    if Path(history_file).exists()
                    else None
                ),
            }

        # If the file already exists, read it to preserve the original created_at time
        if os.path.exists(history_file):
            try:
                with open(history_file, "r") as f:
                    existing_data = json.load(f)
                    if (
                        "metadata" in existing_data
                        and "created_at" in existing_data["metadata"]
                    ):
                        context_data["metadata"]["created_at"] = existing_data[
                            "metadata"
                        ]["created_at"]
            except (json.JSONDecodeError, FileNotFoundError, KeyError):
                # If there's any error reading the existing file, continue with the new metadata
                pass

        # Update the last_updated timestamp
        context_data["metadata"]["last_updated"] = datetime.now(
            timezone.utc
        ).isoformat()

        # Write the data to the file
        with open(history_file, "w") as f:
            json.dump(context_data, f, indent=2, cls=PydanticJSONEncoder)


def load_session_data(
    session_id: str, base_context: Optional[AgentContext] = None
) -> Optional[AgentContext]:
    """
    Load session data from a file and return an updated AgentContext.

    This function loads a previous session's data and returns a new or updated
    AgentContext instance with the loaded state.

    Args:
        session_id: The ID of the session to load
        base_context: Optional existing AgentContext to update with session data.
                      If not provided, a new context will be created.

    Returns:
        Updated AgentContext if successful, None if loading failed
    """
    history_dir = Path.home() / ".hdev" / "history" / session_id
    root_file = history_dir / "root.json"

    if not root_file.exists():
        print(f"Session file not found: {root_file}")
        return None

    try:
        with open(root_file, "r") as f:
            session_data = json.load(f)

        # Verify session has valid metadata (from HDEV-58 onwards)
        if "metadata" not in session_data:
            print("Session lacks metadata (pre-HDEV-58)")
            return None

        # If no base context is provided, we can't create a new one
        # as we need sandbox mode, UI, etc.
        if not base_context:
            return None

        # Extract data from the session file
        chat_history = session_data.get("messages", [])
        usage_data = session_data.get("usage", [])
        model_spec = session_data.get("model_spec", base_context.model_spec)
        parent_id = session_data.get("parent_session_id")
        cli_args = session_data.get("metadata", {}).get("cli_args")

        # Create a new context with the loaded data
        updated_context = AgentContext(
            session_id=session_id,
            parent_session_id=parent_id,
            model_spec=model_spec,
            sandbox=base_context.sandbox,
            user_interface=base_context.user_interface,
            usage=usage_data if usage_data else base_context.usage,
            memory_manager=base_context.memory_manager,
            cli_args=cli_args.copy() if cli_args else None,
            _chat_history=chat_history,
            _tool_result_buffer=[],  # Always start with empty tool buffer
        )

        # If base_context has user_interface.handle_system_message, report success
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
