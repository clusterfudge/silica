"""LLM-based conflict resolution for memory sync."""

import logging
from anthropic import Anthropic

from .conflict_resolver import ConflictResolver, ConflictResolutionError

logger = logging.getLogger(__name__)


class LLMConflictResolver(ConflictResolver):
    """Resolve conflicts using Claude Haiku LLM."""

    def __init__(self, client: Anthropic | None = None):
        """Initialize LLM conflict resolver.

        Args:
            client: Anthropic client (will create one if not provided)
        """
        self.client = client or Anthropic()
        self.model = "claude-3-5-haiku-20241022"

    def resolve_conflict(
        self,
        path: str,
        local_content: bytes,
        remote_content: bytes,
    ) -> bytes:
        """Resolve conflict by using LLM to merge content.

        Args:
            path: File path (for context)
            local_content: Local file content (written first)
            remote_content: Remote file content (incoming update)

        Returns:
            Merged content as bytes

        Raises:
            ConflictResolutionError: If merge fails
        """
        try:
            # Decode content (assume UTF-8, replace errors)
            local_text = local_content.decode("utf-8", errors="replace")
            remote_text = remote_content.decode("utf-8", errors="replace")

            # Build merge prompt
            prompt = self._build_merge_prompt(path, local_text, remote_text)

            logger.debug(f"Resolving conflict for {path} using LLM")

            # Call LLM
            response = self.client.messages.create(
                model=self.model,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract merged content
            merged_text = response.content[0].text

            logger.info(f"Successfully resolved conflict for {path}")

            return merged_text.encode("utf-8")

        except Exception as e:
            logger.error(f"Failed to resolve conflict for {path}: {e}")
            raise ConflictResolutionError(f"LLM merge failed for {path}: {e}") from e

    def _build_merge_prompt(self, path: str, local_text: str, remote_text: str) -> str:
        """Build prompt for LLM merge.

        Args:
            path: File path (for context)
            local_text: Local file content
            remote_text: Remote file content

        Returns:
            Formatted prompt string
        """
        return f"""You are tasked with helping keep an agent's memory files up to date. There is a conflict between two versions of the same file.

Please read both versions and logically merge them together. The local version was written first, and the remote version is the incoming update that has drifted.

Your goal is to preserve all important information from both versions while resolving any contradictions intelligently. If information conflicts, prefer the remote version as it represents the most recent state.

File: {path}

=== LOCAL VERSION (written first) ===
{local_text}

=== REMOTE VERSION (incoming update) ===
{remote_text}

=== INSTRUCTIONS ===
- Preserve all important information from both versions
- When information conflicts, prefer the remote version (more recent)
- Maintain the file structure and format consistent with the file type
- If this is a markdown memory file, maintain proper markdown formatting
- If this is a JSON file, ensure valid JSON output
- Remove any duplicate information
- Output ONLY the merged file content, with no additional commentary or explanation

Merged content:"""
