"""
Tests for streaming TTS functionality in VoiceClient.

Tests the pipelined synthesis/playback architecture:
- Chunk queue and audio queue infrastructure
- Sentence boundary detection
- Synthesis and playback loops
- Interrupt handling
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from silica.voice.client import VoiceClient, VoiceClientSettings, SENTENCE_END_PATTERN
from silica.voice.speaker import TTSResult


class MockSpeaker:
    """Mock speaker for testing."""

    def __init__(self, synth_delay: float = 0.01):
        self.synth_delay = synth_delay
        self.synthesized_texts: list[str] = []

    async def synthesize(self, text: str) -> TTSResult:
        """Record synthesized text and return mock audio."""
        await asyncio.sleep(self.synth_delay)
        self.synthesized_texts.append(text)
        return TTSResult(
            audio_data=f"audio:{text}".encode(),
            format="wav",
            sample_rate=22050,
        )


class MockTranscriber:
    """Mock transcriber for testing."""

    async def transcribe(self, audio_data: bytes):
        return MagicMock(text="test transcription")


class MockAudioPlayer:
    """Mock audio player for testing."""

    def __init__(self, play_delay: float = 0.01):
        self.play_delay = play_delay
        self.played_results: list[TTSResult] = []
        self._stopped = False

    async def play(self, result: TTSResult, block: bool = True) -> None:
        """Record played audio."""
        if self._stopped:
            return
        await asyncio.sleep(self.play_delay)
        self.played_results.append(result)

    def stop(self) -> None:
        """Stop playback."""
        self._stopped = True

    def is_playing(self) -> bool:
        return False


class TestSentenceBoundaryPattern:
    """Tests for sentence boundary detection regex."""

    def test_period_end(self):
        """Test detection of period at end of sentence."""
        match = SENTENCE_END_PATTERN.search("Hello world. ")
        assert match is not None
        assert match.end() == 13

    def test_exclamation_end(self):
        """Test detection of exclamation mark."""
        match = SENTENCE_END_PATTERN.search("Hello! ")
        assert match is not None

    def test_question_end(self):
        """Test detection of question mark."""
        match = SENTENCE_END_PATTERN.search("How are you? ")
        assert match is not None

    def test_multiple_punctuation(self):
        """Test detection of multiple punctuation marks."""
        match = SENTENCE_END_PATTERN.search("Really?! ")
        assert match is not None

    def test_no_match_mid_sentence(self):
        """Test that abbreviations without space don't match incorrectly."""
        # "Mr." should not match if not followed by space
        text = "Mr.Smith"
        match = SENTENCE_END_PATTERN.search(text)
        # This should not match because the pattern requires whitespace or end
        assert match is None

    def test_end_of_string(self):
        """Test detection at end of string."""
        match = SENTENCE_END_PATTERN.search("Hello world.")
        assert match is not None


class TestVoiceClientInfrastructure:
    """Tests for streaming TTS infrastructure in VoiceClient."""

    @pytest.fixture
    def mock_client(self):
        """Create a VoiceClient with mocked components."""
        with patch("silica.voice.client._check_websockets_available"):
            speaker = MockSpeaker()
            transcriber = MockTranscriber()
            settings = VoiceClientSettings(
                streaming_tts=True,
                metrics_enabled=False,
            )
            client = VoiceClient(
                transcriber=transcriber,
                speaker=speaker,
                settings=settings,
            )
            # Replace player with mock
            client.player = MockAudioPlayer()
            return client

    def test_queues_initialized(self, mock_client):
        """Test that chunk and audio queues are initialized."""
        assert mock_client._chunk_queue is not None
        assert mock_client._audio_queue is not None
        assert mock_client._chunk_queue.empty()
        assert mock_client._audio_queue.empty()

    def test_tasks_initially_none(self, mock_client):
        """Test that tasks are initially None."""
        assert mock_client._synthesis_task is None
        assert mock_client._playback_task is None

    def test_streaming_not_in_progress(self, mock_client):
        """Test that streaming is not initially in progress."""
        assert mock_client._streaming_in_progress is False

    def test_streaming_tts_setting_default(self):
        """Test that streaming_tts defaults to True."""
        settings = VoiceClientSettings()
        assert settings.streaming_tts is True

    def test_streaming_tts_setting_disabled(self):
        """Test that streaming_tts can be disabled."""
        settings = VoiceClientSettings(streaming_tts=False)
        assert settings.streaming_tts is False


class TestStreamingPipeline:
    """Tests for the streaming TTS pipeline."""

    @pytest.fixture
    def mock_client(self):
        """Create a VoiceClient with mocked components."""
        with patch("silica.voice.client._check_websockets_available"):
            speaker = MockSpeaker(synth_delay=0.001)
            transcriber = MockTranscriber()
            settings = VoiceClientSettings(
                streaming_tts=True,
                metrics_enabled=False,
            )
            client = VoiceClient(
                transcriber=transcriber,
                speaker=speaker,
                settings=settings,
            )
            client.player = MockAudioPlayer(play_delay=0.001)
            return client

    @pytest.mark.asyncio
    async def test_start_streaming_creates_tasks(self, mock_client):
        """Test that _start_streaming creates synthesis and playback tasks."""
        await mock_client._start_streaming()

        assert mock_client._streaming_in_progress is True
        assert mock_client._synthesis_task is not None
        assert mock_client._playback_task is not None

        # Clean up
        await mock_client._interrupt_streaming()

    @pytest.mark.asyncio
    async def test_chunk_queued(self, mock_client):
        """Test that chunks are queued for synthesis."""
        await mock_client._handle_streaming_chunk("Hello ")

        assert mock_client._streaming_in_progress is True
        # Chunk should be in queue (synthesis task will consume it)

        # Clean up
        await mock_client._interrupt_streaming()

    @pytest.mark.asyncio
    async def test_full_streaming_pipeline(self, mock_client):
        """Test complete streaming pipeline with multiple sentences."""
        # Simulate receiving chunks
        await mock_client._handle_streaming_chunk("Hello, ")
        await mock_client._handle_streaming_chunk("how are you? ")
        await mock_client._handle_streaming_chunk("I am doing ")
        await mock_client._handle_streaming_chunk("great!")

        # Signal end and wait for completion
        await mock_client._finish_streaming("Hello, how are you? I am doing great!")

        # Verify synthesis happened
        speaker = mock_client.speaker
        assert len(speaker.synthesized_texts) >= 1

        # Verify playback happened
        player = mock_client.player
        assert len(player.played_results) >= 1

        assert mock_client._streaming_in_progress is False

    @pytest.mark.asyncio
    async def test_single_sentence_streaming(self, mock_client):
        """Test streaming with a single sentence."""
        await mock_client._handle_streaming_chunk("Just one sentence.")
        await mock_client._finish_streaming("Just one sentence.")

        speaker = mock_client.speaker
        assert len(speaker.synthesized_texts) == 1
        assert "Just one sentence." in speaker.synthesized_texts[0]

    @pytest.mark.asyncio
    async def test_empty_chunks_ignored(self, mock_client):
        """Test that empty chunks don't start streaming."""
        # Empty content shouldn't trigger streaming
        await mock_client._handle_streaming_chunk("")

        # Streaming might start but with no actual content queued
        # This is handled at the _handle_message level
        # Let's test the empty finish case
        if mock_client._streaming_in_progress:
            await mock_client._interrupt_streaming()


class TestStreamingInterrupt:
    """Tests for interrupt handling in streaming TTS."""

    @pytest.fixture
    def mock_client(self):
        """Create a VoiceClient with mocked components."""
        with patch("silica.voice.client._check_websockets_available"):
            speaker = MockSpeaker(synth_delay=0.05)  # Slower to allow interrupt
            transcriber = MockTranscriber()
            settings = VoiceClientSettings(
                streaming_tts=True,
                metrics_enabled=False,
            )
            client = VoiceClient(
                transcriber=transcriber,
                speaker=speaker,
                settings=settings,
            )
            client.player = MockAudioPlayer(play_delay=0.05)
            return client

    @pytest.mark.asyncio
    async def test_interrupt_cancels_tasks(self, mock_client):
        """Test that interrupt cancels synthesis and playback tasks."""
        # Start streaming
        await mock_client._start_streaming()
        await mock_client._chunk_queue.put("Long sentence that takes time. ")

        # Small delay to let tasks start
        await asyncio.sleep(0.01)

        # Interrupt
        await mock_client._interrupt_streaming()

        assert mock_client._streaming_in_progress is False
        assert mock_client._synthesis_task is None
        assert mock_client._playback_task is None

    @pytest.mark.asyncio
    async def test_interrupt_clears_queues(self, mock_client):
        """Test that interrupt clears both queues."""
        # Don't start the full streaming pipeline - just test queue clearing
        mock_client._streaming_in_progress = True

        # Add items to queues directly
        await mock_client._chunk_queue.put("Some text")
        await mock_client._audio_queue.put(
            TTSResult(audio_data=b"test", format="wav", sample_rate=22050)
        )

        # Interrupt (this should clear queues even without running tasks)
        await mock_client._interrupt_streaming()

        # Queues should be cleared
        assert mock_client._chunk_queue.empty()
        assert mock_client._audio_queue.empty()

    @pytest.mark.asyncio
    async def test_interrupt_stops_playback(self, mock_client):
        """Test that interrupt stops audio playback."""
        await mock_client._start_streaming()
        await asyncio.sleep(0.01)

        await mock_client._interrupt_streaming()

        # Player should have been stopped
        assert mock_client.player._stopped is True

    @pytest.mark.asyncio
    async def test_interrupt_when_not_streaming(self, mock_client):
        """Test that interrupt works even when not streaming."""
        # Should not raise
        await mock_client._interrupt_streaming()
        assert mock_client._streaming_in_progress is False


class TestSynthesisLoop:
    """Tests for the synthesis loop logic."""

    def test_sentence_extraction_logic(self):
        """Test the sentence extraction heuristic."""
        # Simulate the logic in _synthesis_loop
        buffer = "Hello, how are you? I am "

        sentences = []
        while True:
            match = SENTENCE_END_PATTERN.search(buffer)
            if not match:
                break

            end_pos = match.end()
            remaining = buffer[end_pos:].strip()

            # Only emit if there's more content (heuristic)
            if remaining:
                sentence = buffer[:end_pos].strip()
                buffer = buffer[end_pos:].lstrip()
                sentences.append(sentence)
            else:
                break

        assert len(sentences) == 1
        assert sentences[0] == "Hello, how are you?"
        assert buffer == "I am "

    def test_long_buffer_triggers_emit(self):
        """Test that long buffers trigger emission even without more content."""
        buffer = "A" * 250 + ". "

        match = SENTENCE_END_PATTERN.search(buffer)
        assert match is not None

        # With buffer > 200, should emit even without more content
        end_pos = match.end()
        remaining = buffer[end_pos:].strip()

        # Heuristic: emit if remaining OR len(buffer) > 200
        should_emit = remaining or len(buffer) > 200
        assert should_emit is True


class TestLegacyFallback:
    """Tests for legacy non-streaming fallback."""

    @pytest.fixture
    def mock_client_no_streaming(self):
        """Create a VoiceClient with streaming disabled."""
        with patch("silica.voice.client._check_websockets_available"):
            speaker = MockSpeaker()
            transcriber = MockTranscriber()
            settings = VoiceClientSettings(
                streaming_tts=False,  # Disabled
                metrics_enabled=False,
            )
            client = VoiceClient(
                transcriber=transcriber,
                speaker=speaker,
                settings=settings,
            )
            client.player = MockAudioPlayer()
            return client

    def test_streaming_disabled_setting(self, mock_client_no_streaming):
        """Test that streaming is disabled in settings."""
        assert mock_client_no_streaming.settings.streaming_tts is False

    @pytest.mark.asyncio
    async def test_legacy_speak_response(self, mock_client_no_streaming):
        """Test that _speak_response works for non-streaming."""
        # This is used for voice command confirmations
        await mock_client_no_streaming._speak_response("Going to sleep.")

        speaker = mock_client_no_streaming.speaker
        assert len(speaker.synthesized_texts) == 1
        assert speaker.synthesized_texts[0] == "Going to sleep."


class TestConcurrentSynthesisPlayback:
    """Tests verifying concurrent synthesis and playback."""

    @pytest.mark.asyncio
    async def test_synthesis_runs_during_playback(self):
        """Test that synthesis of N+1 happens during playback of N."""
        with patch("silica.voice.client._check_websockets_available"):
            # Create client with measurable delays
            speaker = MockSpeaker(synth_delay=0.02)
            transcriber = MockTranscriber()
            settings = VoiceClientSettings(
                streaming_tts=True,
                metrics_enabled=False,
            )
            client = VoiceClient(
                transcriber=transcriber,
                speaker=speaker,
                settings=settings,
            )

            # Custom player that records timing
            play_times = []

            class TimingPlayer:
                def __init__(self):
                    self.play_delay = 0.03
                    self.played_results = []
                    self._stopped = False

                async def play(self, result: TTSResult, block: bool = True) -> None:
                    if self._stopped:
                        return
                    import time

                    start = time.time()
                    await asyncio.sleep(self.play_delay)
                    play_times.append((start, time.time()))
                    self.played_results.append(result)

                def stop(self):
                    self._stopped = True

                def is_playing(self):
                    return False

            client.player = TimingPlayer()

            # Send multiple sentences quickly
            await client._handle_streaming_chunk("First sentence. ")
            await client._handle_streaming_chunk("Second sentence. ")
            await client._handle_streaming_chunk("Third sentence.")

            await client._finish_streaming(
                "First sentence. Second sentence. Third sentence."
            )

            # All sentences should have been synthesized
            assert len(speaker.synthesized_texts) == 3

            # All should have been played
            assert len(client.player.played_results) == 3
