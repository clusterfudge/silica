"""
Voice Client for Silica.

This module provides a WebSocket client that bridges voice I/O
(listener, transcriber, speaker) with the silica serve WebSocket protocol.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from silica.serve.protocol import (
    PROTOCOL_VERSION,
    InterruptMessage,
    UserInputMessage,
)
from silica.voice.coordinator import VoiceCoordinator, VoiceState
from silica.voice.listener import Listener
from silica.voice.speaker import AudioPlayer, Speaker
from silica.voice.transcriber import Transcriber

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _check_websockets_available():
    """Check if websockets is installed."""
    try:
        import websockets  # noqa: F401

        return True
    except ImportError:
        raise ImportError(
            "websockets package required for voice client. "
            "Install with: pip install silica[voice]"
        )


@dataclass
class VoiceClientSettings:
    """Settings for the voice client."""

    # Server connection
    server_url: str = "ws://localhost:8765/ws"
    session_id: Optional[str] = None
    reconnect_delay: float = 5.0
    max_reconnect_attempts: int = 10

    # Audio settings
    device_index: Optional[int] = None
    device_name: Optional[str] = None
    vad_aggressiveness: int = 3
    min_phrase_ms: int = 300
    phrase_padding_ms: int = 500
    phrase_end_ms: int = 800

    # TTS settings
    tts_voice: str = "en-US-GuyNeural"


class VoiceClient:
    """
    WebSocket client for voice interaction with silica serve.

    Handles:
    - Audio capture and VAD phrase detection
    - Speech-to-text transcription
    - WebSocket communication with silica serve
    - Text-to-speech synthesis and playback
    - Mute and interruption handling
    """

    def __init__(
        self,
        transcriber: Transcriber,
        speaker: Speaker,
        settings: Optional[VoiceClientSettings] = None,
    ):
        """
        Initialize the voice client.

        Args:
            transcriber: Transcriber instance for STT
            speaker: Speaker instance for TTS
            settings: Client settings (uses defaults if not provided)
        """
        _check_websockets_available()

        self.settings = settings or VoiceClientSettings()
        self.transcriber = transcriber
        self.speaker = speaker

        # Components
        self.listener: Optional[Listener] = None
        self.player = AudioPlayer()
        self.coordinator = VoiceCoordinator()

        # WebSocket connection
        self._ws = None
        self._session_id: Optional[str] = None
        self._connected = False
        self._running = False

        # Message handling
        self._response_buffer = ""
        self._pending_response = False

        # Set up coordinator references
        self.coordinator._listener = self.listener
        self.coordinator._player = self.player

    async def connect(self) -> bool:
        """
        Connect to the silica serve WebSocket server.

        Returns:
            True if connection successful
        """
        import websockets

        url = self.settings.server_url
        if self.settings.session_id:
            url = f"{url}/{self.settings.session_id}"

        try:
            self._ws = await websockets.connect(url)
            self._connected = True
            logger.info(f"Connected to {url}")

            # Wait for session info
            data = await self._ws.recv()
            msg = json.loads(data)
            if msg.get("type") == "session_info":
                self._session_id = msg.get("session_id")
                protocol_version = msg.get("protocol_version")
                resumed = msg.get("resumed", False)
                logger.info(
                    f"Session: {self._session_id}, "
                    f"Protocol: {protocol_version}, "
                    f"Resumed: {resumed}"
                )

                if protocol_version != PROTOCOL_VERSION:
                    logger.warning(
                        f"Protocol version mismatch: "
                        f"server={protocol_version}, client={PROTOCOL_VERSION}"
                    )

            return True

        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        self._connected = False
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def run(self) -> None:
        """
        Run the voice client main loop.

        This is the main entry point that orchestrates:
        - Listening for speech
        - Transcribing audio
        - Sending to server
        - Receiving and speaking responses
        """
        import websockets.exceptions

        self._running = True

        # Set up listener
        self.listener = Listener(
            device_index=self.settings.device_index,
            device_name=self.settings.device_name,
            aggressiveness=self.settings.vad_aggressiveness,
            min_phrase_ms=self.settings.min_phrase_ms,
            phrase_padding_ms=self.settings.phrase_padding_ms,
            phrase_end_ms=self.settings.phrase_end_ms,
        )
        self.coordinator._listener = self.listener

        # Connect to server
        reconnect_attempts = 0
        while self._running:
            if not self._connected:
                if await self.connect():
                    reconnect_attempts = 0
                else:
                    reconnect_attempts += 1
                    if reconnect_attempts >= self.settings.max_reconnect_attempts:
                        logger.error("Max reconnection attempts reached")
                        break
                    await asyncio.sleep(self.settings.reconnect_delay)
                    continue

            try:
                # Run listen and receive loops concurrently
                await asyncio.gather(
                    self._listen_loop(),
                    self._receive_loop(),
                )
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Connection closed, reconnecting...")
                self._connected = False
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                self._connected = False

        await self.disconnect()

    async def _listen_loop(self) -> None:
        """Listen for speech and send to server."""
        while self._running and self._connected:
            # Skip listening if muted or speaking
            if self.coordinator.muted or self.coordinator.state == VoiceState.SPEAKING:
                await asyncio.sleep(0.1)
                continue

            self.coordinator.start_listening()

            # Listen for a phrase
            audio_data = await self.listener.listen_for_phrase_async(
                on_phrase_start=self.coordinator.phrase_started,
                on_phrase_end=self.coordinator.phrase_ended,
            )

            if audio_data is None:
                # Interrupted or timed out
                continue

            # Transcribe
            self.coordinator.transcription_started()
            try:
                result = await self.transcriber.transcribe(audio_data)
                text = result.text.strip()
            except Exception as e:
                logger.error(f"Transcription failed: {e}")
                self.coordinator.processing_complete()
                continue

            self.coordinator.transcription_complete(text)

            if not text:
                logger.info("Empty transcription, skipping")
                self.coordinator.processing_complete()
                continue

            # Send to server
            await self._send_user_input(text)

    async def _receive_loop(self) -> None:
        """Receive messages from server and handle them."""
        while self._running and self._connected and self._ws:
            try:
                data = await self._ws.recv()
                await self._handle_message(data)
            except Exception as e:
                # Re-raise connection errors to be handled by main loop
                import websockets.exceptions

                if isinstance(e, websockets.exceptions.ConnectionClosed):
                    raise
                logger.error(f"Error receiving message: {e}")

    async def _handle_message(self, data: str) -> None:
        """Handle an incoming message from the server."""
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON: {data[:100]}")
            return

        msg_type = msg.get("type")

        if msg_type == "assistant_chunk":
            # Buffer streaming content
            self._response_buffer += msg.get("content", "")
            self._pending_response = True

        elif msg_type == "assistant_complete":
            # Speak the complete response
            text = msg.get("content", "")
            if text:
                await self._speak_response(text)
            self._response_buffer = ""
            self._pending_response = False

        elif msg_type == "system_message":
            # Log system messages
            content = msg.get("content", "")
            logger.info(f"[System] {content}")

        elif msg_type == "tool_use":
            # Log tool use
            tool_name = msg.get("tool_name", "")
            logger.info(f"[Tool] Using: {tool_name}")

        elif msg_type == "tool_result":
            # Log tool result
            tool_name = msg.get("tool_name", "")
            is_error = msg.get("is_error", False)
            status = "error" if is_error else "complete"
            logger.info(f"[Tool] {tool_name}: {status}")

        elif msg_type == "status":
            # Log status
            message = msg.get("message", "")
            active = msg.get("active", True)
            if active:
                logger.info(f"[Status] {message}")

        elif msg_type == "permission_request":
            # Handle permission request
            await self._handle_permission_request(msg)

        elif msg_type == "error":
            # Handle error
            code = msg.get("code", "UNKNOWN")
            message = msg.get("message", "")
            logger.error(f"[Error] {code}: {message}")

        elif msg_type == "token_count":
            # Log token usage
            total = msg.get("total_tokens", 0)
            cost = msg.get("total_cost", 0)
            logger.info(f"[Tokens] {total} (${cost:.4f})")

        elif msg_type == "pong":
            # Keepalive response
            pass

        else:
            logger.debug(f"Unhandled message type: {msg_type}")

    async def _send_user_input(self, text: str) -> None:
        """Send user input to the server."""
        if not self._ws:
            return

        msg = UserInputMessage(content=text)
        await self._ws.send(msg.model_dump_json())
        logger.info(f"Sent: {text[:50]}...")

    async def _send_interrupt(self, reason: str = "User interrupt") -> None:
        """Send interrupt to the server."""
        if not self._ws:
            return

        msg = InterruptMessage(reason=reason)
        await self._ws.send(msg.model_dump_json())
        logger.info("Sent interrupt")

    async def _handle_permission_request(self, msg: dict) -> None:
        """Handle a permission request from the server."""
        # For now, auto-allow (in a real implementation, this would
        # prompt the user via voice or UI)
        request_id = msg.get("request_id")
        action = msg.get("action")
        resource = msg.get("resource")

        logger.info(f"Permission requested: {action} on {resource}")

        # Auto-allow for voice client
        response = {
            "type": "permission_response",
            "request_id": request_id,
            "allowed": True,
        }
        if self._ws:
            await self._ws.send(json.dumps(response))

    async def _speak_response(self, text: str) -> None:
        """Synthesize and speak a response."""
        if self.coordinator.muted:
            return

        self.coordinator.speech_started(text)

        try:
            # Check for interrupt before synthesis
            if self.coordinator.is_interrupted():
                self.coordinator.clear_interrupt()
                self.coordinator.speech_complete()
                return

            # Synthesize speech
            result = await self.speaker.synthesize(text)

            # Check for interrupt before playback
            if self.coordinator.is_interrupted():
                self.coordinator.clear_interrupt()
                self.coordinator.speech_complete()
                return

            # Play audio
            await self.player.play(result, block=True)

        except Exception as e:
            logger.error(f"Speech error: {e}")
        finally:
            self.coordinator.speech_complete()

    def stop(self) -> None:
        """Stop the voice client."""
        self._running = False
        self.coordinator.interrupt()


async def run_voice_client(
    server_url: str = "ws://localhost:8765/ws",
    transcriber_backend: str = "remote_whisper",
    transcriber_kwargs: Optional[dict] = None,
    speaker_backend: str = "edge",
    speaker_kwargs: Optional[dict] = None,
    **settings_kwargs,
) -> None:
    """
    Run the voice client with specified settings.

    Args:
        server_url: WebSocket server URL
        transcriber_backend: Transcriber backend name
        transcriber_kwargs: Additional transcriber arguments
        speaker_backend: Speaker backend name
        speaker_kwargs: Additional speaker arguments
        **settings_kwargs: Additional VoiceClientSettings arguments
    """
    from silica.voice.transcriber import create_transcriber
    from silica.voice.speaker import create_speaker

    transcriber = create_transcriber(
        transcriber_backend,
        **(transcriber_kwargs or {}),
    )
    speaker = create_speaker(
        speaker_backend,
        **(speaker_kwargs or {}),
    )

    settings = VoiceClientSettings(
        server_url=server_url,
        **settings_kwargs,
    )

    client = VoiceClient(
        transcriber=transcriber,
        speaker=speaker,
        settings=settings,
    )

    await client.run()
