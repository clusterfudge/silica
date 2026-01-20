"""
Relevance filtering for voice input.

This module provides a fast, lightweight relevance check using Claude Haiku
to determine if ambient speech is directed at the assistant (without requiring
a wake word).

Also provides voice command detection for mute/unmute control on headless devices.
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

logger = logging.getLogger(__name__)


class VoiceCommand(Enum):
    """Voice commands that can be detected."""

    NONE = auto()
    MUTE = auto()
    UNMUTE = auto()
    STOP = auto()  # Stop speaking / interrupt
    CANCEL = auto()  # Cancel current operation


# Patterns for voice command detection (checked before relevance filter)
# These are checked case-insensitively
# Note: UNMUTE patterns are checked before MUTE to handle "unmute" containing "mute"
VOICE_COMMAND_PATTERNS = {
    # UNMUTE must come before MUTE in iteration order
    VoiceCommand.UNMUTE: [
        r"\bunmute\b",
        r"\b(wake up|start listening|i'm back|resume)\b",
        r"\b(silica|assistant|hey).*(unmute|wake up|start listening)\b",
    ],
    VoiceCommand.MUTE: [
        r"(?<![un])mute\b",  # "mute" but not "unmute"
        r"\b(go to sleep|sleep mode|stop listening|be quiet|shut up)\b",
        r"\b(silica|assistant|hey).*(go to sleep|sleep|be quiet)\b",
    ],
    VoiceCommand.STOP: [
        r"\b(stop|enough|that's enough|ok stop|okay stop)\b",
        r"\b(silica|assistant).*(stop|enough)\b",
    ],
    VoiceCommand.CANCEL: [
        r"\b(cancel|never\s*mind|nevermind|forget it|abort)\b",
    ],
}

# Compile patterns for efficiency
_COMPILED_PATTERNS = {
    cmd: [re.compile(p, re.IGNORECASE) for p in patterns]
    for cmd, patterns in VOICE_COMMAND_PATTERNS.items()
}


RELEVANCE_SYSTEM_PROMPT = """You are a relevance filter for a voice assistant. Your job is to determine whether a transcribed utterance is directed at the assistant or is just ambient speech/conversation not meant for the assistant.

Consider an utterance RELEVANT if it:
- Is a direct question or request
- Asks for information, help, or action
- References "you" in a way that addresses an assistant
- Is a command or instruction
- Continues an ongoing conversation with the assistant

Consider an utterance NOT RELEVANT if it:
- Is clearly part of a conversation between other people
- Is self-talk or thinking aloud not seeking a response
- Is background noise, TV, radio, or other media
- Is a fragment or incomplete thought
- Is clearly not addressed to an AI assistant

Respond with ONLY "RELEVANT" or "NOT_RELEVANT" - nothing else."""


@dataclass
class RelevanceResult:
    """Result of a relevance check."""

    is_relevant: bool
    confidence: Optional[float] = None
    reason: Optional[str] = None
    voice_command: VoiceCommand = VoiceCommand.NONE


def detect_voice_command(text: str) -> VoiceCommand:
    """
    Detect voice commands in transcribed text.

    Checks for mute, unmute, stop, and cancel commands using
    pattern matching. This is fast and doesn't require an API call.

    Args:
        text: Transcribed text to check

    Returns:
        Detected VoiceCommand or VoiceCommand.NONE
    """
    if not text:
        return VoiceCommand.NONE

    text = text.strip()

    # Check each command type
    for command, patterns in _COMPILED_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(text):
                logger.info(f"Detected voice command: {command.name} in '{text}'")
                return command

    return VoiceCommand.NONE


def is_mute_command(text: str) -> bool:
    """Check if text contains a mute command."""
    return detect_voice_command(text) == VoiceCommand.MUTE


def is_unmute_command(text: str) -> bool:
    """Check if text contains an unmute command."""
    return detect_voice_command(text) == VoiceCommand.UNMUTE


class RelevanceFilter:
    """
    Filter to determine if transcribed speech is relevant to the assistant.

    Uses Claude Haiku for fast, cheap relevance classification.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-haiku-20240307",
        timeout: float = 5.0,
        enabled: bool = True,
    ):
        """
        Initialize the relevance filter.

        Args:
            api_key: Anthropic API key (defaults to ANTHROPIC_API_KEY env var)
            model: Model to use for relevance checking
            timeout: Request timeout in seconds
            enabled: Whether filtering is enabled (if False, all input is relevant)
        """
        import os

        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model
        self.timeout = timeout
        self.enabled = enabled

        if self.enabled and not self.api_key:
            logger.warning(
                "No Anthropic API key found, relevance filtering disabled. "
                "Set ANTHROPIC_API_KEY or pass api_key to enable."
            )
            self.enabled = False

        self._client = None

    def _get_client(self):
        """Lazily initialize the Anthropic client."""
        if self._client is None and self.enabled:
            import anthropic

            self._client = anthropic.Anthropic(
                api_key=self.api_key,
                timeout=self.timeout,
            )
        return self._client

    def check_relevance(
        self,
        text: str,
        context: Optional[str] = None,
        detect_commands: bool = True,
    ) -> RelevanceResult:
        """
        Check if transcribed text is relevant to the assistant.

        Also detects voice commands (mute, unmute, stop, cancel) which
        are always considered relevant for processing.

        Args:
            text: Transcribed text to check
            context: Optional recent conversation context
            detect_commands: Whether to detect voice commands (default True)

        Returns:
            RelevanceResult indicating if the text is relevant and any detected command
        """
        # First check for voice commands (always processed, even when muted)
        command = VoiceCommand.NONE
        if detect_commands:
            command = detect_voice_command(text)
            if command != VoiceCommand.NONE:
                return RelevanceResult(
                    is_relevant=True,
                    reason=f"Voice command: {command.name}",
                    voice_command=command,
                )

        if not self.enabled:
            return RelevanceResult(is_relevant=True, reason="Filtering disabled")

        if not text or not text.strip():
            return RelevanceResult(is_relevant=False, reason="Empty text")

        # Very short utterances are often noise
        if len(text.strip()) < 3:
            return RelevanceResult(is_relevant=False, reason="Too short")

        try:
            client = self._get_client()
            if client is None:
                return RelevanceResult(is_relevant=True, reason="No client available")

            # Build the message
            user_message = f'Utterance: "{text}"'
            if context:
                user_message = f"Recent context:\n{context}\n\n{user_message}"

            response = client.messages.create(
                model=self.model,
                max_tokens=10,
                system=RELEVANCE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            result_text = response.content[0].text.strip().upper()
            is_relevant = (
                "RELEVANT" in result_text and "NOT_RELEVANT" not in result_text
            )

            logger.info(f"Relevance check: '{text[:50]}...' -> {result_text}")

            return RelevanceResult(
                is_relevant=is_relevant,
                reason=result_text,
            )

        except Exception as e:
            logger.error(f"Relevance check failed: {e}")
            # On error, assume relevant to avoid dropping legitimate input
            return RelevanceResult(
                is_relevant=True,
                reason=f"Error: {e}",
            )

    async def check_relevance_async(
        self,
        text: str,
        context: Optional[str] = None,
        detect_commands: bool = True,
    ) -> RelevanceResult:
        """
        Async version of check_relevance.

        Args:
            text: Transcribed text to check
            context: Optional recent conversation context
            detect_commands: Whether to detect voice commands (default True)

        Returns:
            RelevanceResult indicating if the text is relevant
        """
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.check_relevance(text, context, detect_commands)
        )


def create_relevance_filter(
    enabled: bool = True,
    **kwargs,
) -> RelevanceFilter:
    """
    Create a relevance filter.

    Args:
        enabled: Whether filtering is enabled
        **kwargs: Additional arguments for RelevanceFilter

    Returns:
        RelevanceFilter instance
    """
    return RelevanceFilter(enabled=enabled, **kwargs)
