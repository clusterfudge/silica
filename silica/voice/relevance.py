"""
Relevance filtering for voice input.

This module provides a fast, lightweight relevance check using Claude Haiku
to determine if ambient speech is directed at the assistant (without requiring
a wake word).
"""

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

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
        self, text: str, context: Optional[str] = None
    ) -> RelevanceResult:
        """
        Check if transcribed text is relevant to the assistant.

        Args:
            text: Transcribed text to check
            context: Optional recent conversation context

        Returns:
            RelevanceResult indicating if the text is relevant
        """
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
        self, text: str, context: Optional[str] = None
    ) -> RelevanceResult:
        """
        Async version of check_relevance.

        Args:
            text: Transcribed text to check
            context: Optional recent conversation context

        Returns:
            RelevanceResult indicating if the text is relevant
        """
        import asyncio

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: self.check_relevance(text, context)
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
