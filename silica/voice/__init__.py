"""
Silica Voice Extension.

This module provides voice I/O capabilities for silica, enabling
speech-to-text and text-to-speech interaction with the agent.

Install with: pip install silica[voice]
"""

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
