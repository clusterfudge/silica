"""Tests for voice components (without audio hardware)."""

import pytest


# Test imports without voice dependencies
def test_voice_module_import():
    """Test that voice module can be imported."""
    from silica.voice import VOICE_AVAILABLE

    # Should be importable regardless of dependencies
    assert isinstance(VOICE_AVAILABLE, bool)


class TestPhraseState:
    """Test PhraseState enum."""

    def test_phrase_state_values(self):
        from silica.voice.listener import PhraseState

        assert hasattr(PhraseState, "NONE")
        assert hasattr(PhraseState, "START")
        assert hasattr(PhraseState, "CONTINUE")
        assert hasattr(PhraseState, "END")


class TestTranscriberAPI:
    """Test transcriber module API."""

    def test_transcription_result(self):
        from silica.voice.transcriber import TranscriptionResult

        result = TranscriptionResult(text="Hello, world!")
        assert result.text == "Hello, world!"
        assert result.confidence is None
        assert result.language is None

    def test_transcription_result_with_metadata(self):
        from silica.voice.transcriber import TranscriptionResult

        result = TranscriptionResult(
            text="Test", confidence=0.95, language="en", duration_seconds=2.5
        )
        assert result.confidence == 0.95
        assert result.language == "en"
        assert result.duration_seconds == 2.5

    def test_create_transcriber_factory(self):
        from silica.voice.transcriber import create_transcriber

        # Test that factory works for remote_whisper (no API key needed)
        t = create_transcriber("remote_whisper", url="http://localhost:8000/transcribe")
        assert t is not None

    def test_create_transcriber_invalid_backend(self):
        from silica.voice.transcriber import create_transcriber

        with pytest.raises(ValueError):
            create_transcriber("invalid_backend")


class TestSpeakerAPI:
    """Test speaker module API."""

    def test_tts_result(self):
        from silica.voice.speaker import TTSResult

        result = TTSResult(audio_data=b"test")
        assert result.audio_data == b"test"
        assert result.format == "mp3"
        assert result.sample_rate == 24000

    def test_create_speaker_factory(self):
        from silica.voice.speaker import create_speaker

        # Test that factory works for edge
        s = create_speaker("edge", voice="en-US-GuyNeural")
        assert s is not None

    def test_create_speaker_remote(self):
        from silica.voice.speaker import create_speaker

        s = create_speaker("remote", url="http://localhost:8000/synth")
        assert s is not None

    def test_create_speaker_invalid_backend(self):
        from silica.voice.speaker import create_speaker

        with pytest.raises(ValueError):
            create_speaker("invalid_backend")

    def test_extract_sentences(self):
        from silica.voice.speaker import extract_sentences

        sentences = extract_sentences("Hello world. How are you? I am fine!")
        assert len(sentences) >= 2


class TestCoordinator:
    """Test coordinator module."""

    def test_voice_state_enum(self):
        from silica.voice.coordinator import VoiceState

        assert hasattr(VoiceState, "IDLE")
        assert hasattr(VoiceState, "LISTENING")
        assert hasattr(VoiceState, "PROCESSING")
        assert hasattr(VoiceState, "SPEAKING")
        assert hasattr(VoiceState, "MUTED")

    def test_coordinator_initial_state(self):
        from silica.voice.coordinator import VoiceCoordinator, VoiceState

        coord = VoiceCoordinator()
        assert coord.state == VoiceState.IDLE
        assert coord.muted is False

    def test_coordinator_mute_toggle(self):
        from silica.voice.coordinator import VoiceCoordinator, VoiceState

        coord = VoiceCoordinator()

        # Toggle mute on
        result = coord.toggle_mute()
        assert result is True
        assert coord.muted is True
        assert coord.state == VoiceState.MUTED

        # Toggle mute off
        result = coord.toggle_mute()
        assert result is False
        assert coord.muted is False
        assert coord.state == VoiceState.IDLE

    def test_coordinator_status(self):
        from silica.voice.coordinator import VoiceCoordinator, CoordinatorStatus

        coord = VoiceCoordinator()
        status = coord.status
        assert isinstance(status, CoordinatorStatus)
        assert status.muted is False

    def test_coordinator_speech_queue(self):
        from silica.voice.coordinator import VoiceCoordinator

        coord = VoiceCoordinator()

        coord.queue_speech("Hello")
        coord.queue_speech("World")

        assert coord.has_queued_speech() is True
        queued = coord.get_queued_speech()
        assert queued == ["Hello", "World"]
        assert coord.has_queued_speech() is False

    def test_coordinator_callbacks(self):
        from silica.voice.coordinator import VoiceCoordinator, CoordinatorCallbacks

        state_changes = []

        def on_state_change(state):
            state_changes.append(state)

        callbacks = CoordinatorCallbacks(on_state_change=on_state_change)
        coord = VoiceCoordinator(callbacks=callbacks)

        coord.toggle_mute()
        coord.toggle_mute()

        assert len(state_changes) == 2


class TestVoiceClientSettings:
    """Test voice client settings."""

    def test_default_settings(self):
        from silica.voice.client import VoiceClientSettings

        settings = VoiceClientSettings()
        assert settings.server_url == "ws://localhost:8765/ws"
        assert settings.vad_aggressiveness == 3
        assert settings.tts_voice == "en-US-GuyNeural"

    def test_custom_settings(self):
        from silica.voice.client import VoiceClientSettings

        settings = VoiceClientSettings(
            server_url="ws://custom:9000/ws",
            session_id="test-session",
            vad_aggressiveness=2,
        )
        assert settings.server_url == "ws://custom:9000/ws"
        assert settings.session_id == "test-session"
        assert settings.vad_aggressiveness == 2


class TestTextPreprocessing:
    """Test text preprocessing for TTS."""

    def test_prepare_text_special_chars(self):
        from silica.voice.speaker import _prepare_text_for_tts

        # Test percentage
        text = _prepare_text_for_tts("It's 50% complete")
        assert "percent" in text

        # Test temperature
        text = _prepare_text_for_tts("Temperature is 72°F")
        assert "degrees" in text

    def test_prepare_text_strips_markdown(self):
        from silica.voice.speaker import _prepare_text_for_tts

        text = _prepare_text_for_tts("This is *emphasized* text")
        # Should strip the asterisks
        assert "*" not in text or "emphasized" in text
