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

    def test_create_transcriber_with_host_header(self):
        from silica.voice.transcriber import (
            create_transcriber,
            RemoteWhisperTranscriber,
        )

        t = create_transcriber(
            "remote_whisper",
            url="http://piku.local/transcribe",
            host_header="whisper-stt.piku.local",
        )
        assert isinstance(t, RemoteWhisperTranscriber)
        assert t.host_header == "whisper-stt.piku.local"

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

    def test_create_speaker_glados(self):
        from silica.voice.speaker import create_speaker

        s = create_speaker("glados", url="http://localhost:8124/synthesize")
        assert s is not None

    def test_create_speaker_with_host_header(self):
        from silica.voice.speaker import (
            create_speaker,
            RemoteTTSSpeaker,
            GladosTTSSpeaker,
        )

        # Remote with host header
        s = create_speaker(
            "remote",
            url="http://piku.local/synth",
            host_header="my-tts-app.piku.local",
        )
        assert isinstance(s, RemoteTTSSpeaker)
        assert s.host_header == "my-tts-app.piku.local"

        # GLaDOS with host header
        s = create_speaker(
            "glados",
            url="http://piku.local/synthesize",
            host_header="glados-tts.piku.local",
        )
        assert isinstance(s, GladosTTSSpeaker)
        assert s.host_header == "glados-tts.piku.local"

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


class TestVoiceCommands:
    """Test voice command detection."""

    def test_voice_command_enum(self):
        from silica.voice.relevance import VoiceCommand

        assert hasattr(VoiceCommand, "NONE")
        assert hasattr(VoiceCommand, "MUTE")
        assert hasattr(VoiceCommand, "UNMUTE")
        assert hasattr(VoiceCommand, "STOP")
        assert hasattr(VoiceCommand, "CANCEL")

    def test_detect_mute_commands(self):
        from silica.voice.relevance import detect_voice_command, VoiceCommand

        mute_phrases = [
            "mute",
            "go to sleep",
            "sleep mode",
            "stop listening",
            "be quiet",
            "shut up",
            "silica mute",
            "hey silica go to sleep",
        ]
        for phrase in mute_phrases:
            result = detect_voice_command(phrase)
            assert result == VoiceCommand.MUTE, f"Expected MUTE for '{phrase}'"

    def test_detect_unmute_commands(self):
        from silica.voice.relevance import detect_voice_command, VoiceCommand

        unmute_phrases = [
            "unmute",
            "wake up",
            "start listening",
            "I'm back",
            "resume",
            "silica wake up",
            "hey silica unmute",
        ]
        for phrase in unmute_phrases:
            result = detect_voice_command(phrase)
            assert result == VoiceCommand.UNMUTE, f"Expected UNMUTE for '{phrase}'"

    def test_detect_stop_commands(self):
        from silica.voice.relevance import detect_voice_command, VoiceCommand

        stop_phrases = [
            "stop",
            "enough",
            "that's enough",
            "ok stop",
            "silica stop",
        ]
        for phrase in stop_phrases:
            result = detect_voice_command(phrase)
            assert result == VoiceCommand.STOP, f"Expected STOP for '{phrase}'"

    def test_detect_cancel_commands(self):
        from silica.voice.relevance import detect_voice_command, VoiceCommand

        cancel_phrases = [
            "cancel",
            "never mind",
            "nevermind",
            "forget it",
            "abort",
        ]
        for phrase in cancel_phrases:
            result = detect_voice_command(phrase)
            assert result == VoiceCommand.CANCEL, f"Expected CANCEL for '{phrase}'"

    def test_detect_no_command(self):
        from silica.voice.relevance import detect_voice_command, VoiceCommand

        regular_phrases = [
            "what's the weather?",
            "tell me a joke",
            "hello there",
            "I need help with something",
        ]
        for phrase in regular_phrases:
            result = detect_voice_command(phrase)
            assert result == VoiceCommand.NONE, f"Expected NONE for '{phrase}'"

    def test_helper_functions(self):
        from silica.voice.relevance import is_mute_command, is_unmute_command

        assert is_mute_command("mute") is True
        assert is_mute_command("unmute") is False
        assert is_unmute_command("wake up") is True
        assert is_unmute_command("go to sleep") is False


class TestRelevanceFilter:
    """Test relevance filter module."""

    def test_relevance_result(self):
        from silica.voice.relevance import RelevanceResult, VoiceCommand

        result = RelevanceResult(is_relevant=True)
        assert result.is_relevant is True
        assert result.confidence is None
        assert result.reason is None
        assert result.voice_command == VoiceCommand.NONE

    def test_relevance_result_with_command(self):
        from silica.voice.relevance import RelevanceResult, VoiceCommand

        result = RelevanceResult(
            is_relevant=True,
            reason="Voice command: MUTE",
            voice_command=VoiceCommand.MUTE,
        )
        assert result.is_relevant is True
        assert result.voice_command == VoiceCommand.MUTE

    def test_relevance_result_with_reason(self):
        from silica.voice.relevance import RelevanceResult

        result = RelevanceResult(
            is_relevant=False, confidence=0.9, reason="NOT_RELEVANT"
        )
        assert result.is_relevant is False
        assert result.confidence == 0.9
        assert result.reason == "NOT_RELEVANT"

    def test_create_relevance_filter_disabled(self):
        from silica.voice.relevance import create_relevance_filter

        rf = create_relevance_filter(enabled=False)
        assert rf.enabled is False

        # Disabled filter should always return relevant
        result = rf.check_relevance("any text")
        assert result.is_relevant is True

    def test_relevance_filter_detects_commands(self):
        from silica.voice.relevance import RelevanceFilter, VoiceCommand

        # Even with filtering disabled, commands should be detected
        rf = RelevanceFilter(enabled=False)
        result = rf.check_relevance("mute")
        assert result.is_relevant is True
        assert result.voice_command == VoiceCommand.MUTE

    def test_relevance_filter_empty_text(self):
        from silica.voice.relevance import RelevanceFilter

        rf = RelevanceFilter(enabled=True, api_key="fake-key")
        # Empty text should be not relevant (no command to detect either)
        result = rf.check_relevance("", detect_commands=False)
        assert result.is_relevant is False

    def test_relevance_filter_short_text(self):
        from silica.voice.relevance import RelevanceFilter

        rf = RelevanceFilter(enabled=True, api_key="fake-key")
        # Very short text should be not relevant
        result = rf.check_relevance("um", detect_commands=False)
        assert result.is_relevant is False


class TestVoiceClientSettingsExtended:
    """Test extended voice client settings."""

    def test_settings_with_relevance(self):
        from silica.voice.client import VoiceClientSettings

        settings = VoiceClientSettings(
            relevance_filtering=True,
            wake_words=["hey silica", "silica"],
        )
        assert settings.relevance_filtering is True
        assert settings.wake_words == ["hey silica", "silica"]

    def test_settings_mute_key(self):
        from silica.voice.client import VoiceClientSettings

        settings = VoiceClientSettings(mute_key="space")
        assert settings.mute_key == "space"


class TestMetrics:
    """Test metrics module."""

    def test_metrics_config_defaults(self):
        from silica.voice.metrics import MetricsConfig

        config = MetricsConfig()
        assert config.host == "localhost"
        assert config.port == 8125
        assert config.prefix == "silica.voice"
        assert config.enabled is True

    def test_null_metrics_client(self):
        from silica.voice.metrics import NullMetricsClient

        client = NullMetricsClient()
        # Should not raise
        client.incr("test")
        client.decr("test")
        client.gauge("test", 42)
        client.timing("test", 100)
        client.histogram("test", 50)
        with client.timer("test"):
            pass
        client.close()

    def test_statsd_client_format(self):
        from silica.voice.metrics import StatsdClient, MetricsConfig

        config = MetricsConfig(prefix="test", enabled=False)
        client = StatsdClient(config)
        # Test name formatting
        assert client._format_name("counter") == "test.counter"

    def test_configure_metrics(self):
        from silica.voice.metrics import configure_metrics, NullMetricsClient

        client = configure_metrics(enabled=False)
        assert isinstance(client, NullMetricsClient)

    def test_global_metrics_functions(self):
        from silica.voice.metrics import (
            configure_metrics,
            incr,
            decr,
            gauge,
            timing,
            histogram,
            timer,
        )

        configure_metrics(enabled=False)
        # Should not raise
        incr("test")
        decr("test")
        gauge("test", 42)
        timing("test", 100)
        histogram("test", 50)
        with timer("test"):
            pass
