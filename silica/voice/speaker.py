"""
Voice Speaker for Silica.

This module provides text-to-speech synthesis with pluggable backends.
Supports Edge TTS, remote TTS servers, and audio playback.
"""

import asyncio
import io
import logging
import re
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncGenerator, List, Optional

logger = logging.getLogger(__name__)

# Sentence boundary pattern for streaming
SENTENCE_END_PATTERN = re.compile(r"[.!?]+(?:\s|$)")


@dataclass
class TTSResult:
    """Result of a TTS operation."""

    audio_data: bytes
    format: str = "mp3"  # "mp3", "wav", "raw"
    sample_rate: int = 24000


class Speaker(ABC):
    """
    Abstract base class for text-to-speech speakers.

    Subclasses must implement the synthesize method.
    """

    @abstractmethod
    async def synthesize(self, text: str) -> TTSResult:
        """
        Synthesize speech from text.

        Args:
            text: Text to synthesize

        Returns:
            TTSResult with audio data
        """

    async def synthesize_streaming(
        self, text_stream: AsyncGenerator[str, None]
    ) -> AsyncGenerator[TTSResult, None]:
        """
        Synthesize speech from a streaming text source.

        Buffers text until sentence boundaries are detected,
        then synthesizes each sentence incrementally.

        Args:
            text_stream: Async generator yielding text chunks

        Yields:
            TTSResult for each synthesized sentence
        """
        buffer = ""

        async for chunk in text_stream:
            buffer += chunk

            # Look for sentence boundaries
            while True:
                match = SENTENCE_END_PATTERN.search(buffer)
                if match:
                    # Extract complete sentence
                    end_pos = match.end()
                    sentence = buffer[:end_pos].strip()
                    buffer = buffer[end_pos:]

                    if sentence:
                        result = await self.synthesize(sentence)
                        yield result
                else:
                    break

        # Flush remaining buffer
        buffer = buffer.strip()
        if buffer:
            result = await self.synthesize(buffer)
            yield result


def _prepare_text_for_tts(text: str) -> str:
    """
    Preprocess text for better TTS pronunciation.

    Handles special characters like percentages, temperatures, etc.
    """
    replacements = {
        "%": " percent",
        "°C": " degrees Celsius",
        "°F": " degrees Fahrenheit",
        "°": " degrees",
    }

    for original, replacement in replacements.items():
        text = text.replace(original, replacement)

    # Strip markdown annotations like *text*
    result = ""
    in_annotation = False
    for ch in text:
        if ch == "*":
            in_annotation = not in_annotation
        elif not in_annotation:
            result += ch

    return result


class EdgeTTSSpeaker(Speaker):
    """
    Speaker using Microsoft Edge TTS.

    Free TTS service with good quality voices.
    """

    def __init__(
        self,
        voice: str = "en-US-GuyNeural",
        rate: str = "+0%",
        volume: str = "+0%",
    ):
        """
        Initialize the Edge TTS speaker.

        Args:
            voice: Voice name (e.g., "en-US-GuyNeural", "en-US-JennyNeural")
            rate: Speech rate adjustment (e.g., "+10%", "-20%")
            volume: Volume adjustment (e.g., "+10%", "-20%")
        """
        self.voice = voice
        self.rate = rate
        self.volume = volume

    async def synthesize(self, text: str) -> TTSResult:
        """Synthesize speech using Edge TTS."""
        import edge_tts

        text = _prepare_text_for_tts(text)

        communicate = edge_tts.Communicate(
            text,
            voice=self.voice,
            rate=self.rate,
            volume=self.volume,
        )

        audio_data = b""
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_data += chunk["data"]

        return TTSResult(
            audio_data=audio_data,
            format="mp3",
            sample_rate=24000,
        )


class RemoteTTSSpeaker(Speaker):
    """
    Speaker using a remote TTS server.

    Expects a server that accepts text and returns audio.
    """

    def __init__(
        self,
        url: str,
        host_header: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize the remote TTS speaker.

        Args:
            url: URL of the TTS endpoint
            host_header: Optional Host header value
            timeout: Request timeout in seconds
        """
        self.url = url
        self.host_header = host_header
        self.timeout = timeout

    async def synthesize(self, text: str) -> TTSResult:
        """Synthesize speech using remote TTS server."""
        import httpx

        text = _prepare_text_for_tts(text)
        padded_text = f". {text}"  # Padding for better prosody

        headers = {"Content-Type": "text/plain; charset=utf-8"}
        if self.host_header:
            headers["Host"] = self.host_header

        async with httpx.AsyncClient(timeout=self.timeout, verify=False) as client:
            response = await client.post(
                self.url,
                headers=headers,
                content=padded_text,
            )
            response.raise_for_status()

            return TTSResult(
                audio_data=response.content,
                format="wav",
                sample_rate=22050,  # Common for many TTS servers
            )


class AudioPlayer:
    """
    Audio playback utility.

    Supports playing audio from various formats.
    """

    def __init__(self):
        self._current_playback = None
        self._lock = asyncio.Lock()

    async def play(self, result: TTSResult, block: bool = True) -> None:
        """
        Play audio from a TTS result.

        Args:
            result: TTSResult to play
            block: Whether to block until playback completes
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: self._play_sync(result, block))

    def _play_sync(self, result: TTSResult, block: bool = True) -> None:
        """Synchronous audio playback."""
        try:
            import simpleaudio

            # Handle different formats
            if result.format == "mp3":
                # Convert MP3 to WAV for simpleaudio
                audio_data = self._convert_mp3_to_wav(result.audio_data)
            elif result.format == "wav":
                audio_data = result.audio_data
            else:
                # Assume raw PCM
                audio_data = self._wrap_raw_as_wav(
                    result.audio_data, result.sample_rate
                )

            # Write to temp file and play
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(audio_data)
                f.flush()

                wave_obj = simpleaudio.WaveObject.from_wave_file(f.name)
                play_obj = wave_obj.play()

                if block:
                    play_obj.wait_done()
                else:
                    self._current_playback = play_obj

        except ImportError:
            logger.warning("simpleaudio not available, skipping playback")
        except Exception as e:
            logger.error(f"Audio playback error: {e}")

    def _convert_mp3_to_wav(self, mp3_data: bytes) -> bytes:
        """Convert MP3 to WAV format."""
        try:
            from pydub import AudioSegment

            audio = AudioSegment.from_mp3(io.BytesIO(mp3_data))
            buffer = io.BytesIO()
            audio.export(buffer, format="wav")
            return buffer.getvalue()
        except ImportError:
            # Fall back to ffmpeg if pydub not available
            import subprocess

            result = subprocess.run(
                ["ffmpeg", "-i", "pipe:0", "-f", "wav", "pipe:1"],
                input=mp3_data,
                capture_output=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()}")
            return result.stdout

    def _wrap_raw_as_wav(self, raw_data: bytes, sample_rate: int) -> bytes:
        """Wrap raw PCM data as WAV."""
        import wave

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(raw_data)
        return buffer.getvalue()

    def stop(self) -> None:
        """Stop current playback."""
        if self._current_playback:
            try:
                self._current_playback.stop()
            except Exception:
                pass
            self._current_playback = None

    def is_playing(self) -> bool:
        """Check if audio is currently playing."""
        if self._current_playback:
            return self._current_playback.is_playing()
        return False


def extract_sentences(text: str) -> List[str]:
    """
    Extract sentences from text.

    Uses NLTK for better sentence tokenization when available,
    falls back to simple regex otherwise.
    """
    try:
        from nltk import sent_tokenize

        return sent_tokenize(text)
    except ImportError:
        # Simple fallback
        sentences = SENTENCE_END_PATTERN.split(text)
        return [s.strip() for s in sentences if s.strip()]


def create_speaker(
    backend: str = "edge",
    **kwargs,
) -> Speaker:
    """
    Create a speaker with the specified backend.

    Args:
        backend: Backend type ("edge", "remote")
        **kwargs: Additional arguments passed to the speaker

    Returns:
        Speaker instance
    """
    backends = {
        "edge": EdgeTTSSpeaker,
        "remote": RemoteTTSSpeaker,
    }

    if backend not in backends:
        raise ValueError(
            f"Unknown backend: {backend}. Available: {list(backends.keys())}"
        )

    return backends[backend](**kwargs)
