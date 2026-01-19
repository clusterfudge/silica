"""
CLI command for the Silica Voice client.
"""

import asyncio
import logging
from typing import Annotated, Optional

import cyclopts

voice_app = cyclopts.App(name="voice", help="Run the Silica voice interface")


@voice_app.default
def voice(
    server_url: Annotated[
        str, cyclopts.Parameter(help="WebSocket server URL")
    ] = "ws://localhost:8765/ws",
    session_id: Annotated[
        Optional[str], cyclopts.Parameter(help="Session ID to resume")
    ] = None,
    # STT settings
    stt_backend: Annotated[
        str,
        cyclopts.Parameter(
            help="STT backend (remote_whisper, openai, deepgram, google)"
        ),
    ] = "remote_whisper",
    stt_url: Annotated[
        str, cyclopts.Parameter(help="Remote Whisper URL (for remote_whisper backend)")
    ] = "http://localhost:8000/transcribe",
    # TTS settings
    tts_backend: Annotated[
        str, cyclopts.Parameter(help="TTS backend (edge, remote)")
    ] = "edge",
    tts_voice: Annotated[
        str, cyclopts.Parameter(help="TTS voice name")
    ] = "en-US-GuyNeural",
    tts_url: Annotated[
        Optional[str], cyclopts.Parameter(help="Remote TTS URL (for remote backend)")
    ] = None,
    # Audio settings
    device_index: Annotated[
        Optional[int], cyclopts.Parameter(help="Audio input device index")
    ] = None,
    device_name: Annotated[
        Optional[str], cyclopts.Parameter(help="Audio input device name")
    ] = None,
    vad_aggressiveness: Annotated[
        int, cyclopts.Parameter(help="VAD aggressiveness (0-3)")
    ] = 3,
    # Other settings
    verbose: Annotated[bool, cyclopts.Parameter(help="Enable verbose logging")] = False,
    list_devices: Annotated[
        bool, cyclopts.Parameter(help="List available audio devices and exit")
    ] = False,
):
    """
    Run the Silica voice interface.

    The voice interface captures speech, transcribes it, sends to a silica serve
    instance, and speaks the responses.

    Example:
        silica voice --server-url ws://localhost:8765/ws
        silica voice --stt-backend openai --tts-voice en-US-JennyNeural
        silica voice --list-devices
    """
    # Set up logging
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    logger = logging.getLogger("silica.voice")

    # Check for voice dependencies
    try:
        from silica.voice import check_voice_available

        check_voice_available()
    except ImportError as e:
        print(f"Error: {e}")
        print("\nVoice dependencies not installed. Install with:")
        print("  pip install silica[voice]")
        return 1

    # List devices if requested
    if list_devices:
        from silica.voice.listener import list_microphones

        print("\nAvailable audio input devices:")
        print("-" * 50)
        for idx, info in list_microphones():
            name = info.get("name", "Unknown")
            channels = info.get("maxInputChannels", 0)
            rate = info.get("defaultSampleRate", 0)
            print(f"  [{idx}] {name}")
            print(f"       Channels: {channels}, Rate: {rate}")
        return 0

    # Build transcriber kwargs
    transcriber_kwargs = {}
    if stt_backend == "remote_whisper":
        transcriber_kwargs["url"] = stt_url
    elif stt_backend == "openai":
        # Uses OPENAI_API_KEY from env
        pass
    elif stt_backend == "deepgram":
        # Uses DEEPGRAM_API_KEY from env
        pass

    # Build speaker kwargs
    speaker_kwargs = {}
    if tts_backend == "edge":
        speaker_kwargs["voice"] = tts_voice
    elif tts_backend == "remote" and tts_url:
        speaker_kwargs["url"] = tts_url

    # Build settings kwargs
    settings_kwargs = {
        "session_id": session_id,
        "device_index": device_index,
        "device_name": device_name,
        "vad_aggressiveness": vad_aggressiveness,
        "tts_voice": tts_voice,
    }
    # Remove None values
    settings_kwargs = {k: v for k, v in settings_kwargs.items() if v is not None}

    print("Starting Silica voice interface...")
    print(f"  Server: {server_url}")
    print(f"  STT: {stt_backend}")
    print(f"  TTS: {tts_backend} ({tts_voice})")
    if device_name:
        print(f"  Device: {device_name}")
    elif device_index is not None:
        print(f"  Device index: {device_index}")
    print()
    print("Press 'm' to toggle mute, Ctrl+C to exit")
    print()

    # Run the voice client
    try:
        from silica.voice.client import run_voice_client

        asyncio.run(
            run_voice_client(
                server_url=server_url,
                transcriber_backend=stt_backend,
                transcriber_kwargs=transcriber_kwargs,
                speaker_backend=tts_backend,
                speaker_kwargs=speaker_kwargs,
                **settings_kwargs,
            )
        )
    except KeyboardInterrupt:
        print("\nVoice interface stopped.")
    except Exception as e:
        logger.error(f"Voice interface error: {e}")
        return 1


@voice_app.command
def devices():
    """List available audio input devices."""
    try:
        from silica.voice import check_voice_available

        check_voice_available()
    except ImportError as e:
        print(f"Error: {e}")
        return 1

    from silica.voice.listener import list_microphones

    print("\nAvailable audio input devices:")
    print("-" * 50)
    for idx, info in list_microphones():
        name = info.get("name", "Unknown")
        channels = info.get("maxInputChannels", 0)
        rate = info.get("defaultSampleRate", 0)
        print(f"  [{idx}] {name}")
        print(f"       Channels: {channels}, Rate: {rate}")


@voice_app.command
def voices():
    """List available TTS voices for Edge TTS."""
    import asyncio

    async def list_voices():
        try:
            import edge_tts

            voices = await edge_tts.list_voices()

            print("\nAvailable Edge TTS voices:")
            print("-" * 60)

            # Group by locale
            by_locale = {}
            for v in voices:
                locale = v["Locale"]
                if locale not in by_locale:
                    by_locale[locale] = []
                by_locale[locale].append(v)

            for locale in sorted(by_locale.keys()):
                print(f"\n{locale}:")
                for v in by_locale[locale]:
                    name = v["ShortName"]
                    gender = v["Gender"]
                    print(f"  {name} ({gender})")

        except ImportError:
            print("Error: edge-tts not installed")
            print("Install with: pip install edge-tts")

    asyncio.run(list_voices())
