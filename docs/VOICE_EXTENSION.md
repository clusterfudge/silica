# Silica Voice Extension

Real-time voice interaction for Silica AI assistants with streaming STT/TTS.

## Installation

```bash
pip install silica[voice]
```

### System Dependencies

| Platform | Command |
|----------|---------|
| macOS | `brew install portaudio` |
| Ubuntu/Debian | `sudo apt install portaudio19-dev python3-pyaudio` |
| Fedora/RHEL | `sudo dnf install portaudio-devel` |
| Arch | `sudo pacman -S portaudio` |
| Windows | `pip install pipwin && pipwin install pyaudio` |
| Raspberry Pi | `sudo apt install portaudio19-dev libatlas-base-dev` |

## Quick Start

```bash
# Start server
silica serve

# Connect client (new terminal)
silica voice
```

## Configuration

### `silica serve` Options

| Option | Default | Description |
|--------|---------|-------------|
| `--host` | `127.0.0.1` | Bind address |
| `--port` | `8765` | WebSocket port |
| `--stt` | `remote_whisper` | STT backend |
| `--tts` | `edge` | TTS backend |
| `--model` | `base.en` | Whisper model |
| `--voice` | `en-US-GuyNeural` | TTS voice |
| `--rate` | `+0%` | Speech rate |
| `--vad-threshold` | `0.5` | Voice activity threshold |
| `--silence-duration` | `0.8` | Seconds to end utterance |
| `--sample-rate` | `16000` | Audio sample rate |

### `silica voice` Options

| Option | Default | Description |
|--------|---------|-------------|
| `--server` | `ws://localhost:8765` | Server URL |
| `--input-device` | auto | Mic device index |
| `--output-device` | auto | Speaker device index |
| `--list-devices` | - | List audio devices |
| `--push-to-talk` | false | PTT mode (spacebar) |

## Environment Variables

```bash
# API Keys
OPENAI_API_KEY=sk-...
DEEPGRAM_API_KEY=...
GOOGLE_APPLICATION_CREDENTIALS=/path/to/creds.json

# Configuration
SILICA_VOICE_HOST=0.0.0.0
SILICA_VOICE_PORT=8765
SILICA_STT_BACKEND=openai
SILICA_TTS_BACKEND=edge
SILICA_TTS_VOICE=en-US-AriaNeural
WHISPER_SERVER_URL=http://localhost:9000/transcribe
SILICA_VAD_THRESHOLD=0.5
```

## STT Backends

| Backend | Config | Requirements |
|---------|--------|--------------|
| `remote_whisper` | `--stt remote_whisper` | `WHISPER_SERVER_URL` |
| `openai` | `--stt openai` | `OPENAI_API_KEY` |
| `deepgram` | `--stt deepgram` | `DEEPGRAM_API_KEY` |
| `google` | `--stt google` | `GOOGLE_APPLICATION_CREDENTIALS` |

## TTS Backends

| Backend | Config | Notes |
|---------|--------|-------|
| `edge` | `--tts edge --voice en-US-GuyNeural` | Free, no API key |
| `remote` | `--tts remote` | Custom server via `SILICA_TTS_URL` |

Voices: `en-US-GuyNeural`, `en-US-AriaNeural`, `en-GB-SoniaNeural`

## Audio Device Selection

```bash
silica voice --list-devices
# Input Devices:
#   0: Built-in Microphone
#   2: USB Audio Device

silica voice --input-device 2 --output-device 3
```

## WebSocket Protocol

### Client → Server

| Type | Payload | Description |
|------|---------|-------------|
| `session.start` | `{config: {...}}` | Start session |
| `audio.chunk` | `{data: "base64"}` | Audio (PCM16 16kHz) |
| `audio.commit` | - | End utterance manually |
| `response.cancel` | - | Interrupt response |
| `text.input` | `{text: "..."}` | Text input |
| `session.end` | - | End session |

### Server → Client

| Type | Payload | Description |
|------|---------|-------------|
| `session.started` | `{session_id}` | Session confirmed |
| `transcription.partial` | `{text}` | Interim transcript |
| `transcription.final` | `{text}` | Final transcript |
| `response.delta` | `{text}` | Streaming response |
| `response.done` | `{text}` | Complete response |
| `audio.delta` | `{data, format}` | TTS audio chunk |
| `audio.done` | - | TTS complete |
| `vad.speech_start` | - | Voice detected |
| `vad.speech_end` | - | Silence detected |
| `error` | `{code, message}` | Error occurred |

## Architecture

```
+-----------------------------------------------------------+
|                    Voice Client                           |
|  +---------+   +-----+   +---------+   +-----------+      |
|  |   Mic   |-->| VAD |-->| Encoder |-->| WebSocket |      |
|  +---------+   +-----+   +---------+   |  Client   |      |
|  +---------+   +---------------------+ |           |      |
|  | Speaker |<--| Audio Decoder/Buffer|<|           |      |
|  +---------+   +---------------------+ +-----+-----+      |
+----------------------------------------------|------------+
                                               | WSS
+----------------------------------------------|------------+
|                   Voice Server               |            |
|  +-------------------------------------------v---------+  |
|  |               WebSocket Handler                     |  |
|  +---------+---------------+---------------+-----------+  |
|            |               |               |              |
|  +---------v-----+ +-------v-------+ +-----v-------+      |
|  |  STT Engine   | | Silica Agent  | | TTS Engine  |      |
|  |(Whisper/DG/OAI| |   (Core)      | |(Edge/Remote)|      |
|  +---------------+ +---------------+ +-------------+      |
+-----------------------------------------------------------+
```

## Raspberry Pi Deployment

### Requirements
- Pi 4 (4GB+) or Pi 5
- USB microphone or ReSpeaker HAT
- Speaker (3.5mm/USB)

### Setup
```bash
sudo apt install -y portaudio19-dev libatlas-base-dev
pip install silica[voice]

# Test audio
arecord -d 3 test.wav && aplay test.wav
```

### Systemd Service
```ini
# /etc/systemd/system/silica-voice.service
[Unit]
Description=Silica Voice Server
After=network.target

[Service]
User=pi
Environment="OPENAI_API_KEY=sk-..."
ExecStart=/home/pi/.local/bin/silica serve --host 0.0.0.0
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now silica-voice
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `No module named 'pyaudio'` | Install portaudio first, then `pip install pyaudio` |
| `Invalid input device` | Use `--list-devices` and specify `--input-device N` |
| `Connection refused` | Ensure server running: `silica serve` |
| High latency | Use `--stt deepgram` |
| VAD too sensitive | Increase `--vad-threshold 0.7` |
| Cuts off speech | Increase `--silence-duration 1.2` |

Debug: `silica serve --log-level DEBUG`

## Python API

```python
from silica.voice import VoiceServer, VoiceClient, STTBackend, TTSBackend

# Server
server = VoiceServer(
    host="0.0.0.0", port=8765,
    stt=STTBackend.OPENAI, tts=TTSBackend.EDGE,
    vad_threshold=0.5
)
await server.start()

# Client
client = VoiceClient(
    server_url="ws://localhost:8765",
    on_transcription=lambda t: print(f"You: {t}"),
    on_response=lambda r: print(f"AI: {r}"),
)
await client.connect()
await client.start_listening()

# Direct STT/TTS
from silica.voice.stt import create_stt_engine
from silica.voice.tts import create_tts_engine

stt = create_stt_engine("openai")
transcript = await stt.transcribe(audio_bytes)

tts = create_tts_engine("edge", voice="en-US-GuyNeural")
async for chunk in tts.synthesize_stream("Hello"):
    play_audio(chunk)
```

### Event Hooks
```python
@server.on("transcription")
async def handle(session, text, is_final):
    if is_final:
        print(f"Final: {text}")
```