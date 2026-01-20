"""
WebSocket User Interface for Silica.

This module provides a UserInterface implementation that communicates
over WebSocket using the JSONL protocol defined in protocol.py.
"""

import asyncio
import contextlib
import json
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from silica.developer.sandbox import SandboxMode
from silica.developer.user_interface import PermissionResult, UserInterface
from silica.serve.protocol import (
    AssistantMessageChunk,
    AssistantMessageComplete,
    PermissionRequestMessage,
    ServerMessage,
    StatusMessage,
    SystemMessage,
    ThinkingMessage,
    TokenCountMessage,
    ToolResultMessage,
    ToolUseMessage,
)


class WebSocketUserInterface(UserInterface):
    """
    UserInterface implementation that communicates over WebSocket.

    This class bridges the silica agent loop with a WebSocket client,
    serializing all interactions to JSONL messages.
    """

    def __init__(
        self,
        send_callback: callable,
        receive_callback: callable,
        session_id: str,
    ):
        """
        Initialize the WebSocket interface.

        Args:
            send_callback: Async function to send messages (takes ServerMessage)
            receive_callback: Async function to receive permission responses
            session_id: ID of the session
        """
        self._send = send_callback
        self._receive = receive_callback
        self._session_id = session_id
        self._current_message_id: Optional[str] = None
        self._message_buffer: str = ""
        self._pending_permission_requests: Dict[str, asyncio.Future] = {}
        self._status_stack: List[str] = []

    async def _send_message(self, message: ServerMessage) -> None:
        """Send a message to the client."""
        await self._send(message)

    def _sync_send(self, message: ServerMessage) -> None:
        """Synchronously schedule a message send (for non-async methods)."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._send_message(message))
        except RuntimeError:
            # No running loop - we're in sync context
            # This shouldn't happen in normal operation but handle gracefully
            pass

    # =========================================================================
    # Assistant Message Handling (Streaming)
    # =========================================================================

    def handle_assistant_message(self, message: str) -> None:
        """
        Handle and display a new message from the assistant.

        For streaming, this receives chunks. We send each chunk immediately
        and buffer for the complete message.
        """
        if self._current_message_id is None:
            self._current_message_id = str(uuid4())
            self._message_buffer = ""

        self._message_buffer += message

        chunk = AssistantMessageChunk(
            content=message,
            message_id=self._current_message_id,
        )
        self._sync_send(chunk)

    def flush_assistant_message(self) -> None:
        """
        Flush the current assistant message buffer.

        Call this when the assistant turn is complete to send the
        AssistantMessageComplete message.
        """
        if self._current_message_id is not None:
            complete = AssistantMessageComplete(
                content=self._message_buffer,
                message_id=self._current_message_id,
            )
            self._sync_send(complete)
            self._current_message_id = None
            self._message_buffer = ""

    # =========================================================================
    # System Message Handling
    # =========================================================================

    def handle_system_message(
        self, message: str, markdown: bool = True, live=None
    ) -> None:
        """Handle and display a system message."""
        msg = SystemMessage(
            content=message,
            markdown=markdown,
            level="info",
        )
        self._sync_send(msg)

    # =========================================================================
    # Permission Handling
    # =========================================================================

    def permission_callback(
        self,
        action: str,
        resource: str,
        sandbox_mode: SandboxMode,
        action_arguments: Optional[Dict] = None,
        group: Optional[str] = None,
    ) -> PermissionResult:
        """
        Permission check callback with enhanced options.

        This sends a permission request to the client and waits for a response.
        Since this is synchronous but needs async I/O, we use asyncio.run_coroutine_threadsafe
        or an event-based approach.
        """
        # For now, in WebSocket mode, we need to handle this asynchronously
        # This is a simplified implementation that will be enhanced
        request_id = str(uuid4())

        request = PermissionRequestMessage(
            request_id=request_id,
            action=action,
            resource=resource,
            group=group,
            action_arguments=action_arguments,
        )
        self._sync_send(request)

        # Create a future to wait for the response
        # This requires the receive loop to fulfill it
        future = asyncio.get_running_loop().create_future()
        self._pending_permission_requests[request_id] = future

        # In a full implementation, we'd wait for the response
        # For now, return a default based on sandbox mode
        if sandbox_mode == SandboxMode.ALLOW_ALL:
            return True

        # Block and wait for response (this is complex in sync context)
        # For initial implementation, we'll need the caller to be async-aware
        try:
            # Try to wait for the response with a timeout
            asyncio.get_running_loop()
            # This won't work in sync context - needs refactoring
            # For now, default deny
            return False
        except RuntimeError:
            return False

    async def async_permission_callback(
        self,
        action: str,
        resource: str,
        sandbox_mode: SandboxMode,
        action_arguments: Optional[Dict] = None,
        group: Optional[str] = None,
        timeout: float = 30.0,
    ) -> PermissionResult:
        """
        Async version of permission callback.

        This is the preferred method when running in async context.
        """
        if sandbox_mode == SandboxMode.ALLOW_ALL:
            return True

        request_id = str(uuid4())

        request = PermissionRequestMessage(
            request_id=request_id,
            action=action,
            resource=resource,
            group=group,
            action_arguments=action_arguments,
        )
        await self._send_message(request)

        # Create a future for the response
        future = asyncio.get_running_loop().create_future()
        self._pending_permission_requests[request_id] = future

        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            del self._pending_permission_requests[request_id]
            return False

    def fulfill_permission_request(
        self,
        request_id: str,
        result: PermissionResult,
    ) -> None:
        """
        Fulfill a pending permission request.

        Called by the message receive loop when a permission_response arrives.
        """
        future = self._pending_permission_requests.pop(request_id, None)
        if future and not future.done():
            future.set_result(result)

    def permission_rendering_callback(
        self,
        action: str,
        resource: str,
        action_arguments: Optional[Dict] = None,
    ) -> None:
        """Render permission request (no-op for WebSocket - request message handles it)."""

    # =========================================================================
    # Tool Use Handling
    # =========================================================================

    def handle_tool_use(
        self,
        tool_name: str,
        tool_params: Dict[str, Any],
    ) -> None:
        """Handle and display information about a tool being used."""
        # Generate a tool_use_id - in practice this comes from the API
        tool_use_id = tool_params.get("tool_use_id", str(uuid4()))

        msg = ToolUseMessage(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            tool_params=tool_params,
        )
        self._sync_send(msg)

    def handle_tool_result(self, name: str, result: Dict[str, Any], live=None) -> None:
        """Handle and display the result of a tool use."""
        tool_use_id = result.get("tool_use_id", "unknown")
        is_error = result.get("is_error", False)
        truncated = result.get("truncated", False)

        msg = ToolResultMessage(
            tool_use_id=tool_use_id,
            tool_name=name,
            result=result,
            is_error=is_error,
            truncated=truncated,
        )
        self._sync_send(msg)

    # =========================================================================
    # User Input Handling
    # =========================================================================

    async def get_user_input(self, prompt: str = "") -> str:
        """
        Get input from the user.

        For WebSocket, this waits for a user_input message from the client.
        """
        if prompt:
            await self._send_message(
                SystemMessage(content=prompt, markdown=False, level="info")
            )

        # Wait for user input via the receive callback
        return await self._receive()

    def handle_user_input(self, user_input: str) -> str:
        """Handle and display input from the user."""
        # For WebSocket, we don't need to echo - client already has it
        return user_input

    # =========================================================================
    # Token Count Display
    # =========================================================================

    def display_token_count(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        total_cost: float,
        cached_tokens: Optional[int] = None,
        conversation_size: Optional[int] = None,
        context_window: Optional[int] = None,
        thinking_tokens: Optional[int] = None,
        thinking_cost: Optional[float] = None,
        elapsed_seconds: Optional[float] = None,
        plan_slug: Optional[str] = None,
        plan_tasks_completed: Optional[int] = None,
        plan_tasks_verified: Optional[int] = None,
        plan_tasks_total: Optional[int] = None,
    ) -> None:
        """Display token count information."""
        # Flush any pending assistant message first
        self.flush_assistant_message()

        msg = TokenCountMessage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            total_cost=total_cost,
            cached_tokens=cached_tokens,
            thinking_tokens=thinking_tokens,
            thinking_cost=thinking_cost,
            elapsed_seconds=elapsed_seconds,
        )
        self._sync_send(msg)

    # =========================================================================
    # Status and Welcome
    # =========================================================================

    def display_welcome_message(self) -> None:
        """Display a welcome message to the user."""
        self._sync_send(
            SystemMessage(
                content="Connected to Silica agent session.",
                markdown=False,
                level="info",
            )
        )

    @contextlib.contextmanager
    def status(self, message: str, spinner: Optional[str] = None):
        """Display a status message to the user."""
        status_id = str(uuid4())
        self._status_stack.append(status_id)

        # Send status start
        self._sync_send(
            StatusMessage(
                message=message,
                active=True,
                spinner=spinner,
            )
        )

        try:
            yield
        finally:
            self._status_stack.pop()
            # Send status end
            self._sync_send(
                StatusMessage(
                    message=message,
                    active=False,
                    spinner=None,
                )
            )

    def bare(self, message: Union[str, Any], live=None) -> None:
        """Display bare message to the user."""
        content = str(message) if not isinstance(message, str) else message
        self._sync_send(
            SystemMessage(
                content=content,
                markdown=False,
                level="info",
            )
        )

    # =========================================================================
    # Thinking Content
    # =========================================================================

    def handle_thinking_content(
        self, content: str, tokens: int, cost: float, collapsed: bool = True
    ) -> None:
        """Handle and display thinking content from the model."""
        msg = ThinkingMessage(
            content=content,
            tokens=tokens,
            cost=cost,
            collapsed=collapsed,
        )
        self._sync_send(msg)

    def update_thinking_status(self, tokens: int, budget: int, cost: float) -> None:
        """Update the status display with thinking progress."""
        # Send as a status message with thinking info
        self._sync_send(
            StatusMessage(
                message=f"Thinking... ({tokens}/{budget} tokens, ${cost:.4f})",
                active=True,
                spinner="dots",
            )
        )

    # =========================================================================
    # User Choice (Interactive Selection)
    # =========================================================================

    async def get_user_choice(self, question: str, options: List[str]) -> str:
        """
        Present multiple options to the user and get their selection.

        For WebSocket clients, we send the options and wait for a response.
        The client is responsible for rendering the choice UI.
        """
        # Send the question and options as a system message with special format
        options_formatted = {
            "question": question,
            "options": options,
            "type": "user_choice",
        }
        self._sync_send(
            SystemMessage(
                content=json.dumps(options_formatted),
                markdown=False,
                level="info",
            )
        )

        # Wait for user response
        response = await self._receive()
        return response

    async def get_session_choice(self, sessions: List[Dict[str, Any]]) -> Optional[str]:
        """
        Present an interactive selector for session resumption.

        For WebSocket clients, we send session info and wait for selection.
        """
        if not sessions:
            return None

        # Format sessions for client
        sessions_formatted = {
            "sessions": sessions,
            "type": "session_choice",
        }
        self._sync_send(
            SystemMessage(
                content=json.dumps(sessions_formatted),
                markdown=False,
                level="info",
            )
        )

        # Wait for user response
        response = await self._receive()
        if response == "cancelled":
            return None
        return response
