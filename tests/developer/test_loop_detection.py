"""Tests for loop detection functionality."""

from silica.developer.loop_detection import (
    LoopDetector,
    LOOP_PREVENTION_SYSTEM_PROMPT,
)


class TestLoopDetector:
    """Tests for the LoopDetector class."""

    def test_no_loop_on_different_calls(self):
        """Different tool calls should not trigger loop detection."""
        detector = LoopDetector(threshold=3)

        # Make different calls
        assert not detector.record_call(
            "shell_execute", {"command": "ls"}, "file1.py\nfile2.py"
        )
        assert not detector.record_call(
            "shell_execute", {"command": "cat file1.py"}, "content"
        )
        assert not detector.record_call("read_file", {"path": "file1.py"}, "content")

        assert detector.get_loop_info() is None

    def test_no_loop_below_threshold(self):
        """Should not trigger loop until threshold is reached."""
        detector = LoopDetector(threshold=3)

        # Make 2 identical calls (below threshold of 3)
        assert not detector.record_call("shell_execute", {"command": "test"}, "output")
        assert not detector.record_call("shell_execute", {"command": "test"}, "output")

        assert detector.get_loop_info() is None

    def test_loop_detected_at_threshold(self):
        """Should trigger loop exactly at threshold."""
        detector = LoopDetector(threshold=3)

        # First call
        assert not detector.record_call(
            "shell_execute", {"command": "run_tests.sh"}, "FAIL: 10 tests"
        )

        # Second identical call
        assert not detector.record_call(
            "shell_execute", {"command": "run_tests.sh"}, "FAIL: 10 tests"
        )

        # Third identical call - should trigger
        assert detector.record_call(
            "shell_execute", {"command": "run_tests.sh"}, "FAIL: 10 tests"
        )

        info = detector.get_loop_info()
        assert info is not None
        assert info["consecutive_count"] == 3
        assert info["tool_name"] == "shell_execute"
        assert info["tool_input"] == {"command": "run_tests.sh"}

    def test_loop_continues_after_threshold(self):
        """Should continue detecting loops after threshold is passed."""
        detector = LoopDetector(threshold=3)

        for i in range(5):
            result = detector.record_call(
                "shell_execute", {"command": "test"}, "output"
            )
            if i < 2:
                assert not result
            else:
                assert result  # Triggers at 3, 4, 5

        info = detector.get_loop_info()
        assert info["consecutive_count"] == 5

    def test_loop_breaks_on_different_input(self):
        """Loop should break when input changes."""
        detector = LoopDetector(threshold=3)

        # Build up to threshold
        detector.record_call("shell_execute", {"command": "test"}, "output")
        detector.record_call("shell_execute", {"command": "test"}, "output")

        # Different input breaks the chain
        assert not detector.record_call(
            "shell_execute", {"command": "different"}, "output"
        )

        assert detector.get_loop_info() is None

    def test_loop_breaks_on_different_output(self):
        """Loop should break when output changes."""
        detector = LoopDetector(threshold=3)

        # Build up to threshold
        detector.record_call("shell_execute", {"command": "test"}, "output1")
        detector.record_call("shell_execute", {"command": "test"}, "output1")

        # Different output breaks the chain
        assert not detector.record_call("shell_execute", {"command": "test"}, "output2")

        assert detector.get_loop_info() is None

    def test_loop_breaks_on_different_tool(self):
        """Loop should break when tool name changes."""
        detector = LoopDetector(threshold=3)

        # Build up to threshold
        detector.record_call("shell_execute", {"command": "test"}, "output")
        detector.record_call("shell_execute", {"command": "test"}, "output")

        # Different tool breaks the chain
        assert not detector.record_call("read_file", {"command": "test"}, "output")

        assert detector.get_loop_info() is None

    def test_reset_clears_state(self):
        """Reset should clear all state."""
        detector = LoopDetector(threshold=3)

        # Build up state
        detector.record_call("shell_execute", {"command": "test"}, "output")
        detector.record_call("shell_execute", {"command": "test"}, "output")
        detector.record_call("shell_execute", {"command": "test"}, "output")

        assert detector.get_loop_info() is not None

        # Reset
        detector.reset()

        assert detector.get_loop_info() is None
        assert detector._consecutive_count == 0
        assert detector._last_hash is None
        assert len(detector._recent_calls) == 0

    def test_intervention_message_format(self):
        """Intervention message should contain useful information."""
        detector = LoopDetector(threshold=3)

        # Trigger a loop
        for _ in range(3):
            detector.record_call("shell_execute", {"command": "run_tests.sh"}, "FAIL")

        message = detector.get_intervention_message()

        assert "LOOP DETECTED" in message
        assert "shell_execute" in message
        assert "3 times" in message
        assert "different approach" in message.lower() or "DIFFERENT" in message

    def test_intervention_message_empty_when_no_loop(self):
        """Intervention message should be empty when no loop detected."""
        detector = LoopDetector(threshold=3)

        detector.record_call("shell_execute", {"command": "test"}, "output")

        assert detector.get_intervention_message() == ""

    def test_custom_threshold(self):
        """Should respect custom threshold."""
        detector = LoopDetector(threshold=5)

        # 4 calls should not trigger
        for _ in range(4):
            assert not detector.record_call(
                "shell_execute", {"command": "test"}, "output"
            )

        # 5th call should trigger
        assert detector.record_call("shell_execute", {"command": "test"}, "output")

    def test_complex_input_comparison(self):
        """Should handle complex nested inputs."""
        detector = LoopDetector(threshold=3)

        complex_input = {
            "command": "test",
            "options": {"verbose": True, "timeout": 30},
            "env": {"PATH": "/usr/bin"},
        }

        for _ in range(3):
            result = detector.record_call("shell_execute", complex_input, "output")

        assert result  # Should detect loop

    def test_input_order_independent(self):
        """Input dict order should not affect comparison."""
        detector = LoopDetector(threshold=3)

        # Same keys, different order
        input1 = {"a": 1, "b": 2}
        input2 = {"b": 2, "a": 1}

        detector.record_call("tool", input1, "output")
        detector.record_call("tool", input2, "output")
        detector.record_call("tool", input1, "output")

        # Should detect as loop since inputs are equivalent
        assert detector._consecutive_count == 3

    def test_recent_calls_limited(self):
        """Should only keep last 10 calls."""
        detector = LoopDetector(threshold=3)

        # Make 15 different calls
        for i in range(15):
            detector.record_call("tool", {"n": i}, f"output{i}")

        assert len(detector._recent_calls) == 10


class TestLoopPreventionSystemPrompt:
    """Tests for the system prompt content."""

    def test_system_prompt_not_empty(self):
        """System prompt should not be empty."""
        assert LOOP_PREVENTION_SYSTEM_PROMPT
        assert len(LOOP_PREVENTION_SYSTEM_PROMPT) > 100

    def test_system_prompt_contains_guidance(self):
        """System prompt should contain useful guidance."""
        prompt = LOOP_PREVENTION_SYSTEM_PROMPT.lower()

        assert "repeat" in prompt
        assert "different" in prompt or "vary" in prompt
        assert "change" in prompt


class TestLoopDetectorRealWorldScenario:
    """Test with real-world-like data from the session."""

    def test_test_runner_loop(self):
        """Simulate the actual loop from session 53999f60."""
        detector = LoopDetector(threshold=3)

        tool_name = "shell_execute"
        tool_input = {
            "command": "cd /path/to/project && bash run_tests.sh 2>&1 | grep -E '(FAIL|Results)'",
            "timeout": 120,
        }
        tool_output = """Exit code: 0
STDOUT:
FAIL (run): 00051 (exit=1)
FAIL (run): 00124 (exit=214)
FAIL (compile): 00129
FAIL (run): 00130 (exit=139)
FAIL (compile): 00141
FAIL (run): 00143 (exit=1)
FAIL (compile): 00145
FAIL (run): 00151 (exit=139)
FAIL (compile): 00152
FAIL (compile): 00209
Results: 139 passed, 10 failed"""

        # First two calls - no detection
        assert not detector.record_call(tool_name, tool_input, tool_output)
        assert not detector.record_call(tool_name, tool_input, tool_output)

        # Third call - should detect
        assert detector.record_call(tool_name, tool_input, tool_output)

        info = detector.get_loop_info()
        assert info["tool_name"] == "shell_execute"
        assert info["consecutive_count"] == 3

        # Verify intervention message is generated
        message = detector.get_intervention_message()
        assert "LOOP DETECTED" in message
        assert "shell_execute" in message
