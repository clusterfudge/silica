"""
Voice Client for Silica.

This module provides a WebSocket client that bridges voice I/O
(listener, transcriber, speaker) with the silica serve WebSocket protocol.

Features streaming TTS that synthesizes and plays sentences as they arrive,
pipelining synthesis of sentence N+1 while sentence N plays.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional, Tuple, TYPE_CHECKING

from silica.serve.protocol import (
    PROTOCOL_VERSION,
    InterruptMessage,
    UserInputMessage,
)
from silica.voice.coordinator import VoiceCoordinator, VoiceState, KeyboardMuteManager
from silica.voice.listener import Listener
from silica.voice.relevance import RelevanceFilter, VoiceCommand, detect_voice_command
from silica.voice.speaker import AudioPlayer, Speaker, TTSResult
from silica.voice.transcriber import Transcriber

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Sentence boundary pattern - matches end of sentence punctuation
# Uses the same pattern as speaker.py for consistency
SENTENCE_END_PATTERN = re.compile(r"[.!?]+(?:\s|$)")


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
    streaming_tts: bool = True  # Enable streaming TTS (sentence-by-sentence)

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
    - Text-to-speech synthesis and playback (with streaming support)
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

        # Message handling (legacy non-streaming)
        self._response_buffer = ""
        self._pending_response = False

        # Streaming TTS infrastructure
        # Queue 1: Text chunks from WebSocket -> Synthesis task
        self._chunk_queue: asyncio.Queue[str | None] = asyncio.Queue()
        # Queue 2: Synthesized audio -> Playback task
        self._audio_queue: asyncio.Queue[TTSResult | None] = asyncio.Queue()
        # Background tasks for pipelined synthesis/playback
        self._synthesis_task: Optional[asyncio.Task] = None
        self._playback_task: Optional[asyncio.Task] = None
        self._streaming_in_progress: bool = False

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
        is_muted = self.coordinator.toggle_mute()
        status = "MUTED" if is_muted else "LISTENING"
        logger.info(f"Mute toggled: {status}")
        print(f"\n[{status}]")

    async def _handle_voice_command(self, command: VoiceCommand, text: str) -> None:
        """Handle a detected voice command."""
        logger.info(f"Handling voice command: {command.name}")

        if command == VoiceCommand.MUTE:
            if not self.coordinator.muted:
                self.coordinator.mute()
                print("\n[MUTED by voice command]")
                # Speak confirmation before going to sleep
                await self._speak_response("Going to sleep.")

        elif command == VoiceCommand.UNMUTE:
            if self.coordinator.muted:
                self.coordinator.unmute()
                print("\n[LISTENING - woken by voice command]")
                await self._speak_response("I'm listening.")

        elif command == VoiceCommand.STOP:
            # Interrupt current speech
            await self._interrupt_streaming()
            await self._send_interrupt("Voice command: stop")
            print("\n[STOPPED]")

        elif command == VoiceCommand.CANCEL:
            # Interrupt and send cancel to server
            await self._interrupt_streaming()
            await self._send_interrupt("Voice command: cancel")
            print("\n[CANCELLED]")

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

    async def _check_relevance(self, text: str) -> Tuple[bool, VoiceCommand]:
        """
        Check if transcribed text is relevant to the assistant.

        Returns:
            Tuple of (is_relevant, voice_command)
        """
        # First check for voice commands (always processed, even bypassing wake words)
        command = detect_voice_command(text)
        if command != VoiceCommand.NONE:
            self._incr(f"command.{command.name.lower()}")
            return True, command

        # Check wake words if configured
        if self.settings.wake_words:
            if self._check_wake_word(text):
                self._incr("relevance.wake_word_match")
                return True, VoiceCommand.NONE
            else:
                self._incr("relevance.no_wake_word")
                return False, VoiceCommand.NONE

        # If relevance filtering is disabled, everything is relevant
        if not self.relevance_filter or not self.settings.relevance_filtering:
            return True, VoiceCommand.NONE

        # Use relevance filter (commands already checked above)
        self._incr("relevance.check")
        context = self._get_context_string()
        result = await self.relevance_filter.check_relevance_async(
            text, context, detect_commands=False
        )

        if result.is_relevant:
            self._incr("relevance.relevant")
        else:
            self._incr("relevance.not_relevant")
            logger.info(f"Filtered out: '{text[:50]}...' ({result.reason})")

        return result.is_relevant, VoiceCommand.NONE

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
        await self._interrupt_streaming()
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
            # Skip listening only if speaking (still listen when muted for unmute commands)
            if self.coordinator.state == VoiceState.SPEAKING:
                await asyncio.sleep(0.1)
                continue

            # When muted, still listen but only for unmute commands
            is_muted = self.coordinator.muted

            if not is_muted:
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

            # Check relevance and voice commands
            is_relevant, command = await self._check_relevance(text)

            # Handle voice commands (always processed, even when muted)
            if command != VoiceCommand.NONE:
                await self._handle_voice_command(command, text)
                self.coordinator.processing_complete()
                continue

            # When muted, only voice commands are processed
            if is_muted:
                logger.debug(f"Muted, ignoring non-command: '{text[:50]}...'")
                self.coordinator.processing_complete()
                continue

            if not is_relevant:
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
            content = msg.get("content", "")
            if not content:
                return

            # Use streaming TTS if enabled
            if self.settings.streaming_tts:
                await self._handle_streaming_chunk(content)
            else:
                # Legacy: just buffer
                self._response_buffer += content
                self._pending_response = True

        elif msg_type == "assistant_complete":
            text = msg.get("content", "")

            if self.settings.streaming_tts:
                # Signal end of stream and wait for completion
                await self._finish_streaming(text)
            else:
                # Legacy: speak the complete response
                if text:
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

    # -------------------------------------------------------------------------
    # Streaming TTS Implementation
    # -------------------------------------------------------------------------

    async def _handle_streaming_chunk(self, content: str) -> None:
        """
        Handle an incoming text chunk for streaming TTS.

        On first chunk: starts synthesis and playback tasks.
        Subsequent chunks: queued for the synthesis task.
        """
        if not self._streaming_in_progress:
            # First chunk - start the streaming pipeline
            await self._start_streaming()

        # Queue the chunk for synthesis
        await self._chunk_queue.put(content)
        self._incr("streaming.chunk_queued")

    async def _start_streaming(self) -> None:
        """Start the streaming TTS pipeline (synthesis + playback tasks)."""
        if self._streaming_in_progress:
            return

        self._streaming_in_progress = True
        self._incr("streaming.start")

        # Clear any leftover items in queues
        while not self._chunk_queue.empty():
            try:
                self._chunk_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        # Start coordinator in speaking state
        self.coordinator.speech_started("")

        # Start both tasks concurrently
        # Synthesis task: chunks -> sentences -> audio
        self._synthesis_task = asyncio.create_task(
            self._synthesis_loop(), name="synthesis_loop"
        )
        # Playback task: audio -> speakers
        self._playback_task = asyncio.create_task(
            self._playback_loop(), name="playback_loop"
        )

        logger.debug("Streaming TTS pipeline started")

    async def _finish_streaming(self, full_text: str) -> None:
        """
        Finish the streaming TTS pipeline.

        Sends sentinel to signal end, waits for tasks to complete.
        """
        if not self._streaming_in_progress:
            # No streaming was started (empty response?)
            return

        # Add full text to context for relevance filtering
        if full_text:
            self._add_context("assistant", full_text)

        # Signal end of chunks
        await self._chunk_queue.put(None)
        self._incr("streaming.finish_signaled")

        # Wait for both tasks to complete
        if self._synthesis_task:
            try:
                await self._synthesis_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Synthesis task error: {e}")
            self._synthesis_task = None

        if self._playback_task:
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Playback task error: {e}")
            self._playback_task = None

        self._streaming_in_progress = False
        self.coordinator.speech_complete()
        self._incr("streaming.complete")
        logger.debug("Streaming TTS pipeline finished")

    async def _interrupt_streaming(self) -> None:
        """
        Interrupt the streaming TTS pipeline.

        Cancels both tasks and clears queues.
        """
        if not self._streaming_in_progress:
            self.coordinator.interrupt()
            return

        self._incr("streaming.interrupted")
        logger.debug("Interrupting streaming TTS")

        # Cancel synthesis task
        if self._synthesis_task and not self._synthesis_task.done():
            self._synthesis_task.cancel()
            try:
                await self._synthesis_task
            except asyncio.CancelledError:
                pass
            self._synthesis_task = None

        # Cancel playback task
        if self._playback_task and not self._playback_task.done():
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass
            self._playback_task = None

        # Stop audio playback
        self.player.stop()

        # Clear queues
        while not self._chunk_queue.empty():
            try:
                self._chunk_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

        self._streaming_in_progress = False
        self.coordinator.interrupt()
        self.coordinator.speech_complete()

    async def _synthesis_loop(self) -> None:
        """
        Synthesis task: consume chunks, detect sentences, synthesize audio.

        Runs concurrently with _playback_loop. Synthesizes sentences as soon
        as they're detected, allowing playback of sentence N while synthesizing
        sentence N+1.
        """
        buffer = ""
        sentence_count = 0

        try:
            while True:
                # Check for interrupt
                if self.coordinator.is_interrupted():
                    logger.debug("Synthesis loop interrupted")
                    break

                # Get next chunk (with timeout to check for interrupts)
                try:
                    chunk = await asyncio.wait_for(self._chunk_queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                # None signals end of stream
                if chunk is None:
                    logger.debug("Synthesis received end signal")
                    break

                buffer += chunk

                # Try to extract complete sentences
                # We use a heuristic: wait for 2+ potential sentences to ensure
                # the first one is truly complete (like HEARE does)
                while True:
                    match = SENTENCE_END_PATTERN.search(buffer)
                    if not match:
                        break

                    # Check if there's more content after this sentence
                    # (indicates we have a complete sentence)
                    end_pos = match.end()
                    remaining = buffer[end_pos:].strip()

                    # Heuristic: only emit if we have more content OR buffer is long
                    # This prevents cutting off mid-sentence on abbreviations like "Mr."
                    if remaining or len(buffer) > 200:
                        sentence = buffer[:end_pos].strip()
                        buffer = buffer[end_pos:].lstrip()

                        if sentence:
                            await self._synthesize_sentence(sentence, sentence_count)
                            sentence_count += 1
                    else:
                        # Wait for more content
                        break

            # Flush remaining buffer
            buffer = buffer.strip()
            if buffer:
                await self._synthesize_sentence(buffer, sentence_count)
                sentence_count += 1

        except asyncio.CancelledError:
            logger.debug("Synthesis loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Synthesis loop error: {e}")
        finally:
            # Signal playback loop that synthesis is done
            await self._audio_queue.put(None)
            self._gauge("streaming.sentences_synthesized", sentence_count)

    async def _synthesize_sentence(self, text: str, index: int) -> None:
        """Synthesize a single sentence and queue the audio."""
        if self.coordinator.is_interrupted():
            return

        self._incr("streaming.sentence_synth_start")
        synth_start = time.time()

        try:
            result = await self.speaker.synthesize(text)
            synth_duration = (time.time() - synth_start) * 1000
            self._timing("streaming.sentence_synth_duration", synth_duration)
            self._incr("streaming.sentence_synth_success")

            # Queue for playback
            await self._audio_queue.put(result)
            logger.debug(
                f"Sentence {index} synthesized ({len(text)} chars, {synth_duration:.0f}ms)"
            )

        except Exception as e:
            logger.error(f"Synthesis error for sentence {index}: {e}")
            self._incr("streaming.sentence_synth_error")

    async def _playback_loop(self) -> None:
        """
        Playback task: consume audio from queue and play sequentially.

        Runs concurrently with _synthesis_loop. Blocks on each audio segment
        (within this task), but doesn't block the synthesis task.
        """
        segment_count = 0

        try:
            while True:
                # Check for interrupt
                if self.coordinator.is_interrupted():
                    logger.debug("Playback loop interrupted")
                    break

                # Get next audio segment
                try:
                    result = await asyncio.wait_for(
                        self._audio_queue.get(), timeout=0.1
                    )
                except asyncio.TimeoutError:
                    continue

                # None signals end of stream
                if result is None:
                    logger.debug("Playback received end signal")
                    break

                # Play the audio (blocks until complete)
                self._incr("streaming.segment_play_start")
                play_start = time.time()

                try:
                    await self.player.play(result, block=True)
                    play_duration = (time.time() - play_start) * 1000
                    self._timing("streaming.segment_play_duration", play_duration)
                    self._incr("streaming.segment_play_success")
                    segment_count += 1
                    logger.debug(
                        f"Segment {segment_count} played ({play_duration:.0f}ms)"
                    )

                except Exception as e:
                    logger.error(f"Playback error for segment {segment_count}: {e}")
                    self._incr("streaming.segment_play_error")

        except asyncio.CancelledError:
            logger.debug("Playback loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Playback loop error: {e}")
        finally:
            self._gauge("streaming.segments_played", segment_count)

    # -------------------------------------------------------------------------
    # Legacy non-streaming TTS (fallback)
    # -------------------------------------------------------------------------

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
        """
        Synthesize and speak a response (non-streaming fallback).

        Used when streaming_tts is disabled or for voice command confirmations.
        """
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
        # Schedule interrupt on the event loop if running
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._interrupt_streaming())
        except RuntimeError:
            # No running loop, just set flags
            self.coordinator.interrupt()


async def run_voice_client(
    server_url: str = "ws://localhost:8765/ws",
    transcriber_backend: str = "remote_whisper",
    transcriber_kwargs: Optional[dict] = None,
    speaker_backend: str = "edge",
    speaker_kwargs: Optional[dict] = None,
    metrics_enabled: bool = True,
    streaming_tts: bool = True,
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
        streaming_tts: Whether to enable streaming TTS (default: True)
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
        streaming_tts=streaming_tts,
        **settings_kwargs,
    )

    client = VoiceClient(
        transcriber=transcriber,
        speaker=speaker,
        settings=settings,
    )

    await client.run()
