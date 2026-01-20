"""
Voice Transcriber for Silica.

This module provides speech-to-text transcription with pluggable backends.
Supports remote Whisper, OpenAI, and Deepgram APIs.
"""

import asyncio
import io
import logging
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Audio constants (matching listener.py)
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2


@dataclass
class TranscriptionResult:
    """Result of a transcription operation."""

    text: str
    confidence: Optional[float] = None
    language: Optional[str] = None
    duration_seconds: Optional[float] = None


class Transcriber(ABC):
    """
    Abstract base class for speech-to-text transcribers.

    Subclasses must implement the transcribe method.
    """

    @abstractmethod
    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = SAMPLE_RATE,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """
        Transcribe audio data to text.

        Args:
            audio_data: Raw 16-bit PCM audio data
            sample_rate: Sample rate of the audio
            language: Optional language hint (e.g., "en", "es")

        Returns:
            TranscriptionResult with the transcribed text
        """

    def transcribe_sync(
        self,
        audio_data: bytes,
        sample_rate: int = SAMPLE_RATE,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Synchronous wrapper for transcribe."""
        return asyncio.run(self.transcribe(audio_data, sample_rate, language))


def _audio_to_wav(audio_data: bytes, sample_rate: int) -> bytes:
    """Convert raw PCM audio to WAV format."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(BYTES_PER_SAMPLE)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data)
    return buffer.getvalue()


class RemoteWhisperTranscriber(Transcriber):
    """
    Transcriber using a remote Whisper server.

    Expects a server that accepts audio files via multipart form upload
    and returns JSON with a "text" field.

    Supports Host header override for piku-style routing where multiple
    apps share the same IP/port and are differentiated by Host header.
    """

    def __init__(
        self,
        url: str = "http://localhost:8000/transcribe",
        host_header: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize the remote Whisper transcriber.

        Args:
            url: URL of the Whisper transcription endpoint
            host_header: Optional Host header for piku-style routing
            timeout: Request timeout in seconds
        """
        self.url = url
        self.host_header = host_header
        self.timeout = timeout

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = SAMPLE_RATE,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio using remote Whisper server."""
        wav_data = _audio_to_wav(audio_data, sample_rate)

        headers = {}
        if self.host_header:
            headers["Host"] = self.host_header

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            files = {"file": ("audio.wav", wav_data, "audio/wav")}
            data = {}
            if language:
                data["language"] = language

            try:
                response = await client.post(
                    self.url, files=files, data=data, headers=headers
                )
                response.raise_for_status()
                result = response.json()

                return TranscriptionResult(
                    text=result.get("text", "").strip(),
                    confidence=result.get("confidence"),
                    language=result.get("language"),
                    duration_seconds=result.get("duration"),
                )
            except httpx.HTTPError as e:
                logger.error(f"Remote Whisper transcription failed: {e}")
                raise


class OpenAITranscriber(Transcriber):
    """
    Transcriber using OpenAI's Whisper API.

    Requires an OpenAI API key set in the environment or passed directly.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "whisper-1",
        timeout: float = 30.0,
    ):
        """
        Initialize the OpenAI Whisper transcriber.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Whisper model to use
            timeout: Request timeout in seconds
        """
        import os

        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required")
        self.model = model
        self.timeout = timeout
        self.url = "https://api.openai.com/v1/audio/transcriptions"

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = SAMPLE_RATE,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio using OpenAI Whisper API."""
        wav_data = _audio_to_wav(audio_data, sample_rate)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            files = {"file": ("audio.wav", wav_data, "audio/wav")}
            data = {"model": self.model}
            if language:
                data["language"] = language

            headers = {"Authorization": f"Bearer {self.api_key}"}

            try:
                response = await client.post(
                    self.url, files=files, data=data, headers=headers
                )
                response.raise_for_status()
                result = response.json()

                return TranscriptionResult(
                    text=result.get("text", "").strip(),
                    language=language,
                )
            except httpx.HTTPError as e:
                logger.error(f"OpenAI transcription failed: {e}")
                raise


class DeepgramTranscriber(Transcriber):
    """
    Transcriber using Deepgram's API.

    Requires a Deepgram API key set in the environment or passed directly.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "nova-2",
        timeout: float = 30.0,
    ):
        """
        Initialize the Deepgram transcriber.

        Args:
            api_key: Deepgram API key (defaults to DEEPGRAM_API_KEY env var)
            model: Deepgram model to use
            timeout: Request timeout in seconds
        """
        import os

        self.api_key = api_key or os.environ.get("DEEPGRAM_API_KEY")
        if not self.api_key:
            raise ValueError("Deepgram API key required")
        self.model = model
        self.timeout = timeout
        self.url = "https://api.deepgram.com/v1/listen"

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = SAMPLE_RATE,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio using Deepgram API."""
        # Deepgram accepts raw audio directly
        params = {
            "model": self.model,
            "encoding": "linear16",
            "sample_rate": sample_rate,
            "channels": 1,
        }
        if language:
            params["language"] = language

        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "audio/raw",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    self.url,
                    params=params,
                    headers=headers,
                    content=audio_data,
                )
                response.raise_for_status()
                result = response.json()

                # Parse Deepgram response
                alternatives = (
                    result.get("results", {})
                    .get("channels", [{}])[0]
                    .get("alternatives", [{}])
                )
                if alternatives:
                    best = alternatives[0]
                    return TranscriptionResult(
                        text=best.get("transcript", "").strip(),
                        confidence=best.get("confidence"),
                        language=language,
                    )
                return TranscriptionResult(text="")

            except httpx.HTTPError as e:
                logger.error(f"Deepgram transcription failed: {e}")
                raise


class SpeechRecognitionTranscriber(Transcriber):
    """
    Transcriber using the speech_recognition library.

    Supports multiple backends through speech_recognition:
    - Google Speech Recognition (free, no API key)
    - Google Cloud Speech-to-Text
    - Sphinx (offline)
    """

    def __init__(self, backend: str = "google"):
        """
        Initialize the speech_recognition transcriber.

        Args:
            backend: Recognition backend ("google", "sphinx")
        """
        from silica.voice import check_voice_available

        check_voice_available()

        import speech_recognition as sr

        self.recognizer = sr.Recognizer()
        self.backend = backend

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = SAMPLE_RATE,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio using speech_recognition library."""
        import speech_recognition as sr

        # Create AudioData from raw bytes
        audio = sr.AudioData(audio_data, sample_rate, BYTES_PER_SAMPLE)

        # Run recognition in thread pool
        loop = asyncio.get_running_loop()

        def recognize():
            try:
                if self.backend == "google":
                    text = self.recognizer.recognize_google(
                        audio, language=language or "en-US"
                    )
                elif self.backend == "sphinx":
                    text = self.recognizer.recognize_sphinx(audio)
                else:
                    raise ValueError(f"Unknown backend: {self.backend}")
                return TranscriptionResult(text=text)
            except sr.UnknownValueError:
                return TranscriptionResult(text="")
            except sr.RequestError as e:
                logger.error(f"Speech recognition error: {e}")
                raise

        return await loop.run_in_executor(None, recognize)


def create_transcriber(
    backend: str = "remote_whisper",
    **kwargs,
) -> Transcriber:
    """
    Create a transcriber with the specified backend.

    Args:
        backend: Backend type ("remote_whisper", "openai", "deepgram", "google", "sphinx")
        **kwargs: Additional arguments passed to the transcriber

    Returns:
        Transcriber instance
    """
    backends = {
        "remote_whisper": RemoteWhisperTranscriber,
        "openai": OpenAITranscriber,
        "deepgram": DeepgramTranscriber,
        "google": lambda **kw: SpeechRecognitionTranscriber(backend="google"),
        "sphinx": lambda **kw: SpeechRecognitionTranscriber(backend="sphinx"),
    }

    if backend not in backends:
        raise ValueError(
            f"Unknown backend: {backend}. Available: {list(backends.keys())}"
        )

    return backends[backend](**kwargs)
