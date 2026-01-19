"""
Voice Coordinator for Silica.

This module manages the voice interaction lifecycle, including:
- Mute state management
- Audio lifecycle (listening, speaking)
- Interruption handling (barge-in)
- Status tracking and callbacks
"""

import asyncio
import logging
import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)


class VoiceState(Enum):
    """Current state of the voice interface."""

    IDLE = auto()  # Waiting, not listening or speaking
    LISTENING = auto()  # Actively listening for speech
    PROCESSING = auto()  # Processing transcription or agent response
    SPEAKING = auto()  # Playing TTS output
    MUTED = auto()  # Muted, not listening


@dataclass
class CoordinatorCallbacks:
    """Callbacks for coordinator events."""

    on_state_change: Optional[Callable[[VoiceState], None]] = None
    on_mute_change: Optional[Callable[[bool], None]] = None
    on_phrase_start: Optional[Callable[[], None]] = None
    on_phrase_end: Optional[Callable[[], None]] = None
    on_transcription_start: Optional[Callable[[], None]] = None
    on_transcription_complete: Optional[Callable[[str], None]] = None
    on_speech_start: Optional[Callable[[str], None]] = None
    on_speech_complete: Optional[Callable[[], None]] = None
    on_interrupt: Optional[Callable[[], None]] = None


@dataclass
class CoordinatorStatus:
    """Current status of the coordinator."""

    state: VoiceState = VoiceState.IDLE
    muted: bool = False
    current_text: str = ""
    last_transcription: str = ""


class VoiceCoordinator:
    """
    Coordinates voice interaction lifecycle.

    Manages state transitions between listening, processing, and speaking,
    handles mute state, and provides callbacks for status changes.
    """

    def __init__(
        self,
        callbacks: Optional[CoordinatorCallbacks] = None,
    ):
        """
        Initialize the voice coordinator.

        Args:
            callbacks: Optional callbacks for state changes
        """
        self._callbacks = callbacks or CoordinatorCallbacks()
        self._state = VoiceState.IDLE
        self._muted = False
        self._lock = threading.Lock()
        self._interrupt_event = asyncio.Event()
        self._speech_queue: List[str] = []
        self._current_text = ""
        self._last_transcription = ""

        # References to external components (set by client)
        self._listener = None
        self._speaker = None
        self._player = None

    @property
    def state(self) -> VoiceState:
        """Current voice state."""
        return self._state

    @property
    def muted(self) -> bool:
        """Whether the microphone is muted."""
        return self._muted

    @property
    def status(self) -> CoordinatorStatus:
        """Get current coordinator status."""
        return CoordinatorStatus(
            state=self._state,
            muted=self._muted,
            current_text=self._current_text,
            last_transcription=self._last_transcription,
        )

    def _set_state(self, new_state: VoiceState) -> None:
        """Set state and trigger callback."""
        if new_state != self._state:
            old_state = self._state
            self._state = new_state
            logger.info(f"Voice state: {old_state.name} -> {new_state.name}")
            if self._callbacks.on_state_change:
                self._callbacks.on_state_change(new_state)

    def toggle_mute(self) -> bool:
        """
        Toggle mute state.

        Returns:
            New mute state
        """
        self._muted = not self._muted
        logger.info(f"Mute toggled: {self._muted}")

        if self._muted:
            self._set_state(VoiceState.MUTED)
            # Interrupt any current listening
            if self._listener:
                self._listener.interrupt()
        else:
            self._set_state(VoiceState.IDLE)
            # Clear interrupt to resume listening
            if self._listener:
                self._listener.clear_interrupt()

        if self._callbacks.on_mute_change:
            self._callbacks.on_mute_change(self._muted)

        return self._muted

    def mute(self) -> None:
        """Mute the microphone."""
        if not self._muted:
            self.toggle_mute()

    def unmute(self) -> None:
        """Unmute the microphone."""
        if self._muted:
            self.toggle_mute()

    def interrupt(self) -> None:
        """
        Interrupt current operation (barge-in).

        Stops speaking and clears pending speech queue.
        """
        logger.info("Interrupt requested")
        self._interrupt_event.set()

        # Stop any current playback
        if self._player:
            self._player.stop()

        # Clear speech queue
        with self._lock:
            self._speech_queue.clear()

        # Reset to listening if not muted
        if not self._muted:
            self._set_state(VoiceState.IDLE)

        if self._callbacks.on_interrupt:
            self._callbacks.on_interrupt()

    def clear_interrupt(self) -> None:
        """Clear the interrupt flag."""
        self._interrupt_event.clear()

    def is_interrupted(self) -> bool:
        """Check if an interrupt has been requested."""
        return self._interrupt_event.is_set()

    # =========================================================================
    # State Transition Methods
    # =========================================================================

    def start_listening(self) -> None:
        """Signal that listening has started."""
        if not self._muted:
            self._set_state(VoiceState.LISTENING)

    def phrase_started(self) -> None:
        """Signal that a phrase has started."""
        logger.info("Phrase capture started")
        if self._callbacks.on_phrase_start:
            self._callbacks.on_phrase_start()

    def phrase_ended(self) -> None:
        """Signal that a phrase has ended."""
        logger.info("Phrase capture ended")
        self._set_state(VoiceState.PROCESSING)
        if self._callbacks.on_phrase_end:
            self._callbacks.on_phrase_end()

    def transcription_started(self) -> None:
        """Signal that transcription has started."""
        logger.info("Transcription started")
        if self._callbacks.on_transcription_start:
            self._callbacks.on_transcription_start()

    def transcription_complete(self, text: str) -> None:
        """Signal that transcription is complete."""
        logger.info(f"Transcription complete: {text[:50]}...")
        self._last_transcription = text
        if self._callbacks.on_transcription_complete:
            self._callbacks.on_transcription_complete(text)

    def speech_started(self, text: str) -> None:
        """Signal that speech synthesis/playback has started."""
        logger.info(f"Speech started: {text[:50]}...")
        self._set_state(VoiceState.SPEAKING)
        self._current_text = text
        if self._callbacks.on_speech_start:
            self._callbacks.on_speech_start(text)

    def speech_complete(self) -> None:
        """Signal that speech playback is complete."""
        logger.info("Speech complete")
        self._current_text = ""
        self._set_state(VoiceState.IDLE)
        if self._callbacks.on_speech_complete:
            self._callbacks.on_speech_complete()

    def processing_complete(self) -> None:
        """Signal that processing is complete (back to idle or speaking)."""
        if self._state == VoiceState.PROCESSING:
            self._set_state(VoiceState.IDLE)

    # =========================================================================
    # Speech Queue Management
    # =========================================================================

    def queue_speech(self, text: str) -> None:
        """Add text to the speech queue."""
        with self._lock:
            self._speech_queue.append(text)

    def get_queued_speech(self) -> List[str]:
        """Get and clear queued speech."""
        with self._lock:
            speech = list(self._speech_queue)
            self._speech_queue.clear()
            return speech

    def has_queued_speech(self) -> bool:
        """Check if there is queued speech."""
        with self._lock:
            return len(self._speech_queue) > 0


class GPIOManager:
    """
    Simple GPIO manager for hardware mute button.

    Provides a basic interface for reading a GPIO button state
    on Raspberry Pi or similar devices.
    """

    def __init__(
        self,
        button_pin: int = 17,
        led_pin: Optional[int] = None,
        callback: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize GPIO manager.

        Args:
            button_pin: GPIO pin number for the mute button
            led_pin: Optional GPIO pin for status LED
            callback: Callback to trigger on button press
        """
        self.button_pin = button_pin
        self.led_pin = led_pin
        self.callback = callback
        self._gpio_available = False
        self._running = False

        try:
            import RPi.GPIO as GPIO

            self._GPIO = GPIO
            self._gpio_available = True
        except ImportError:
            logger.warning("RPi.GPIO not available, GPIO features disabled")

    def setup(self) -> bool:
        """
        Set up GPIO pins.

        Returns:
            True if setup successful, False otherwise
        """
        if not self._gpio_available:
            return False

        try:
            GPIO = self._GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.button_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

            if self.led_pin:
                GPIO.setup(self.led_pin, GPIO.OUT)
                GPIO.output(self.led_pin, GPIO.LOW)

            # Set up interrupt
            GPIO.add_event_detect(
                self.button_pin,
                GPIO.FALLING,
                callback=self._button_callback,
                bouncetime=300,
            )

            self._running = True
            return True

        except Exception as e:
            logger.error(f"GPIO setup failed: {e}")
            return False

    def _button_callback(self, channel: int) -> None:
        """Handle button press."""
        if self.callback:
            self.callback()

    def set_led(self, on: bool) -> None:
        """Set LED state."""
        if self._gpio_available and self.led_pin:
            self._GPIO.output(self.led_pin, self._GPIO.HIGH if on else self._GPIO.LOW)

    def cleanup(self) -> None:
        """Clean up GPIO resources."""
        if self._gpio_available and self._running:
            self._GPIO.cleanup()
            self._running = False


class KeyboardMuteManager:
    """
    Keyboard-based mute toggle for development/testing.

    Listens for a specific key (default: 'm') to toggle mute.
    """

    def __init__(
        self,
        key: str = "m",
        callback: Optional[Callable[[], None]] = None,
    ):
        """
        Initialize keyboard mute manager.

        Args:
            key: Key to trigger mute toggle
            callback: Callback to trigger on key press
        """
        self.key = key
        self.callback = callback
        self._running = False
        self._thread = None

    def start(self) -> None:
        """Start listening for keyboard input."""
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def _listen_loop(self) -> None:
        """Listen for keyboard input."""
        try:
            import sys
            import termios
            import tty

            old_settings = termios.tcgetattr(sys.stdin)
            try:
                tty.setcbreak(sys.stdin.fileno())
                while self._running:
                    import select

                    if select.select([sys.stdin], [], [], 0.1)[0]:
                        char = sys.stdin.read(1)
                        if char.lower() == self.key.lower():
                            if self.callback:
                                self.callback()
            finally:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
        except Exception as e:
            logger.debug(f"Keyboard mute not available: {e}")

    def stop(self) -> None:
        """Stop listening for keyboard input."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
