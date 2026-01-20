"""
Voice Listener for Silica.

This module provides audio capture with Voice Activity Detection (VAD)
for extracting speech phrases from a microphone or audio source.

Adapted from heare-llm-prototype's listen.py and phrase_extractor.py.
"""

import asyncio
import logging
from collections import deque
from enum import Enum, auto
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Audio constants
SAMPLE_RATE = 16000  # WebRTC VAD requires 16kHz
FRAME_DURATION_MS = 30  # Frame duration in milliseconds
BYTES_PER_SAMPLE = 2  # 16-bit audio

# Default phrase extraction parameters
DEFAULT_MIN_PHRASE_MS = 300
DEFAULT_PHRASE_PADDING_MS = 500
DEFAULT_PHRASE_END_MS = 800


class PhraseState(Enum):
    """State of phrase detection."""

    NONE = auto()  # No speech detected
    START = auto()  # Speech started
    CONTINUE = auto()  # Speech continuing
    END = auto()  # Speech ended (phrase complete)


class PhraseExtractor:
    """
    Extracts speech phrases from an audio stream using Voice Activity Detection.

    Uses WebRTC VAD to detect speech boundaries and extract complete phrases
    with appropriate padding.
    """

    def __init__(
        self,
        aggressiveness: int = 3,
        frame_duration_ms: int = FRAME_DURATION_MS,
        sample_rate: int = SAMPLE_RATE,
        min_phrase_ms: int = DEFAULT_MIN_PHRASE_MS,
        phrase_padding_ms: int = DEFAULT_PHRASE_PADDING_MS,
        phrase_end_ms: int = DEFAULT_PHRASE_END_MS,
    ):
        """
        Initialize the phrase extractor.

        Args:
            aggressiveness: VAD aggressiveness (0-3, higher = more aggressive)
            frame_duration_ms: Frame duration in milliseconds (10, 20, or 30)
            sample_rate: Sample rate in Hz (must be 8000, 16000, 32000, or 48000)
            min_phrase_ms: Minimum phrase duration in milliseconds
            phrase_padding_ms: Padding before/after phrase in milliseconds
            phrase_end_ms: Duration of silence to end phrase in milliseconds
        """
        from silica.voice import check_voice_available

        check_voice_available()

        import webrtcvad

        self.vad = webrtcvad.Vad(aggressiveness)
        self.frame_duration_ms = frame_duration_ms
        self.sample_rate = sample_rate

        # Timing parameters
        self.min_phrase_ms = min_phrase_ms
        self.phrase_padding_ms = phrase_padding_ms
        self.phrase_end_ms = phrase_end_ms

        # Convert ms to frame counts
        self.min_phrase_frames = min_phrase_ms // frame_duration_ms
        self.padding_frames_count = phrase_padding_ms // frame_duration_ms
        self.end_phrase_frames_count = phrase_end_ms // frame_duration_ms

        # Calculate frame size in bytes
        self.frame_size = (
            int(sample_rate * (frame_duration_ms / 1000.0)) * BYTES_PER_SAMPLE
        )

        # Buffers
        self.speech_buffer = deque(maxlen=self.end_phrase_frames_count)
        self.is_phrase = False
        self.phrase_frames: List[bytes] = []
        self.padding_frames: deque = deque(maxlen=self.padding_frames_count)
        self.end_padding: deque = deque(maxlen=self.padding_frames_count)
        self.leftover_audio = b""

        logger.info(
            f"PhraseExtractor initialized: aggressiveness={aggressiveness}, "
            f"min_phrase_ms={min_phrase_ms}, phrase_padding_ms={phrase_padding_ms}, "
            f"phrase_end_ms={phrase_end_ms}"
        )

    def process_audio(
        self, audio_data: bytes
    ) -> List[Tuple[PhraseState, Optional[bytes]]]:
        """
        Process audio data and return phrase detection results.

        Args:
            audio_data: Raw 16-bit PCM audio data at the configured sample rate

        Returns:
            List of (state, phrase_audio) tuples. phrase_audio is only set
            when state is PhraseState.END.
        """
        # Combine leftover audio with new data
        audio_data = self.leftover_audio + audio_data

        # Split into frames
        frames = [
            audio_data[i : i + self.frame_size]
            for i in range(0, len(audio_data), self.frame_size)
        ]

        # Store leftover audio for next call
        remainder = len(audio_data) % self.frame_size
        if remainder != 0:
            self.leftover_audio = audio_data[-remainder:]
            frames = frames[:-1]  # Remove incomplete frame
        else:
            self.leftover_audio = b""

        # Process each frame
        results = []
        for frame in frames:
            if len(frame) == self.frame_size:
                result = self._update(frame)
                results.append(result)

        return results

    def _is_speech(self, audio_frame: bytes) -> bool:
        """Check if an audio frame contains speech."""
        try:
            return self.vad.is_speech(audio_frame, self.sample_rate)
        except Exception as e:
            logger.error(f"VAD error: {e}")
            return False

    def _update(self, audio_frame: bytes) -> Tuple[PhraseState, Optional[bytes]]:
        """Update phrase state with a new audio frame."""
        is_speech = self._is_speech(audio_frame)
        self.speech_buffer.append(is_speech)

        if not self.is_phrase:
            # Not currently in a phrase - accumulate padding
            self.padding_frames.append(audio_frame)

            if is_speech and len(self.padding_frames) == self.padding_frames_count:
                # Start of phrase
                self.is_phrase = True
                self.phrase_frames.extend(self.padding_frames)
                self.padding_frames.clear()
                return PhraseState.START, None
        else:
            # Currently in a phrase - accumulate audio
            self.phrase_frames.append(audio_frame)

            if not is_speech:
                # Potential end of phrase
                self.end_padding.append(audio_frame)

                if len(self.end_padding) == self.padding_frames_count:
                    # Check if we've had enough silence
                    if all(not speech for speech in self.speech_buffer):
                        # Check minimum phrase length
                        if len(self.phrase_frames) >= self.min_phrase_frames:
                            # End of phrase
                            self.phrase_frames.extend(self.end_padding)
                            phrase_audio = b"".join(self.phrase_frames)
                            self.reset()
                            return PhraseState.END, phrase_audio
                    else:
                        self.end_padding.clear()
            else:
                self.end_padding.clear()

        return (PhraseState.CONTINUE if self.is_phrase else PhraseState.NONE), None

    def flush(self) -> bytes:
        """Flush any buffered audio and reset state."""
        phrase_audio = b"".join(self.phrase_frames)
        self.reset()
        return phrase_audio

    def reset(self) -> None:
        """Reset the extractor state."""
        self.is_phrase = False
        self.phrase_frames = []
        self.padding_frames.clear()
        self.end_padding.clear()
        self.leftover_audio = b""


class Listener:
    """
    Audio listener that captures speech phrases from a microphone.

    Provides both synchronous and asynchronous interfaces for capturing
    audio and extracting speech phrases.
    """

    def __init__(
        self,
        device_index: Optional[int] = None,
        device_name: Optional[str] = None,
        aggressiveness: int = 3,
        min_phrase_ms: int = DEFAULT_MIN_PHRASE_MS,
        phrase_padding_ms: int = DEFAULT_PHRASE_PADDING_MS,
        phrase_end_ms: int = DEFAULT_PHRASE_END_MS,
        phrase_time_limit: float = 30.0,
    ):
        """
        Initialize the listener.

        Args:
            device_index: Index of the audio input device (None for default)
            device_name: Name of the audio input device (overrides device_index)
            aggressiveness: VAD aggressiveness (0-3)
            min_phrase_ms: Minimum phrase duration in milliseconds
            phrase_padding_ms: Padding before/after phrase in milliseconds
            phrase_end_ms: Duration of silence to end phrase in milliseconds
            phrase_time_limit: Maximum phrase duration in seconds
        """
        from silica.voice import check_voice_available

        check_voice_available()

        self.device_index = device_index
        self.device_name = device_name
        self.aggressiveness = aggressiveness
        self.min_phrase_ms = min_phrase_ms
        self.phrase_padding_ms = phrase_padding_ms
        self.phrase_end_ms = phrase_end_ms
        self.phrase_time_limit = phrase_time_limit

        self._microphone = None
        self._recognizer = None
        self._interrupted = False

        # Resolve device by name if provided
        if device_name:
            self.device_index = self._find_device_by_name(device_name)

    def _find_device_by_name(self, name: str) -> Optional[int]:
        """Find a device index by name."""
        for idx, info in list_microphones():
            if info.get("name") == name:
                return idx
        return None

    def _setup_microphone(self):
        """Set up the microphone and recognizer."""
        import speech_recognition as sr

        self._microphone = sr.Microphone(device_index=self.device_index)
        self._recognizer = sr.Recognizer()

        # Calibrate for ambient noise
        with self._microphone as source:
            logger.info("Calibrating for ambient noise...")
            self._recognizer.adjust_for_ambient_noise(source, duration=1)
            logger.info("Calibration complete")

    def interrupt(self) -> None:
        """Interrupt the current listening operation."""
        self._interrupted = True

    def clear_interrupt(self) -> None:
        """Clear the interrupt flag."""
        self._interrupted = False

    def listen_for_phrase(
        self,
        on_phrase_start: Optional[Callable[[], None]] = None,
        on_phrase_end: Optional[Callable[[], None]] = None,
    ) -> Optional[bytes]:
        """
        Listen for a single speech phrase.

        Args:
            on_phrase_start: Callback when phrase starts
            on_phrase_end: Callback when phrase ends

        Returns:
            Raw audio bytes of the phrase, or None if interrupted/timeout
        """
        if self._microphone is None:
            self._setup_microphone()

        phrase_extractor = PhraseExtractor(
            aggressiveness=self.aggressiveness,
            min_phrase_ms=self.min_phrase_ms,
            phrase_padding_ms=self.phrase_padding_ms,
            phrase_end_ms=self.phrase_end_ms,
        )

        phrase_in_progress = False

        try:
            with self._microphone as source:
                logger.info("Listening for speech...")

                # Use streaming mode for low-latency VAD
                for audio_chunk in self._recognizer.listen(
                    source,
                    phrase_time_limit=self.phrase_time_limit,
                    stream=True,
                ):
                    if self._interrupted:
                        logger.info("Listening interrupted")
                        self._interrupted = False
                        return None

                    # Process the audio chunk
                    raw_data = audio_chunk.get_raw_data(
                        convert_rate=SAMPLE_RATE,
                        convert_width=BYTES_PER_SAMPLE,
                    )

                    results = phrase_extractor.process_audio(raw_data)

                    for state, phrase_audio in results:
                        if state == PhraseState.START:
                            if not phrase_in_progress:
                                phrase_in_progress = True
                                logger.info("Phrase started")
                                if on_phrase_start:
                                    on_phrase_start()

                        elif state == PhraseState.END:
                            if phrase_in_progress:
                                logger.info("Phrase ended")
                                if on_phrase_end:
                                    on_phrase_end()
                                return phrase_audio

                # Stream ended - flush any remaining audio
                if phrase_in_progress:
                    phrase_audio = phrase_extractor.flush()
                    if on_phrase_end:
                        on_phrase_end()
                    return phrase_audio

        except Exception as e:
            logger.error(f"Error listening for phrase: {e}")

        return None

    async def listen_for_phrase_async(
        self,
        on_phrase_start: Optional[Callable[[], None]] = None,
        on_phrase_end: Optional[Callable[[], None]] = None,
    ) -> Optional[bytes]:
        """
        Async version of listen_for_phrase.

        Runs the blocking listen operation in a thread pool.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.listen_for_phrase(on_phrase_start, on_phrase_end),
        )


def list_microphones() -> List[Tuple[int, dict]]:
    """
    List available microphone devices.

    Returns:
        List of (device_index, device_info) tuples for input devices
    """
    from silica.voice import check_voice_available

    check_voice_available()

    import speech_recognition as sr

    audio = sr.Microphone.get_pyaudio().PyAudio()
    try:
        result = []
        for i in range(audio.get_device_count()):
            device_info = audio.get_device_info_by_index(i)
            if device_info.get("maxInputChannels", 0) >= 1:
                result.append((i, device_info))
        return result
    finally:
        audio.terminate()


def find_microphone(names: List[str]) -> Optional[int]:
    """
    Find a microphone by name.

    Args:
        names: List of device names to search for (in order of preference)

    Returns:
        Device index if found, None otherwise
    """
    devices = {info["name"]: idx for idx, info in list_microphones()}

    for name in names:
        if name in devices:
            return devices[name]

    return None


# Add metrics to listen_for_phrase method
