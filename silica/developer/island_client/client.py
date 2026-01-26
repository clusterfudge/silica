"""Agent Island IPC Client.

Provides async communication with the Agent Island macOS app over Unix socket.
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from .protocol import (
    JsonRpcRequest,
    JsonRpcResponse,
    JsonRpcNotification,
    HandshakeParams,
    SessionRegisterParams,
    PermissionRequestParams,
    PermissionResponse,
    QuestionnaireQuestion,
    AlertStyle,
    ErrorCode,
)
from .exceptions import (
    IslandError,
    ConnectionError,
    ProtocolError,
    DialogNotFoundError,
    SessionNotFoundError,
    TimeoutError,
)


DEFAULT_SOCKET_PATH = "~/.agent-island/agent.sock"
PROTOCOL_VERSION = "1.0"


InputCallback = Any  # Callable[[str, str, str], Awaitable[None]] - (session_id, content, message_id)
ProgressActionCallback = Any  # Callable[[str, str, str, Optional[str]], Awaitable[None]] - (session_id, progress_id, action_id, url_scheme)


class IslandClient:
    """Async client for Agent Island IPC communication.

    Usage:
        async with IslandClient() as client:
            if client.connected:
                result = await client.permission_request(...)

    Or manually:
        client = IslandClient()
        await client.connect()
        try:
            result = await client.permission_request(...)
        finally:
            await client.disconnect()

    For bidirectional chat, register an input callback:
        async def handle_input(session_id: str, content: str, message_id: str):
            print(f"User said: {content}")

        client.on_input_received = handle_input
    """

    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET_PATH,
        app_name: str = "silica",
        app_icon: str = "brain",
        agent_version: str = "1.0.0",
    ):
        self.socket_path = Path(socket_path).expanduser()
        self.app_name = app_name
        self.app_icon = app_icon
        self.agent_version = agent_version

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._connected = False
        self._island_version: Optional[str] = None
        self._supported_methods: List[str] = []

        # Callback for user input from Island UI (bidirectional chat)
        # Signature: async def callback(session_id: str, content: str, message_id: str)
        self.on_input_received: Optional[InputCallback] = None

        # Callback for progress bar action clicks
        # Signature: async def callback(session_id: str, progress_id: str, action_id: str, url_scheme: Optional[str])
        self.on_progress_action: Optional[ProgressActionCallback] = None

    @property
    def connected(self) -> bool:
        """Check if connected to Agent Island."""
        return self._connected and self._writer is not None

    @property
    def island_version(self) -> Optional[str]:
        """Get the connected Island's version."""
        return self._island_version

    async def __aenter__(self) -> "IslandClient":
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()

    def socket_exists(self) -> bool:
        """Check if the socket file exists."""
        return self.socket_path.exists()

    async def connect(self) -> bool:
        """Connect to Agent Island.

        Returns:
            True if connected successfully, False otherwise.
            Does not raise exceptions - returns False on any failure.
        """
        if self._connected:
            return True

        if not self.socket_exists():
            return False

        try:
            self._reader, self._writer = await asyncio.open_unix_connection(
                str(self.socket_path)
            )

            # Start background reader task
            self._read_task = asyncio.create_task(self._reader_loop())

            # Perform handshake
            handshake_result = await self._handshake()
            if not handshake_result:
                await self._close_connection()
                return False

            self._connected = True
            return True

        except (OSError, ConnectionRefusedError, FileNotFoundError):
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Agent Island."""
        await self._close_connection()

    async def _close_connection(self) -> None:
        """Close the connection and clean up."""
        self._connected = False

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None

        self._reader = None

        # Cancel any pending requests
        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(ConnectionError("Connection closed"))
        self._pending_requests.clear()

    async def _reader_loop(self) -> None:
        """Background task that reads responses from the socket."""
        try:
            while self._reader:
                line = await self._reader.readline()
                if not line:
                    break

                try:
                    data = json.loads(line.decode("utf-8"))

                    # Check if it's a response (has id)
                    if "id" in data and data["id"] in self._pending_requests:
                        response = JsonRpcResponse(
                            id=data["id"],
                            result=data.get("result"),
                            error=data.get("error"),
                        )
                        future = self._pending_requests.pop(data["id"])
                        if not future.done():
                            future.set_result(response)

                    # Handle server-initiated notifications (no id field)
                    elif "method" in data and "id" not in data:
                        await self._handle_notification(data)

                except json.JSONDecodeError:
                    continue

        except asyncio.CancelledError:
            pass
        except Exception:
            # Connection lost
            self._connected = False

    async def _handle_notification(self, data: Dict[str, Any]) -> None:
        """Handle a server-initiated notification."""
        method = data.get("method", "")
        params = data.get("params", {})

        if method == "input.received":
            # User sent input from Island UI
            session_id = params.get("session_id", "")
            content = params.get("content", "")
            message_id = params.get("message_id", "")

            if self.on_input_received:
                try:
                    # Call the callback (may be sync or async)
                    result = self.on_input_received(session_id, content, message_id)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    # Don't let callback errors break the reader loop
                    pass

        elif method == "progress.action_clicked":
            # User clicked an action button on a progress bar
            session_id = params.get("session_id", "")
            progress_id = params.get("progress_id", "")
            action_id = params.get("action_id", "")
            url_scheme = params.get("url_scheme")

            if self.on_progress_action:
                try:
                    result = self.on_progress_action(
                        session_id, progress_id, action_id, url_scheme
                    )
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass

    def _next_id(self) -> int:
        """Get the next request ID."""
        self._request_id += 1
        return self._request_id

    async def _send_request(
        self,
        method: str,
        params: Dict[str, Any],
        timeout: Optional[float] = None,
        _allow_during_handshake: bool = False,
    ) -> Dict[str, Any]:
        """Send a request and wait for response.

        Args:
            method: JSON-RPC method name
            params: Method parameters
            timeout: Optional timeout in seconds
            _allow_during_handshake: Internal flag to allow requests before connected

        Returns:
            The result dict from the response

        Raises:
            ConnectionError: If not connected
            ProtocolError: If response is an error
            TimeoutError: If request times out
        """
        # Allow requests during handshake (before _connected is set)
        if not _allow_during_handshake and not self.connected:
            raise ConnectionError("Not connected to Agent Island")

        if self._writer is None:
            raise ConnectionError("No connection to Agent Island")

        request_id = self._next_id()
        request = JsonRpcRequest(method=method, params=params, id=request_id)

        # Create future for response
        future: asyncio.Future[JsonRpcResponse] = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            # Send request
            self._writer.write(request.to_bytes())
            await self._writer.drain()

            # Wait for response
            if timeout:
                response = await asyncio.wait_for(future, timeout=timeout)
            else:
                response = await future

            # Check for error
            if response.is_error:
                error = response.error
                code = error.get("code", ErrorCode.INTERNAL_ERROR)
                message = error.get("message", "Unknown error")

                if code == ErrorCode.DIALOG_NOT_FOUND:
                    raise DialogNotFoundError(params.get("dialog_id", "unknown"))
                elif code == ErrorCode.SESSION_NOT_FOUND:
                    raise SessionNotFoundError(params.get("session_id", "unknown"))
                else:
                    raise ProtocolError(message, code)

            return response.result or {}

        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise TimeoutError(f"Request {method} timed out")
        except asyncio.CancelledError:
            self._pending_requests.pop(request_id, None)
            raise

    async def _send_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send a notification (fire-and-forget, no response expected).

        Does not raise exceptions - silently fails if not connected.
        """
        if not self.connected:
            return

        try:
            notification = JsonRpcNotification(method=method, params=params)
            self._writer.write(notification.to_bytes())
            await self._writer.drain()
        except Exception:
            # Fire-and-forget - don't propagate errors
            pass

    async def _handshake(self) -> bool:
        """Perform protocol handshake.

        Returns:
            True if handshake successful, False otherwise.
        """
        try:
            params = HandshakeParams(
                agent=self.app_name,
                agent_version=self.agent_version,
                protocol_version=PROTOCOL_VERSION,
                pid=os.getpid(),
            )

            result = await self._send_request(
                "handshake", params.to_dict(), timeout=5.0, _allow_during_handshake=True
            )

            # Verify protocol version compatibility
            island_protocol = result.get("protocol_version", "")
            if not island_protocol.startswith("1."):
                return False

            self._island_version = result.get("island_version")
            self._supported_methods = result.get("supported_methods", [])

            return True

        except Exception:
            return False

    # ========== Session Management ==========

    async def register_session(
        self,
        session_id: str,
        working_directory: str,
        model: Optional[str] = None,
        persona: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """Register a session with Agent Island.

        Args:
            session_id: Unique session identifier
            working_directory: Current working directory
            model: Optional model name
            persona: Optional persona name
            history: Optional list of chat history messages to bulk load

        Returns:
            True if registered successfully
        """
        params = SessionRegisterParams(
            session_id=session_id,
            app_name=self.app_name,
            app_icon=self.app_icon,
            working_directory=working_directory,
            model=model,
            persona=persona,
        )

        params_dict = params.to_dict()
        if history:
            params_dict["history"] = history

        try:
            result = await self._send_request("session.register", params_dict)
            return result.get("registered", False)
        except IslandError:
            return False

    async def unregister_session(self, session_id: str) -> bool:
        """Unregister a session.

        Args:
            session_id: Session ID to unregister

        Returns:
            True if unregistered successfully
        """
        try:
            await self._send_request("session.unregister", {"session_id": session_id})
            return True
        except IslandError:
            return False

    # ========== UI Primitives ==========

    async def alert(
        self,
        title: str,
        message: str,
        style: AlertStyle = AlertStyle.INFO,
        dialog_id: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> bool:
        """Show an alert dialog.

        Args:
            title: Dialog title
            message: Message body
            style: Alert style (info, warning, error)
            dialog_id: Optional dialog ID for cancellation
            hint: Optional hint about alternative interface

        Returns:
            True when dismissed
        """
        params = {
            "dialog_id": dialog_id or str(uuid4()),
            "title": title,
            "message": message,
            "style": style.value,
        }
        if hint:
            params["hint"] = hint

        result = await self._send_request("ui.alert", params)
        return result.get("dismissed", True)

    async def prompt(
        self,
        title: str,
        message: str,
        default_value: Optional[str] = None,
        placeholder: Optional[str] = None,
        dialog_id: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> Optional[str]:
        """Show a text input prompt.

        Args:
            title: Dialog title
            message: Prompt message
            default_value: Optional default value
            placeholder: Optional placeholder text
            dialog_id: Optional dialog ID for cancellation
            hint: Optional hint about alternative interface

        Returns:
            User's input string, or None if cancelled
        """
        params = {
            "dialog_id": dialog_id or str(uuid4()),
            "title": title,
            "message": message,
        }
        if default_value:
            params["default_value"] = default_value
        if placeholder:
            params["placeholder"] = placeholder
        if hint:
            params["hint"] = hint

        result = await self._send_request("ui.prompt", params)

        if result.get("cancelled"):
            return None
        return result.get("value")

    async def confirm(
        self,
        title: str,
        message: str,
        confirm_text: str = "OK",
        cancel_text: str = "Cancel",
        dialog_id: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> bool:
        """Show a confirmation dialog.

        Args:
            title: Dialog title
            message: Confirmation message
            confirm_text: Text for confirm button
            cancel_text: Text for cancel button
            dialog_id: Optional dialog ID for cancellation
            hint: Optional hint about alternative interface

        Returns:
            True if confirmed, False if cancelled
        """
        params = {
            "dialog_id": dialog_id or str(uuid4()),
            "title": title,
            "message": message,
            "confirm_text": confirm_text,
            "cancel_text": cancel_text,
        }
        if hint:
            params["hint"] = hint

        result = await self._send_request("ui.confirm", params)
        return result.get("confirmed", False)

    async def select(
        self,
        title: str,
        message: str,
        options: List[str],
        allow_custom: bool = False,
        dialog_id: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> Optional[str]:
        """Show a selection dialog.

        Args:
            title: Dialog title
            message: Selection prompt
            options: List of options to choose from
            allow_custom: Whether to allow custom input
            dialog_id: Optional dialog ID for cancellation
            hint: Optional hint about alternative interface

        Returns:
            Selected option string, or None if cancelled
        """
        params = {
            "dialog_id": dialog_id or str(uuid4()),
            "title": title,
            "message": message,
            "options": options,
            "allow_custom": allow_custom,
        }
        if hint:
            params["hint"] = hint

        result = await self._send_request("ui.select", params)

        if result.get("cancelled"):
            return None
        return result.get("selection")

    async def questionnaire(
        self,
        title: str,
        questions: List[Union[QuestionnaireQuestion, Dict[str, Any]]],
        dialog_id: Optional[str] = None,
        hint: Optional[str] = None,
    ) -> Optional[Dict[str, str]]:
        """Show a questionnaire form.

        Args:
            title: Form title
            questions: List of questions
            dialog_id: Optional dialog ID for cancellation
            hint: Optional hint about alternative interface

        Returns:
            Dict mapping question IDs to answers, or None if cancelled
        """
        # Convert questions to dicts
        q_list = []
        for q in questions:
            if isinstance(q, QuestionnaireQuestion):
                q_list.append(q.to_dict())
            else:
                q_list.append(q)

        params = {
            "dialog_id": dialog_id or str(uuid4()),
            "title": title,
            "questions": q_list,
        }
        if hint:
            params["hint"] = hint

        result = await self._send_request("ui.questionnaire", params)

        if result.get("cancelled"):
            return None
        return result.get("answers")

    # ========== Permission Requests ==========

    async def permission_request(
        self,
        action: str,
        resource: str,
        dialog_id: Optional[str] = None,
        group: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        shell_parsed: Optional[Dict[str, Any]] = None,
        hint: Optional[str] = None,
    ) -> PermissionResponse:
        """Request permission for an action.

        Args:
            action: Action name (e.g., "shell", "read_file")
            resource: Resource being accessed
            dialog_id: Optional dialog ID for cancellation
            group: Optional tool group
            details: Optional additional details (diff, etc.)
            shell_parsed: Optional parsed shell command info
            hint: Optional hint about alternative interface

        Returns:
            PermissionResponse with the user's decision
        """
        params = PermissionRequestParams(
            dialog_id=dialog_id or str(uuid4()),
            action=action,
            resource=resource,
            group=group,
            details=details,
            shell_parsed=shell_parsed,
            hint=hint,
        )

        result = await self._send_request("permission.request", params.to_dict())
        return PermissionResponse.from_result(result)

    # ========== Dialog Lifecycle ==========

    async def cancel_dialog(self, dialog_id: str) -> bool:
        """Cancel a pending dialog.

        Args:
            dialog_id: ID of dialog to cancel

        Returns:
            True if cancelled successfully
        """
        try:
            result = await self._send_request("dialog.cancel", {"dialog_id": dialog_id})
            return result.get("cancelled", False)
        except DialogNotFoundError:
            return False
        except IslandError:
            return False

    # ========== Event Notifications ==========

    async def notify_user_message(
        self,
        content: str,
        message_id: Optional[str] = None,
    ) -> None:
        """Notify about a user message.

        Args:
            content: The user's message text
            message_id: Optional unique message ID for deduplication
        """
        params = {
            "content": content,
        }
        if message_id:
            params["message_id"] = message_id
        await self._send_notification("event.user_message", params)

    async def notify_assistant_message(
        self,
        content: str,
        format: str = "markdown",
        message_id: Optional[str] = None,
        notification: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Notify about an assistant message.

        Args:
            content: The assistant's message content
            format: Content format ("markdown" or "text")
            message_id: Optional unique message ID for deduplication
            notification: Optional notification style override {"style": "none|indicator|sound|expand|bounce", "sound": "optional_sound_name"}
        """
        params: Dict[str, Any] = {
            "content": content,
            "format": format,
        }
        if message_id:
            params["message_id"] = message_id
        if notification:
            params["notification"] = notification
        await self._send_notification("event.assistant_message", params)

    async def notify_tool_use(
        self,
        tool_name: str,
        tool_params: Dict[str, Any],
    ) -> None:
        """Notify about a tool being used."""
        await self._send_notification(
            "event.tool_use",
            {
                "tool_name": tool_name,
                "tool_params": tool_params,
            },
        )

    async def notify_tool_result(
        self,
        tool_name: str,
        result: Any,
        success: bool = True,
    ) -> None:
        """Notify about a tool result."""
        await self._send_notification(
            "event.tool_result",
            {
                "tool_name": tool_name,
                "result": result,
                "success": success,
            },
        )

    async def notify_thinking(
        self,
        content: str,
        tokens: int,
        cost: float,
        message_id: Optional[str] = None,
    ) -> None:
        """Notify about thinking content.

        Args:
            content: The thinking/reasoning content
            tokens: Number of tokens in thinking
            cost: Cost of thinking tokens
            message_id: Optional unique message ID for deduplication
        """
        params = {
            "content": content,
            "tokens": tokens,
            "cost": cost,
        }
        if message_id:
            params["message_id"] = message_id
        await self._send_notification("event.thinking", params)

    async def notify_token_usage(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_cost: float,
        cached_tokens: Optional[int] = None,
        conversation_size: Optional[int] = None,
        context_window: Optional[int] = None,
        thinking_tokens: Optional[int] = None,
        elapsed_seconds: Optional[float] = None,
    ) -> None:
        """Notify about token usage."""
        params = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_cost": total_cost,
        }
        if cached_tokens is not None:
            params["cached_tokens"] = cached_tokens
        if conversation_size is not None:
            params["conversation_size"] = conversation_size
        if context_window is not None:
            params["context_window"] = context_window
        if thinking_tokens is not None:
            params["thinking_tokens"] = thinking_tokens
        if elapsed_seconds is not None:
            params["elapsed_seconds"] = elapsed_seconds

        await self._send_notification("event.token_usage", params)

    async def notify_status(
        self,
        message: str,
        spinner: bool = False,
        notification: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Notify about a status update.

        Args:
            message: Status message
            spinner: Whether to show a spinner
            notification: Optional notification style override
        """
        params: Dict[str, Any] = {
            "message": message,
            "spinner": spinner,
        }
        if notification:
            params["notification"] = notification
        await self._send_notification("event.status", params)

    async def notify_system_message(
        self,
        message: str,
        style: str = "info",
        notification: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Notify about a system message.

        Args:
            message: System message content
            style: Message style (info, warning, error)
            notification: Optional notification style override
        """
        params: Dict[str, Any] = {
            "message": message,
            "style": style,
        }
        if notification:
            params["notification"] = notification
        await self._send_notification("event.system_message", params)

    async def notify_ready_for_input(
        self,
        message: str = "Ready for input",
    ) -> None:
        """Notify that the agent is ready for user input.

        This triggers a notification sound by default.
        """
        await self._send_notification(
            "event.ready_for_input",
            {
                "message": message,
                "notification": {"style": "sound"},
            },
        )

    async def notify_error(
        self,
        message: str,
        details: Optional[str] = None,
    ) -> None:
        """Notify about an error.

        This triggers a notification sound by default.
        """
        params: Dict[str, Any] = {
            "message": message,
            "notification": {"style": "sound"},
        }
        if details:
            params["details"] = details
        await self._send_notification("event.error", params)

    # ========== Panel Control (Testing/Debugging) ==========

    async def open_panel(self) -> bool:
        """Open the Agent Island panel.

        This is primarily for testing/debugging to programmatically
        open the panel to inspect its current state.

        Returns:
            True if panel was opened successfully
        """
        try:
            result = await self._send_request("ui.open", {})
            return result.get("opened", False)
        except IslandError:
            return False

    async def close_panel(self) -> bool:
        """Close the Agent Island panel.

        This is primarily for testing/debugging to programmatically
        close the panel.

        Returns:
            True if panel was closed successfully
        """
        try:
            result = await self._send_request("ui.close", {})
            return result.get("closed", False)
        except IslandError:
            return False

    async def open_settings(self) -> bool:
        """Open the Agent Island settings panel.

        This is primarily for testing/debugging to programmatically
        open the settings view.

        Returns:
            True if settings were opened successfully
        """
        try:
            result = await self._send_request("ui.settings", {})
            return result.get("opened", False)
        except IslandError:
            return False

    # ========== Session Phase API ==========

    async def update_phase(
        self,
        phase: str,
        session_id: Optional[str] = None,
    ) -> bool:
        """Update the session phase.

        Args:
            phase: Phase name ("idle", "processing", "waiting_for_input", "ended")
            session_id: Optional session ID (uses connected session if not specified)

        Returns:
            True if updated successfully
        """
        params: Dict[str, Any] = {"phase": phase}
        if session_id is not None:
            params["session_id"] = session_id

        try:
            result = await self._send_request("session.update_phase", params)
            return result.get("updated", False)
        except IslandError:
            return False

    # ========== Progress Bar API ==========

    async def progress_create(
        self,
        progress_id: str,
        title: str,
        progress: Optional[float] = None,
        status_text: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """Create a new progress bar.

        Args:
            progress_id: Unique ID for this progress bar
            title: Title to display
            progress: Progress value 0-1, or None for indeterminate
            status_text: Optional status text below the bar
            session_id: Optional session ID (uses connected session if not specified)

        Returns:
            The progress_id
        """
        params: Dict[str, Any] = {
            "progress_id": progress_id,
            "title": title,
        }
        if progress is not None:
            params["progress"] = progress
        if status_text is not None:
            params["status_text"] = status_text
        if session_id is not None:
            params["session_id"] = session_id

        result = await self._send_request("progress.create", params)
        return result.get("progress_id", progress_id)

    async def progress_update(
        self,
        progress_id: str,
        progress: Optional[float] = None,
        status_text: Optional[str] = None,
        title: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """Update an existing progress bar.

        Args:
            progress_id: ID of the progress bar to update
            progress: New progress value 0-1
            status_text: New status text
            title: New title
            session_id: Optional session ID

        Returns:
            True if updated successfully
        """
        params: Dict[str, Any] = {"progress_id": progress_id}
        if progress is not None:
            params["progress"] = progress
        if status_text is not None:
            params["status_text"] = status_text
        if title is not None:
            params["title"] = title
        if session_id is not None:
            params["session_id"] = session_id

        result = await self._send_request("progress.update", params)
        return result.get("updated", False)

    async def progress_complete(
        self,
        progress_id: str,
        style: str = "success",
        status_text: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """Mark a progress bar as complete.

        Args:
            progress_id: ID of the progress bar
            style: Completion style ("success", "error", "cancelled")
            status_text: Final status text
            session_id: Optional session ID

        Returns:
            True if completed successfully
        """
        params: Dict[str, Any] = {
            "progress_id": progress_id,
            "style": style,
        }
        if status_text is not None:
            params["status_text"] = status_text
        if session_id is not None:
            params["session_id"] = session_id

        result = await self._send_request("progress.complete", params)
        return result.get("completed", False)

    async def progress_add_action(
        self,
        progress_id: str,
        action_id: str,
        label: str,
        style: str = "secondary",
        url_scheme: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """Add an action button to a progress bar.

        Args:
            progress_id: ID of the progress bar
            action_id: Unique ID for this action
            label: Button label text
            style: Button style ("primary", "secondary", "destructive")
            url_scheme: Optional URL to open when clicked (e.g., "file:///path")
            session_id: Optional session ID

        Returns:
            True if added successfully
        """
        params: Dict[str, Any] = {
            "progress_id": progress_id,
            "action_id": action_id,
            "label": label,
            "style": style,
        }
        if url_scheme is not None:
            params["url_scheme"] = url_scheme
        if session_id is not None:
            params["session_id"] = session_id

        result = await self._send_request("progress.add_action", params)
        return result.get("added", False)

    async def progress_remove(
        self,
        progress_id: str,
        session_id: Optional[str] = None,
    ) -> bool:
        """Remove/dismiss a progress bar.

        Args:
            progress_id: ID of the progress bar to remove
            session_id: Optional session ID

        Returns:
            True if removed successfully
        """
        params: Dict[str, Any] = {"progress_id": progress_id}
        if session_id is not None:
            params["session_id"] = session_id

        result = await self._send_request("progress.remove", params)
        return result.get("removed", False)
