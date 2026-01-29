"""Tests for the /repair-history command."""

from unittest.mock import Mock
from silica.developer.context import AgentContext
from silica.developer.toolbox import Toolbox
from silica.developer.sandbox import Sandbox, SandboxMode


def create_mock_context():
    """Create a mock agent context for testing."""
    context = Mock(spec=AgentContext)

    context.session_id = "test-session-123"
    context.parent_session_id = None
    context.history_base_dir = None

    context.model_spec = {
        "title": "claude-3-5-sonnet-20241022",
        "max_tokens": 8192,
        "context_window": 200000,
        "pricing": {"input": 3.0, "output": 15.0},
        "cache_pricing": {"read": 0.3, "write": 3.75},
    }

    context.thinking_mode = "off"
    context.chat_history = []
    context.usage = []
    context.usage_summary.return_value = {
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_thinking_tokens": 0,
        "total_cost": 0.0,
        "thinking_cost": 0.0,
        "cached_tokens": 0,
        "model_breakdown": {},
    }

    context.sandbox = Mock(spec=Sandbox)
    context.sandbox.mode = SandboxMode.ALLOW_ALL
    context.user_interface = Mock()

    return context


class TestRepairHistoryCommand:
    """Tests for the /repair-history command."""

    def test_no_oversized_results(self):
        """Should report no issues when history is clean."""
        context = create_mock_context()
        context.chat_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

        toolbox = Toolbox(context)
        result = toolbox._repair_history(
            user_interface=context.user_interface,
            sandbox=context.sandbox,
            user_input="",
        )

        assert "No oversized tool results found" in result

    def test_detects_oversized_tool_result(self):
        """Should detect oversized tool results."""
        context = create_mock_context()

        # Create an oversized tool result (500K chars ~= 166K tokens)
        large_content = "x" * 500000
        context.chat_history = [
            {"role": "user", "content": "Run a command"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool_123",
                        "name": "shell_execute",
                        "input": {"command": "cat bigfile.txt"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_123",
                        "content": large_content,
                    }
                ],
            },
        ]

        toolbox = Toolbox(context)
        toolbox._repair_history(
            user_interface=context.user_interface,
            sandbox=context.sandbox,
            user_input="",
        )

        # Should have called handle_system_message with fix report
        context.user_interface.handle_system_message.assert_called()
        call_args = context.user_interface.handle_system_message.call_args[0][0]
        assert "Fixed" in call_args or "oversized" in call_args

    def test_dry_run_mode(self):
        """Dry run should not modify history."""
        context = create_mock_context()

        large_content = "x" * 500000
        original_content = large_content  # Save original
        context.chat_history = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_123",
                        "content": large_content,
                    }
                ],
            },
        ]

        toolbox = Toolbox(context)
        toolbox._repair_history(
            user_interface=context.user_interface,
            sandbox=context.sandbox,
            user_input="--dry-run",
        )

        # Content should be unchanged
        assert context.chat_history[0]["content"][0]["content"] == original_content

        # Should have reported findings
        context.user_interface.handle_system_message.assert_called()
        call_args = context.user_interface.handle_system_message.call_args[0][0]
        assert "Dry run" in call_args

    def test_custom_token_limit(self):
        """Should respect custom token limit."""
        context = create_mock_context()

        # Create content that's ~33K tokens (100K chars)
        medium_content = "x" * 100000
        context.chat_history = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_123",
                        "content": medium_content,
                    }
                ],
            },
        ]

        toolbox = Toolbox(context)

        # With default limit (50K), this should be fine
        result = toolbox._repair_history(
            user_interface=context.user_interface,
            sandbox=context.sandbox,
            user_input="",
        )
        assert "No oversized" in result

        # With 10K limit, it should be detected
        context.user_interface.reset_mock()
        toolbox._repair_history(
            user_interface=context.user_interface,
            sandbox=context.sandbox,
            user_input="10000",
        )
        context.user_interface.handle_system_message.assert_called()

    def test_fixes_oversized_result(self):
        """Should replace oversized content with truncation message."""
        context = create_mock_context()

        large_content = "x" * 500000
        context.chat_history = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool_123",
                        "content": large_content,
                    }
                ],
            },
        ]

        toolbox = Toolbox(context)
        toolbox._repair_history(
            user_interface=context.user_interface,
            sandbox=context.sandbox,
            user_input="",
        )

        # Content should be replaced with truncation message
        new_content = context.chat_history[0]["content"][0]["content"]
        assert "TOOL RESULT TOO LARGE" in new_content
        assert context.chat_history[0]["content"][0].get("is_error") is True

        # Should have called flush to save
        context.flush.assert_called()

    def test_invalid_token_limit(self):
        """Should handle invalid token limit argument."""
        context = create_mock_context()
        context.chat_history = []

        toolbox = Toolbox(context)
        result = toolbox._repair_history(
            user_interface=context.user_interface,
            sandbox=context.sandbox,
            user_input="not_a_number",
        )

        assert "Error" in result
        assert "Invalid token limit" in result

    def test_preserves_tool_use_id(self):
        """Should preserve tool_use_id when fixing."""
        context = create_mock_context()

        context.chat_history = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "unique_id_456",
                        "content": "x" * 500000,
                    }
                ],
            },
        ]

        toolbox = Toolbox(context)
        toolbox._repair_history(
            user_interface=context.user_interface,
            sandbox=context.sandbox,
            user_input="",
        )

        # tool_use_id should be preserved
        assert context.chat_history[0]["content"][0]["tool_use_id"] == "unique_id_456"

    def test_command_registered(self):
        """Test that repair-history command is registered."""
        context = create_mock_context()
        toolbox = Toolbox(context)

        assert "repair-history" in toolbox.local
        assert (
            "oversized" in toolbox.local["repair-history"]["docstring"].lower()
            or "truncat" in toolbox.local["repair-history"]["docstring"].lower()
        )
