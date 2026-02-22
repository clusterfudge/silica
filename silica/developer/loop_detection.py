"""Loop detection for agent conversations.

Detects when the agent gets stuck in a repetitive loop, making the same
tool calls with identical inputs and getting identical outputs.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LoopDetector:
    """Detects repetitive loops in agent tool usage.

    Tracks recent (tool_name, tool_input, tool_result) tuples and detects
    when the same combination appears consecutively.
    """

    threshold: int = 3  # Number of consecutive identical calls to trigger detection
    _recent_calls: list[dict[str, Any]] = field(default_factory=list)
    _consecutive_count: int = 0
    _last_hash: str | None = None

    def _hash_call(self, tool_name: str, tool_input: dict, tool_result: str) -> str:
        """Create a hash of a tool call for comparison."""
        # Normalize the input and result for comparison
        normalized = {
            "name": tool_name,
            "input": json.dumps(tool_input, sort_keys=True),
            "result": tool_result,
        }
        return hashlib.sha256(
            json.dumps(normalized, sort_keys=True).encode()
        ).hexdigest()

    def record_call(self, tool_name: str, tool_input: dict, tool_result: str) -> bool:
        """Record a tool call and check for loops.

        Args:
            tool_name: Name of the tool that was called
            tool_input: Input arguments to the tool
            tool_result: Output from the tool (as string)

        Returns:
            True if a loop has been detected (threshold reached), False otherwise
        """
        call_hash = self._hash_call(tool_name, tool_input, tool_result)

        if call_hash == self._last_hash:
            self._consecutive_count += 1
        else:
            self._consecutive_count = 1
            self._last_hash = call_hash

        # Store the call details for potential debugging
        self._recent_calls.append(
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_result_preview": tool_result[:200]
                if len(tool_result) > 200
                else tool_result,
                "hash": call_hash,
                "consecutive": self._consecutive_count,
            }
        )

        # Keep only the last 10 calls
        if len(self._recent_calls) > 10:
            self._recent_calls.pop(0)

        return self._consecutive_count >= self.threshold

    def get_loop_info(self) -> dict[str, Any] | None:
        """Get information about the current loop if one is detected.

        Returns:
            Dict with loop info if threshold reached, None otherwise
        """
        if self._consecutive_count < self.threshold:
            return None

        if not self._recent_calls:
            return None

        last_call = self._recent_calls[-1]
        return {
            "consecutive_count": self._consecutive_count,
            "tool_name": last_call["tool_name"],
            "tool_input": last_call["tool_input"],
            "tool_result_preview": last_call["tool_result_preview"],
        }

    def reset(self) -> None:
        """Reset the loop detector state."""
        self._recent_calls.clear()
        self._consecutive_count = 0
        self._last_hash = None

    def get_intervention_message(self) -> str:
        """Get a message to inject when a loop is detected.

        Returns:
            A message that will help the model break out of the loop.
        """
        info = self.get_loop_info()
        if not info:
            return ""

        return f"""⚠️ **LOOP DETECTED**: You have made the same tool call ({info["tool_name"]}) with identical inputs {info["consecutive_count"]} times in a row, and received the same output each time.

This indicates you may be stuck in a repetitive pattern. The output is not going to change unless you take a different action.

**To break out of this loop, you should:**
1. Analyze WHY the output isn't changing - what's blocking progress?
2. Try a DIFFERENT approach or tool
3. If you're waiting for something to change, explicitly check what you're waiting for
4. If you're stuck, ask the user for guidance

**Do NOT repeat the same action again.** Take a different approach now."""


# System prompt addition to help prevent loops
LOOP_PREVENTION_SYSTEM_PROMPT = """
## Tool Use Repetition

When making tool calls, avoid repeating the exact same call multiple times expecting different results. If you need to:

1. **Poll or wait for changes**: Add a descriptive comment in your reasoning explaining what you're waiting for, and consider using a different approach (e.g., checking specific conditions rather than re-running the same command)

2. **Retry after making changes**: Ensure you've actually made changes before re-running a test or check

3. **Verify state**: If checking the same thing multiple times, vary your approach (e.g., check a specific file, run a specific test, rather than running the full test suite repeatedly)

If you find yourself about to make the same tool call with the same inputs as your previous call, STOP and reconsider:
- Did you make any changes since the last call?
- Are you expecting a different result? Why?
- Is there a more targeted check you could do instead?
"""
