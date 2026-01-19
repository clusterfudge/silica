"""
WebSocket Server for Silica.

This module provides the FastAPI/Starlette WebSocket server that handles
client connections and bridges them to silica agent sessions.
"""

import asyncio
import logging
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from silica.developer.context import AgentContext
from silica.developer.models import get_model
from silica.developer.sandbox import SandboxMode
from silica.serve.protocol import (
    PROTOCOL_VERSION,
    ErrorMessage,
    InterruptMessage,
    PermissionResponseMessage,
    PingMessage,
    PongMessage,
    ServerMessage,
    SessionInfoMessage,
    UserInputMessage,
    parse_client_message,
    serialize_server_message,
    ProtocolError,
)
from silica.serve.ws_interface import WebSocketUserInterface

logger = logging.getLogger(__name__)


class ConnectionState:
    """State for a single WebSocket connection."""

    def __init__(self, websocket: WebSocket, session_id: str):
        self.websocket = websocket
        self.session_id = session_id
        self.agent_context: Optional[AgentContext] = None
        self.user_interface: Optional[WebSocketUserInterface] = None
        self.input_queue: asyncio.Queue[str] = asyncio.Queue()
        self.agent_task: Optional[asyncio.Task] = None
        self.interrupted = False

    async def send(self, message: ServerMessage) -> None:
        """Send a message to the client."""
        try:
            data = serialize_server_message(message)
            await self.websocket.send_text(data)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")

    async def receive_input(self) -> str:
        """Wait for user input from the queue."""
        return await self.input_queue.get()


class SilicaWebSocketServer:
    """
    WebSocket server for Silica agent sessions.

    Handles multiple concurrent connections, each with its own agent context.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        model: str = "sonnet",
        sandbox_mode: SandboxMode = SandboxMode.REMEMBER_ALL,
        persona_base_dir: Optional[Path] = None,
    ):
        self.host = host
        self.port = port
        self.model = model
        self.sandbox_mode = sandbox_mode
        self.persona_base_dir = persona_base_dir or (
            Path.home() / ".silica" / "personas" / "default"
        )
        self.connections: Dict[str, ConnectionState] = {}
        self.app = self._create_app()

    def _create_app(self) -> Starlette:
        """Create the Starlette application with WebSocket routes."""
        routes = [
            WebSocketRoute("/ws", self._handle_websocket),
            WebSocketRoute("/ws/{session_id}", self._handle_websocket),
        ]
        return Starlette(routes=routes, on_startup=[self._on_startup])

    async def _on_startup(self) -> None:
        """Startup handler for the application."""
        logger.info(f"Silica WebSocket server starting on ws://{self.host}:{self.port}")
        logger.info(f"Protocol version: {PROTOCOL_VERSION}")

    async def _handle_websocket(self, websocket: WebSocket) -> None:
        """Handle a WebSocket connection."""
        await websocket.accept()

        # Get session ID from path or generate new one
        session_id = websocket.path_params.get("session_id") or str(uuid4())
        resumed = session_id in self.connections

        # Create connection state
        conn = ConnectionState(websocket, session_id)
        self.connections[session_id] = conn

        try:
            # Create user interface
            conn.user_interface = WebSocketUserInterface(
                send_callback=conn.send,
                receive_callback=conn.receive_input,
                session_id=session_id,
            )

            # Create or resume agent context
            conn.agent_context = self._create_agent_context(conn, session_id, resumed)

            # Send session info
            await conn.send(
                SessionInfoMessage(
                    session_id=session_id,
                    protocol_version=PROTOCOL_VERSION,
                    resumed=resumed,
                    message_count=len(conn.agent_context.chat_history)
                    if conn.agent_context
                    else 0,
                )
            )

            # Start message handling loop
            await self._message_loop(conn)

        except WebSocketDisconnect:
            logger.info(f"Client disconnected from session {session_id}")
        except Exception as e:
            logger.error(f"Error in session {session_id}: {e}", exc_info=True)
            try:
                await conn.send(
                    ErrorMessage(
                        code="SERVER_ERROR",
                        message=str(e),
                        recoverable=False,
                    )
                )
            except Exception:
                pass
        finally:
            # Clean up
            if conn.agent_task and not conn.agent_task.done():
                conn.agent_task.cancel()
            # Keep connection in dict for potential resume
            # Could add timeout-based cleanup later

    def _create_agent_context(
        self, conn: ConnectionState, session_id: str, resumed: bool
    ) -> AgentContext:
        """Create or resume an agent context for the connection."""
        model_spec = get_model(self.model)

        # Create sandbox with the WebSocket interface's permission callback
        from silica.developer.sandbox import Sandbox

        sandbox = Sandbox(
            str(Path.cwd()),
            mode=self.sandbox_mode,
            permission_check_callback=conn.user_interface.permission_callback,
            permission_check_rendering_callback=conn.user_interface.permission_rendering_callback,
        )

        # Create memory manager
        from silica.developer.memory import MemoryManager

        memory_manager = MemoryManager(base_dir=self.persona_base_dir / "memory")

        context = AgentContext(
            session_id=session_id,
            parent_session_id=None,
            model_spec=model_spec,
            sandbox=sandbox,
            user_interface=conn.user_interface,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=self.persona_base_dir,
        )

        # If resuming, try to load session
        if resumed:
            # Load existing context - for now this is a placeholder
            # Full implementation would load from session store
            pass

        return context

    async def _message_loop(self, conn: ConnectionState) -> None:
        """Main message handling loop for a connection."""
        while True:
            try:
                data = await conn.websocket.receive_text()
                await self._handle_message(conn, data)
            except WebSocketDisconnect:
                raise
            except Exception as e:
                logger.error(f"Error handling message: {e}", exc_info=True)
                await conn.send(
                    ErrorMessage(
                        code="MESSAGE_ERROR",
                        message=str(e),
                        recoverable=True,
                    )
                )

    async def _handle_message(self, conn: ConnectionState, data: str) -> None:
        """Handle an incoming message from a client."""
        try:
            message = parse_client_message(data)
        except ProtocolError as e:
            await conn.send(
                ErrorMessage(
                    code=e.code,
                    message=e.message,
                    details=e.details,
                    recoverable=True,
                )
            )
            return

        # Route message by type
        if isinstance(message, UserInputMessage):
            await self._handle_user_input(conn, message)
        elif isinstance(message, InterruptMessage):
            await self._handle_interrupt(conn, message)
        elif isinstance(message, PermissionResponseMessage):
            await self._handle_permission_response(conn, message)
        elif isinstance(message, PingMessage):
            await conn.send(PongMessage())
        else:
            await conn.send(
                ErrorMessage(
                    code="UNSUPPORTED_MESSAGE",
                    message=f"Message type not yet supported: {type(message).__name__}",
                    recoverable=True,
                )
            )

    async def _handle_user_input(
        self, conn: ConnectionState, message: UserInputMessage
    ) -> None:
        """Handle user input message."""
        # If there's an ongoing agent task waiting for input, provide it
        if conn.agent_task and not conn.agent_task.done():
            await conn.input_queue.put(message.content)
        else:
            # Start a new agent turn
            conn.agent_task = asyncio.create_task(
                self._run_agent_turn(conn, message.content)
            )

    async def _handle_interrupt(
        self, conn: ConnectionState, message: InterruptMessage
    ) -> None:
        """Handle interrupt message."""
        conn.interrupted = True
        if conn.agent_task and not conn.agent_task.done():
            conn.agent_task.cancel()
            await conn.send(
                ErrorMessage(
                    code="INTERRUPTED",
                    message=message.reason or "Agent interrupted by user",
                    recoverable=True,
                )
            )

    async def _handle_permission_response(
        self, conn: ConnectionState, message: PermissionResponseMessage
    ) -> None:
        """Handle permission response message."""
        if conn.user_interface:
            result = message.allowed
            if message.allowed and message.mode:
                result = message.mode.value
            conn.user_interface.fulfill_permission_request(message.request_id, result)

    async def _run_agent_turn(self, conn: ConnectionState, user_input: str) -> None:
        """Run a single agent turn with the given user input."""
        try:
            # Import here to avoid circular imports
            from silica.developer.agent_loop import run

            # Run the agent loop for one turn
            # This is a simplified version - full implementation would
            # integrate more deeply with the agent loop
            await run(
                agent_context=conn.agent_context,
                initial_message=user_input,
                single_turn=True,
            )
        except asyncio.CancelledError:
            logger.info(f"Agent turn cancelled for session {conn.session_id}")
        except Exception as e:
            logger.error(f"Error in agent turn: {e}", exc_info=True)
            await conn.send(
                ErrorMessage(
                    code="AGENT_ERROR",
                    message=str(e),
                    recoverable=True,
                )
            )
        finally:
            # Flush any pending assistant message
            if conn.user_interface:
                conn.user_interface.flush_assistant_message()


def create_server(
    host: str = "0.0.0.0",
    port: int = 8765,
    model: str = "sonnet",
    sandbox_mode: SandboxMode = SandboxMode.REMEMBER_ALL,
    persona_base_dir: Optional[Path] = None,
) -> SilicaWebSocketServer:
    """Create a new SilicaWebSocketServer instance."""
    return SilicaWebSocketServer(
        host=host,
        port=port,
        model=model,
        sandbox_mode=sandbox_mode,
        persona_base_dir=persona_base_dir,
    )


async def run_server(
    host: str = "0.0.0.0",
    port: int = 8765,
    model: str = "sonnet",
    sandbox_mode: SandboxMode = SandboxMode.REMEMBER_ALL,
    persona_base_dir: Optional[Path] = None,
) -> None:
    """Run the WebSocket server."""
    import uvicorn

    server = create_server(
        host=host,
        port=port,
        model=model,
        sandbox_mode=sandbox_mode,
        persona_base_dir=persona_base_dir,
    )

    config = uvicorn.Config(
        server.app,
        host=host,
        port=port,
        log_level="info",
    )
    uvicorn_server = uvicorn.Server(config)
    await uvicorn_server.serve()
