"""
Silica Voice Extension.

This module provides voice I/O capabilities for silica, enabling
speech-to-text and text-to-speech interaction with the agent.

Install with: pip install silica[voice]
"""

from silica.voice.relevance import (
    RelevanceFilter,
    RelevanceResult,
    VoiceCommand,
    create_relevance_filter,
    detect_voice_command,
    is_mute_command,
    is_unmute_command,
)

# Check if voice dependencies are available
try:
    pass

    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False


def check_voice_available():
    """Check if voice dependencies are installed."""
    if not VOICE_AVAILABLE:
        raise ImportError(
            "Voice dependencies not installed. "
            "Install with: pip install silica[voice]"
        )
    return True


__all__ = [
    "VOICE_AVAILABLE",
    "check_voice_available",
    "RelevanceFilter",
    "RelevanceResult",
    "VoiceCommand",
    "create_relevance_filter",
    "detect_voice_command",
    "is_mute_command",
    "is_unmute_command",
]
