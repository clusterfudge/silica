"""
Voice Client for Silica.

This module provides a WebSocket client that bridges voice I/O
(listener, transcriber, speaker) with the silica serve WebSocket protocol.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING

from silica.serve.protocol import (
    PROTOCOL_VERSION,
    InterruptMessage,
    UserInputMessage,
)
from silica.voice.coordinator import VoiceCoordinator, VoiceState, KeyboardMuteManager
from silica.voice.listener import Listener
from silica.voice.relevance import RelevanceFilter
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

    # Relevance filtering (for ambient mode without wake word)
    relevance_filtering: bool = False
    wake_words: Optional[list] = (
        None  # If set, require wake word instead of relevance filter
    )

    # Mute toggle
    mute_key: str = "m"  # Key to toggle mute (keyboard mode)

    # Metrics
    metrics_enabled: bool = True


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
        relevance_filter: Optional[RelevanceFilter] = None,
    ):
        """
        Initialize the voice client.

        Args:
            transcriber: Transcriber instance for STT
            speaker: Speaker instance for TTS
            settings: Client settings (uses defaults if not provided)
            relevance_filter: Optional relevance filter for ambient mode
        """
        _check_websockets_available()

        self.settings = settings or VoiceClientSettings()
        self.transcriber = transcriber
        self.speaker = speaker

        # Components
        self.listener: Optional[Listener] = None
        self.player = AudioPlayer()
        self.coordinator = VoiceCoordinator()
        self._mute_manager: Optional[KeyboardMuteManager] = None

        # Relevance filter for ambient mode
        self.relevance_filter = relevance_filter
        if self.relevance_filter is None and self.settings.relevance_filtering:
            self.relevance_filter = RelevanceFilter(enabled=True)

        # WebSocket connection
        self._ws = None
        self._session_id: Optional[str] = None
        self._connected = False
        self._running = False

        # Message handling
        self._response_buffer = ""
        self._pending_response = False

        # Recent context for relevance filtering
        self._recent_context: list = []
        self._max_context_turns = 5

        # Metrics
        self._metrics = None
        if self.settings.metrics_enabled:
            from silica.voice.metrics import get_metrics_client

            self._metrics = get_metrics_client()

        # Set up coordinator references
        self.coordinator._listener = self.listener
        self.coordinator._player = self.player

    def _incr(self, name: str, value: int = 1) -> None:
        """Increment a counter metric."""
        if self._metrics:
            self._metrics.incr(name, value)

    def _timing(self, name: str, value_ms: float) -> None:
        """Record a timing metric."""
        if self._metrics:
            self._metrics.timing(name, value_ms)

    def _gauge(self, name: str, value: float) -> None:
        """Set a gauge metric."""
        if self._metrics:
            self._metrics.gauge(name, value)

    def _on_mute_toggle(self) -> None:
        """Handle mute toggle from keyboard or GPIO."""
        self.coordinator.muted
        is_muted = self.coordinator.toggle_mute()
        status = "MUTED" if is_muted else "LISTENING"
        logger.info(f"Mute toggled: {status}")
        print(f"\n[{status}]")

    def _add_context(self, role: str, text: str) -> None:
        """Add a turn to recent context for relevance filtering."""
        self._recent_context.append({"role": role, "text": text})
        # Keep only recent turns
        if len(self._recent_context) > self._max_context_turns:
            self._recent_context = self._recent_context[-self._max_context_turns :]

    def _get_context_string(self) -> str:
        """Get recent context as a string for relevance filtering."""
        if not self._recent_context:
            return ""
        lines = []
        for turn in self._recent_context:
            role = turn["role"].capitalize()
            text = turn["text"][:100]  # Truncate for efficiency
            lines.append(f"{role}: {text}")
        return "\n".join(lines)

    def _check_wake_word(self, text: str) -> bool:
        """Check if text contains a wake word."""
        if not self.settings.wake_words:
            return True  # No wake words configured, always pass
        text_lower = text.lower()
        return any(wake.lower() in text_lower for wake in self.settings.wake_words)

    async def _check_relevance(self, text: str) -> bool:
        """Check if transcribed text is relevant to the assistant."""
        # First check wake words if configured
        if self.settings.wake_words:
            if self._check_wake_word(text):
                self._incr("relevance.wake_word_match")
                return True
            else:
                self._incr("relevance.no_wake_word")
                return False

        # If relevance filtering is disabled, everything is relevant
        if not self.relevance_filter or not self.settings.relevance_filtering:
            return True

        # Use relevance filter
        self._incr("relevance.check")
        context = self._get_context_string()
        result = await self.relevance_filter.check_relevance_async(text, context)

        if result.is_relevant:
            self._incr("relevance.relevant")
        else:
            self._incr("relevance.not_relevant")
            logger.info(f"Filtered out: '{text[:50]}...' ({result.reason})")

        return result.is_relevant

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

        start_time = time.time()
        try:
            self._ws = await websockets.connect(url)
            self._connected = True
            self._incr("connection.success")
            self._timing("connection.time", (time.time() - start_time) * 1000)
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
            self._incr("connection.failure")
            logger.error(f"Connection failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from the server."""
        self._connected = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        self._incr("connection.disconnect")

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
        self._incr("client.start")

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

        # Set up keyboard mute toggle
        self._mute_manager = KeyboardMuteManager(
            key=self.settings.mute_key,
            callback=self._on_mute_toggle,
        )
        self._mute_manager.start()
        logger.info(f"Press '{self.settings.mute_key}' to toggle mute")

        # Connect to server
        reconnect_attempts = 0
        while self._running:
            if not self._connected:
                if await self.connect():
                    reconnect_attempts = 0
                else:
                    reconnect_attempts += 1
                    self._incr("connection.reconnect_attempt")
                    if reconnect_attempts >= self.settings.max_reconnect_attempts:
                        logger.error("Max reconnection attempts reached")
                        self._incr("connection.max_reconnects_reached")
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
                self._incr("connection.closed")
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                self._connected = False
                self._incr("client.error")

        await self.disconnect()
        self._incr("client.stop")

    async def _listen_loop(self) -> None:
        """Listen for speech and send to server."""
        while self._running and self._connected:
            # Skip listening if muted or speaking
            if self.coordinator.muted or self.coordinator.state == VoiceState.SPEAKING:
                await asyncio.sleep(0.1)
                continue

            self.coordinator.start_listening()
            self._incr("listen.start")

            # Listen for a phrase
            listen_start = time.time()
            audio_data = await self.listener.listen_for_phrase_async(
                on_phrase_start=self.coordinator.phrase_started,
                on_phrase_end=self.coordinator.phrase_ended,
            )
            listen_duration = (time.time() - listen_start) * 1000

            if audio_data is None:
                # Interrupted or timed out
                self._incr("listen.timeout")
                continue

            self._incr("listen.phrase_captured")
            self._timing("listen.duration", listen_duration)
            self._gauge("listen.phrase_bytes", len(audio_data))

            # Transcribe
            self.coordinator.transcription_started()
            self._incr("transcribe.start")
            transcribe_start = time.time()

            try:
                result = await self.transcriber.transcribe(audio_data)
                text = result.text.strip()
                transcribe_duration = (time.time() - transcribe_start) * 1000
                self._timing("transcribe.duration", transcribe_duration)
                self._incr("transcribe.success")
            except Exception as e:
                logger.error(f"Transcription failed: {e}")
                self._incr("transcribe.error")
                self.coordinator.processing_complete()
                continue

            self.coordinator.transcription_complete(text)

            if not text:
                logger.info("Empty transcription, skipping")
                self._incr("transcribe.empty")
                self.coordinator.processing_complete()
                continue

            self._gauge("transcribe.text_length", len(text))

            # Check relevance (wake word or Haiku filter)
            if not await self._check_relevance(text):
                logger.info(f"Skipping irrelevant: '{text[:50]}...'")
                self.coordinator.processing_complete()
                continue

            # Add to context for future relevance checks
            self._add_context("user", text)

            # Send to server
            await self._send_user_input(text)

    async def _receive_loop(self) -> None:
        """Receive messages from server and handle them."""
        while self._running and self._connected and self._ws:
            try:
                data = await self._ws.recv()
                self._incr("message.received")
                await self._handle_message(data)
            except Exception as e:
                # Re-raise connection errors to be handled by main loop
                import websockets.exceptions

                if isinstance(e, websockets.exceptions.ConnectionClosed):
                    raise
                logger.error(f"Error receiving message: {e}")
                self._incr("message.error")

    async def _handle_message(self, data: str) -> None:
        """Handle an incoming message from the server."""
        try:
            msg = json.loads(data)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON: {data[:100]}")
            self._incr("message.invalid_json")
            return

        msg_type = msg.get("type")
        self._incr(f"message.type.{msg_type}")

        if msg_type == "assistant_chunk":
            # Buffer streaming content
            self._response_buffer += msg.get("content", "")
            self._pending_response = True

        elif msg_type == "assistant_complete":
            # Speak the complete response
            text = msg.get("content", "")
            if text:
                # Add to context for relevance filtering
                self._add_context("assistant", text)
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
            self._incr(f"tool.use.{tool_name}")

        elif msg_type == "tool_result":
            # Log tool result
            tool_name = msg.get("tool_name", "")
            is_error = msg.get("is_error", False)
            status = "error" if is_error else "complete"
            logger.info(f"[Tool] {tool_name}: {status}")
            self._incr(f"tool.result.{status}")

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
            self._incr(f"error.{code}")

        elif msg_type == "token_count":
            # Log token usage
            total = msg.get("total_tokens", 0)
            cost = msg.get("total_cost", 0)
            logger.info(f"[Tokens] {total} (${cost:.4f})")
            self._gauge("tokens.total", total)
            self._gauge("tokens.cost", cost)

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
        self._incr("message.sent.user_input")
        logger.info(f"Sent: {text[:50]}...")

    async def _send_interrupt(self, reason: str = "User interrupt") -> None:
        """Send interrupt to the server."""
        if not self._ws:
            return

        msg = InterruptMessage(reason=reason)
        await self._ws.send(msg.model_dump_json())
        self._incr("message.sent.interrupt")
        logger.info("Sent interrupt")

    async def _handle_permission_request(self, msg: dict) -> None:
        """Handle a permission request from the server."""
        # For now, auto-allow (in a real implementation, this would
        # prompt the user via voice or UI)
        request_id = msg.get("request_id")
        action = msg.get("action")
        resource = msg.get("resource")

        logger.info(f"Permission requested: {action} on {resource}")
        self._incr("permission.requested")

        # Auto-allow for voice client
        response = {
            "type": "permission_response",
            "request_id": request_id,
            "allowed": True,
        }
        if self._ws:
            await self._ws.send(json.dumps(response))
            self._incr("permission.granted")

    async def _speak_response(self, text: str) -> None:
        """Synthesize and speak a response."""
        if self.coordinator.muted:
            return

        self.coordinator.speech_started(text)
        self._incr("speak.start")
        speak_start = time.time()

        try:
            # Check for interrupt before synthesis
            if self.coordinator.is_interrupted():
                self.coordinator.clear_interrupt()
                self.coordinator.speech_complete()
                self._incr("speak.interrupted_before_synth")
                return

            # Synthesize speech
            synth_start = time.time()
            result = await self.speaker.synthesize(text)
            self._timing("speak.synth_duration", (time.time() - synth_start) * 1000)

            # Check for interrupt before playback
            if self.coordinator.is_interrupted():
                self.coordinator.clear_interrupt()
                self.coordinator.speech_complete()
                self._incr("speak.interrupted_before_play")
                return

            # Play audio
            play_start = time.time()
            await self.player.play(result, block=True)
            self._timing("speak.play_duration", (time.time() - play_start) * 1000)
            self._incr("speak.success")

        except Exception as e:
            logger.error(f"Speech error: {e}")
            self._incr("speak.error")
        finally:
            total_duration = (time.time() - speak_start) * 1000
            self._timing("speak.total_duration", total_duration)
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
    metrics_enabled: bool = True,
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
        metrics_enabled: Whether to enable metrics collection
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
        metrics_enabled=metrics_enabled,
        **settings_kwargs,
    )

    client = VoiceClient(
        transcriber=transcriber,
        speaker=speaker,
        settings=settings,
    )

    await client.run()
