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
        local_metadata: dict | None = None,
        remote_metadata: dict | None = None,
    ) -> bytes:
        """Resolve conflict by using LLM to merge content.

        Args:
            path: File path (for context)
            local_content: Local file content
            remote_content: Remote file content
            local_metadata: Optional metadata (mtime, etc.) for local
            remote_metadata: Optional metadata (last_modified, version, etc.) for remote

        Returns:
            Merged content as bytes

        Raises:
            ConflictResolutionError: If merge fails
        """
        try:
            # Decode content (assume UTF-8, replace errors)
            local_text = local_content.decode("utf-8", errors="replace")
            remote_text = remote_content.decode("utf-8", errors="replace")

            # Build merge prompt with metadata
            prompt = self._build_merge_prompt(
                path, local_text, remote_text, local_metadata, remote_metadata
            )

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

    def _build_merge_prompt(
        self,
        path: str,
        local_text: str,
        remote_text: str,
        local_metadata: dict | None,
        remote_metadata: dict | None,
    ) -> str:
        """Build prompt for LLM merge.

        Args:
            path: File path (for context)
            local_text: Local file content
            remote_text: Remote file content
            local_metadata: Optional local file metadata
            remote_metadata: Optional remote file metadata

        Returns:
            Formatted prompt string
        """
        # Build metadata context
        metadata_context = ""
        if local_metadata or remote_metadata:
            metadata_context = "\n\n=== FILE METADATA ===\n"
            if local_metadata:
                metadata_context += f"Local: {local_metadata}\n"
            if remote_metadata:
                metadata_context += f"Remote: {remote_metadata}\n"

        return f"""You are tasked with helping keep an agent's memory files up to date. There is a conflict between two versions of the same file.

Please read both versions and logically merge them together.

Your goal is to preserve all important information from both versions while resolving any contradictions intelligently.

File: {path}{metadata_context}

=== LOCAL VERSION ===
{local_text}

=== REMOTE VERSION ===
{remote_text}

=== INSTRUCTIONS ===
- Use context clues in the content to infer which version came first (look for dates, timestamps, completion markers like "in-progress" vs "complete", etc.)
- Use file metadata timestamps if provided to determine temporal ordering
- Preserve all important information from both versions
- When information conflicts, prefer the more recent version based on your analysis
- Maintain the file structure and format consistent with the file type
- If this is a markdown memory file, maintain proper markdown formatting
- If this is a JSON file, ensure valid JSON output
- Remove any duplicate information
- Output ONLY the merged file content, with no additional commentary or explanation

Merged content:"""
