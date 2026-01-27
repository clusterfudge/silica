"""Agent Island IPC Client.

Provides async communication with the Agent Island macOS app over Unix socket.
Includes automatic reconnection with exponential backoff, session re-registration,
heartbeat detection, and silent failure mode.
"""

import asyncio
import json
import logging
import os
import random
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
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

logger = logging.getLogger(__name__)

DEFAULT_SOCKET_PATH = "~/.agent-island/agent.sock"
PROTOCOL_VERSION = "1.0"

# Reconnection constants
RECONNECT_BASE_DELAY = 0.5  # Initial delay in seconds
RECONNECT_MAX_DELAY = 16.0  # Maximum delay cap
RECONNECT_MAX_ATTEMPTS = 20  # Stop after this many attempts
HEARTBEAT_INTERVAL = 30.0  # Seconds between heartbeat pings

InputCallback = Any
ProgressActionCallback = Any
ReconnectedCallback = Callable[[], None]


class IslandClient:
    """Async client for Agent Island IPC communication.

    Features:
    - Automatic reconnection with exponential backoff when connection drops
    - Session re-registration after reconnection
    - Heartbeat/ping to detect disconnection proactively
    - Silent failure mode for fire-and-forget operations when disconnected
    """

    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET_PATH,
        app_name: str = "silica",
        app_icon: str = "brain",
        agent_version: str = "1.0.0",
        auto_reconnect: bool = True,
    ):
        self.socket_path = Path(socket_path).expanduser()
        self.app_name = app_name
        self.app_icon = app_icon
        self.agent_version = agent_version
        self.auto_reconnect = auto_reconnect

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._request_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}
        self._read_task: Optional[asyncio.Task] = None
        self._connected = False
        self._island_version: Optional[str] = None
        self._supported_methods: List[str] = []

        # Reconnection state
        self._intentional_disconnect = False
        self._reconnecting = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._reconnect_attempts = 0

        # Heartbeat state
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Session state for re-registration
        self._session_info: Optional[Dict[str, Any]] = None

        # Callbacks
        self.on_input_received: Optional[InputCallback] = None
        self.on_progress_action: Optional[ProgressActionCallback] = None
        self.on_reconnected: Optional[ReconnectedCallback] = None

    @property
    def connected(self) -> bool:
        """Check if connected to Agent Island."""
        return self._connected and self._writer is not None

    @property
    def reconnecting(self) -> bool:
        """Check if currently attempting to reconnect."""
        return self._reconnecting

    @property
    def island_version(self) -> Optional[str]:
        """Get the connected Island's version."""
        return self._island_version

    async def __aenter__(self) -> "IslandClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()

    def socket_exists(self) -> bool:
        """Check if the socket file exists."""
        return self.socket_path.exists()

    async def connect(self) -> bool:
        """Connect to Agent Island. Returns True if successful."""
        if self._connected:
            return True

        if not self.socket_exists():
            return False

        try:
            self._reader, self._writer = await asyncio.open_unix_connection(
                str(self.socket_path)
            )
            self._read_task = asyncio.create_task(self._reader_loop())

            if not await self._handshake():
                await self._close_connection_internal()
                return False

            self._connected = True
            self._intentional_disconnect = False
            self._reconnect_attempts = 0

            # Start heartbeat
            self._start_heartbeat()

            logger.debug("Connected to Agent Island")
            return True

        except (OSError, ConnectionRefusedError, FileNotFoundError):
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from Agent Island (intentional - no reconnection)."""
        self._intentional_disconnect = True
        self._stop_reconnection()
        self._stop_heartbeat()
        await self._close_connection_internal()
        logger.debug("Disconnected from Agent Island")

    async def _close_connection_internal(self) -> None:
        """Close connection without triggering reconnection."""
        self._connected = False
        self._stop_heartbeat()

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

        for future in self._pending_requests.values():
            if not future.done():
                future.set_exception(ConnectionError("Connection closed"))
        self._pending_requests.clear()

    def _start_heartbeat(self) -> None:
        """Start the heartbeat task."""
        self._stop_heartbeat()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def _stop_heartbeat(self) -> None:
        """Stop the heartbeat task."""
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        """Background task that sends periodic pings."""
        try:
            while self._connected:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if not self._connected:
                    break
                try:
                    # Use a simple request as ping - handshake info is lightweight
                    await self._send_request("system.ping", {}, timeout=5.0)
                except Exception:
                    # Ping failed - connection is likely dead
                    if self._connected and not self._intentional_disconnect:
                        logger.info("Heartbeat failed - connection lost")
                        await self._handle_connection_lost()
                    break
        except asyncio.CancelledError:
            pass

    async def _handle_connection_lost(self) -> None:
        """Handle unexpected connection loss."""
        was_connected = self._connected
        await self._close_connection_internal()

        if was_connected and self.auto_reconnect and not self._intentional_disconnect:
            logger.info("Connection to Agent Island lost, will attempt reconnection")
            self._start_reconnection()

    def _start_reconnection(self) -> None:
        """Start the reconnection task if not already running."""
        if self._reconnecting or self._intentional_disconnect:
            return
        self._reconnecting = True
        self._reconnect_task = asyncio.create_task(self._reconnection_loop())

    def _stop_reconnection(self) -> None:
        """Stop any ongoing reconnection attempts."""
        self._reconnecting = False
        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

    async def _reconnection_loop(self) -> None:
        """Background task that attempts reconnection with exponential backoff."""
        try:
            while self._reconnecting and not self._intentional_disconnect:
                if self._reconnect_attempts >= RECONNECT_MAX_ATTEMPTS:
                    logger.warning(
                        f"Giving up reconnection after {RECONNECT_MAX_ATTEMPTS} attempts"
                    )
                    break

                # Exponential backoff with jitter
                delay = min(
                    RECONNECT_BASE_DELAY * (2**self._reconnect_attempts),
                    RECONNECT_MAX_DELAY,
                )
                delay *= 0.5 + random.random()  # Add jitter

                self._reconnect_attempts += 1
                logger.debug(
                    f"Reconnection attempt {self._reconnect_attempts} in {delay:.1f}s"
                )

                await asyncio.sleep(delay)

                if self._intentional_disconnect:
                    break

                if await self.connect():
                    logger.info("Reconnected to Agent Island")
                    await self._on_reconnected()
                    break

        except asyncio.CancelledError:
            pass
        finally:
            self._reconnecting = False
            self._reconnect_task = None

    async def _on_reconnected(self) -> None:
        """Called after successful reconnection."""
        # Re-register session if we had one
        if self._session_info:
            try:
                await self.register_session(**self._session_info)
                logger.debug("Session re-registered after reconnection")
            except Exception:
                logger.debug("Failed to re-register session after reconnection")

        # Notify callback
        if self.on_reconnected:
            try:
                result = self.on_reconnected()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass

    async def _reader_loop(self) -> None:
        """Background task that reads responses from the socket."""
        try:
            while self._reader:
                line = await self._reader.readline()
                if not line:
                    # Connection closed
                    break

                try:
                    data = json.loads(line.decode("utf-8"))

                    if "id" in data and data["id"] in self._pending_requests:
                        response = JsonRpcResponse(
                            id=data["id"],
                            result=data.get("result"),
                            error=data.get("error"),
                        )
                        future = self._pending_requests.pop(data["id"])
                        if not future.done():
                            future.set_result(response)

                    elif "method" in data and "id" not in data:
                        await self._handle_notification(data)

                except json.JSONDecodeError:
                    continue

        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        finally:
            # Connection lost - trigger reconnection if appropriate
            if not self._intentional_disconnect and self._connected:
                asyncio.create_task(self._handle_connection_lost())

    async def _handle_notification(self, data: Dict[str, Any]) -> None:
        """Handle a server-initiated notification."""
        method = data.get("method", "")
        params = data.get("params", {})

        if method == "input.received":
            if self.on_input_received:
                try:
                    result = self.on_input_received(
                        params.get("session_id", ""),
                        params.get("content", ""),
                        params.get("message_id", ""),
                    )
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass

        elif method == "progress.action_clicked":
            if self.on_progress_action:
                try:
                    result = self.on_progress_action(
                        params.get("session_id", ""),
                        params.get("progress_id", ""),
                        params.get("action_id", ""),
                        params.get("url_scheme"),
                    )
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send_request(
        self,
        method: str,
        params: Dict[str, Any],
        timeout: Optional[float] = None,
        _allow_during_handshake: bool = False,
    ) -> Dict[str, Any]:
        """Send a request and wait for response."""
        if not _allow_during_handshake and not self.connected:
            raise ConnectionError("Not connected to Agent Island")

        if self._writer is None:
            raise ConnectionError("No connection to Agent Island")

        request_id = self._next_id()
        request = JsonRpcRequest(method=method, params=params, id=request_id)

        future: asyncio.Future[JsonRpcResponse] = asyncio.Future()
        self._pending_requests[request_id] = future

        try:
            self._writer.write(request.to_bytes())
            await self._writer.drain()

            if timeout:
                response = await asyncio.wait_for(future, timeout=timeout)
            else:
                response = await future

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
        """Send a notification (fire-and-forget). Silently fails if not connected."""
        if not self.connected:
            return  # Silent fail - no logging

        try:
            notification = JsonRpcNotification(method=method, params=params)
            self._writer.write(notification.to_bytes())
            await self._writer.drain()
        except Exception:
            pass  # Silent fail - no logging

    async def _handshake(self) -> bool:
        """Perform protocol handshake."""
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
        """Register a session with Agent Island."""
        # Store for re-registration on reconnect
        self._session_info = {
            "session_id": session_id,
            "working_directory": working_directory,
            "model": model,
            "persona": persona,
            # Don't store history - only needed on initial registration
        }

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
        """Unregister a session."""
        self._session_info = None  # Clear stored session
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
        try:
            result = await self._send_request("dialog.cancel", {"dialog_id": dialog_id})
            return result.get("cancelled", False)
        except (DialogNotFoundError, IslandError):
            return False

    # ========== Event Notifications (fire-and-forget) ==========

    async def notify_user_message(
        self, content: str, message_id: Optional[str] = None
    ) -> None:
        params = {"content": content}
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
        params: Dict[str, Any] = {"content": content, "format": format}
        if message_id:
            params["message_id"] = message_id
        if notification:
            params["notification"] = notification
        await self._send_notification("event.assistant_message", params)

    async def notify_tool_use(
        self, tool_name: str, tool_params: Dict[str, Any]
    ) -> None:
        await self._send_notification(
            "event.tool_use", {"tool_name": tool_name, "tool_params": tool_params}
        )

    async def notify_tool_result(
        self, tool_name: str, result: Any, success: bool = True
    ) -> None:
        await self._send_notification(
            "event.tool_result",
            {"tool_name": tool_name, "result": result, "success": success},
        )

    async def notify_thinking(
        self, content: str, tokens: int, cost: float, message_id: Optional[str] = None
    ) -> None:
        params = {"content": content, "tokens": tokens, "cost": cost}
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
        params: Dict[str, Any] = {"message": message, "spinner": spinner}
        if notification:
            params["notification"] = notification
        await self._send_notification("event.status", params)

    async def notify_system_message(
        self,
        message: str,
        style: str = "info",
        notification: Optional[Dict[str, Any]] = None,
    ) -> None:
        params: Dict[str, Any] = {"message": message, "style": style}
        if notification:
            params["notification"] = notification
        await self._send_notification("event.system_message", params)

    async def notify_ready_for_input(self, message: str = "Ready for input") -> None:
        await self._send_notification(
            "event.ready_for_input",
            {"message": message, "notification": {"style": "sound"}},
        )

    async def notify_error(self, message: str, details: Optional[str] = None) -> None:
        params: Dict[str, Any] = {
            "message": message,
            "notification": {"style": "sound"},
        }
        if details:
            params["details"] = details
        await self._send_notification("event.error", params)

    # ========== Panel Control ==========

    async def open_panel(self) -> bool:
        try:
            result = await self._send_request("ui.open", {})
            return result.get("opened", False)
        except IslandError:
            return False

    async def close_panel(self) -> bool:
        try:
            result = await self._send_request("ui.close", {})
            return result.get("closed", False)
        except IslandError:
            return False

    async def open_settings(self) -> bool:
        try:
            result = await self._send_request("ui.settings", {})
            return result.get("opened", False)
        except IslandError:
            return False

    # ========== Session Phase API ==========

    async def update_phase(self, phase: str, session_id: Optional[str] = None) -> bool:
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
        params: Dict[str, Any] = {"progress_id": progress_id, "title": title}
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
        params: Dict[str, Any] = {"progress_id": progress_id, "style": style}
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
        self, progress_id: str, session_id: Optional[str] = None
    ) -> bool:
        params: Dict[str, Any] = {"progress_id": progress_id}
        if session_id is not None:
            params["session_id"] = session_id
        result = await self._send_request("progress.remove", params)
        return result.get("removed", False)
