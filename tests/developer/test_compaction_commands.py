#!/usr/bin/env python3
"""
Tests for the /compact and /mc CLI commands.
"""

import unittest
from unittest import mock
import tempfile
import shutil
from pathlib import Path

from silica.developer.toolbox import Toolbox
from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.user_interface import UserInterface
from silica.developer.memory import MemoryManager


class MockAnthropicClient:
    """Mock for the Anthropic client."""

    def __init__(self, summary_text="Summary of the conversation"):
        """Initialize the mock client."""
        self.summary_text = summary_text
        self.messages = self.MessagesClient(self)

    class MessagesClient:
        """Mock for the messages client."""

        def __init__(self, parent):
            self.parent = parent

        def count_tokens(self, model, system=None, messages=None, tools=None):
            """Mock for the messages.count_tokens method."""
            # Calculate token count based on all components
            total_chars = 0

            if system:
                for block in system:
                    if isinstance(block, dict) and block.get("type") == "text":
                        total_chars += len(block.get("text", ""))

            if messages:
                for message in messages:
                    if isinstance(message, dict) and "content" in message:
                        content = message["content"]
                        if isinstance(content, str):
                            total_chars += len(content)
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and "text" in block:
                                    total_chars += len(block["text"])

            if tools:
                import json

                total_chars += len(json.dumps(tools))

            token_count = max(1, total_chars // 4)

            class TokenResponse:
                def __init__(self, count):
                    self.token_count = count

            return TokenResponse(token_count)

        def create(self, model, system, messages, max_tokens):
            """Mock for the messages.create method."""

            class ContentItem:
                def __init__(self, text):
                    self.text = text

            class MessageResponse:
                def __init__(self, content_text):
                    self.content = [ContentItem(content_text)]

            return MessageResponse(self.parent.summary_text)


class MockUserInterface(UserInterface):
    """Mock for the user interface."""

    def __init__(self):
        self.system_messages = []

    def handle_system_message(self, message, markdown=True, live=None):
        """Record system messages."""
        self.system_messages.append(message)

    def permission_callback(self, action, resource, sandbox_mode, action_arguments):
        """Always allow."""
        return True

    def permission_rendering_callback(self, action, resource, action_arguments):
        """Do nothing."""

    def bare(self, message, live=None):
        """Do nothing."""

    def display_token_count(self, *args, **kwargs):
        """Do nothing."""

    def display_welcome_message(self):
        """Do nothing."""

    async def get_user_input(self, prompt=""):
        """Return empty string."""
        return ""

    def handle_assistant_message(self, message, markdown=True):
        """Do nothing."""

    def handle_tool_result(self, name, result, markdown=True, live=None):
        """Do nothing."""

    def handle_tool_use(self, tool_name, tool_params):
        """Do nothing."""

    def handle_user_input(self, user_input):
        """Do nothing."""

    def status(self, message, spinner=None):
        """Return a context manager that does nothing."""

        class DummyContextManager:
            def __enter__(self):
                return None

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        return DummyContextManager()


class TestCompactionCommands(unittest.TestCase):
    """Tests for the /compact and /mc commands."""

    def setUp(self):
        """Set up test environment."""
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp()

        # Create sample messages
        self.sample_messages = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Message 3"},
            {"role": "assistant", "content": "Response 3"},
            {"role": "user", "content": "Message 4"},
            {"role": "assistant", "content": "Response 4"},
        ]

        # Create a model spec
        self.model_spec = {
            "title": "claude-opus-4-20250514",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
            "max_tokens": 8192,
            "context_window": 200000,
        }

    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.test_dir)

    @mock.patch("anthropic.Client")
    def test_compact_command(self, mock_client_class):
        """Test the /compact command."""
        # Setup mock
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

        # Create agent context
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-compact",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".hdev",
        )
        context._chat_history = self.sample_messages.copy()

        # Create toolbox
        toolbox = Toolbox(context)

        # Execute the compact command
        result = toolbox._compact(ui, sandbox, "")

        # Verify compaction occurred
        self.assertIn("compacted successfully", result)
        self.assertIn("Original:", result)
        self.assertIn("Compacted:", result)
        self.assertIn("Compression ratio:", result)

        # Verify context was modified
        self.assertNotEqual(len(context.chat_history), len(self.sample_messages))
        self.assertGreater(len(context.chat_history), 0)

    @mock.patch("anthropic.Client")
    def test_compact_command_insufficient_messages(self, mock_client_class):
        """Test /compact with too few messages."""
        # Setup mock
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

        # Create agent context with only 2 messages
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-compact-insufficient",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".hdev",
        )
        context._chat_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"},
        ]

        # Create toolbox
        toolbox = Toolbox(context)

        # Execute the compact command
        result = toolbox._compact(ui, sandbox, "")

        # Verify error was returned
        self.assertIn("Error", result)
        self.assertIn("Not enough conversation history", result)

    @mock.patch("anthropic.Client")
    def test_micro_compact_command_default(self, mock_client_class):
        """Test the /mc command with default (3 turns)."""
        # Setup mock client
        mock_client = MockAnthropicClient(summary_text="Summary of first 3 turns")
        mock_client_class.return_value = mock_client

        # Create agent context
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-mc",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".hdev",
        )
        context._chat_history = self.sample_messages.copy()

        # Create toolbox
        toolbox = Toolbox(context)

        # Execute the micro-compact command with default (3 turns)
        result = toolbox._micro_compact(ui, sandbox, "")

        # Verify micro-compaction occurred
        self.assertIn("Micro-compaction completed", result)
        self.assertIn("Compacted:", result)
        self.assertIn("3 turns", result)
        self.assertIn("5 messages", result)  # 3 turns = (3*2)-1 = 5 messages

        # Verify context was modified correctly
        # Should have: 1 summary message + 3 remaining messages (from original 8)
        # Original 8 - 5 compacted = 3 remaining + 1 summary = 4 total
        self.assertEqual(len(context.chat_history), 4)

        # Verify first message is the summary
        self.assertIn("Micro-Compacted Summary", context.chat_history[0]["content"])

    @mock.patch("anthropic.Client")
    def test_micro_compact_command_custom_turns(self, mock_client_class):
        """Test the /mc command with custom number of turns."""
        # Setup mock client
        mock_client = MockAnthropicClient(summary_text="Summary of first 2 turns")
        mock_client_class.return_value = mock_client

        # Create agent context
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-mc-custom",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".hdev",
        )
        context._chat_history = self.sample_messages.copy()

        # Create toolbox
        toolbox = Toolbox(context)

        # Execute the micro-compact command with 2 turns
        result = toolbox._micro_compact(ui, sandbox, "2")

        # Verify micro-compaction occurred
        self.assertIn("Micro-compaction completed", result)
        self.assertIn("2 turns", result)
        self.assertIn("3 messages", result)  # 2 turns = (2*2)-1 = 3 messages

        # Verify context was modified correctly
        # Should have: 1 summary message + 5 remaining messages (from original 8)
        # Original 8 - 3 compacted = 5 remaining + 1 summary = 6 total
        self.assertEqual(len(context.chat_history), 6)

    @mock.patch("anthropic.Client")
    def test_micro_compact_command_insufficient_messages(self, mock_client_class):
        """Test /mc with too few messages for the requested turns."""
        # Setup mock client
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

        # Create agent context with only 4 messages (2 turns)
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-mc-insufficient",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".hdev",
        )
        context._chat_history = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
        ]

        # Create toolbox
        toolbox = Toolbox(context)

        # Try to micro-compact 3 turns (6 messages) but only have 4 messages
        result = toolbox._micro_compact(ui, sandbox, "3")

        # Verify error was returned
        self.assertIn("Error", result)
        self.assertIn("Not enough conversation history", result)

    @mock.patch("anthropic.Client")
    def test_micro_compact_command_invalid_input(self, mock_client_class):
        """Test /mc with invalid input."""
        # Setup mock client
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

        # Create agent context
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-mc-invalid",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
            history_base_dir=Path(self.test_dir) / ".hdev",
        )
        context._chat_history = self.sample_messages.copy()

        # Create toolbox
        toolbox = Toolbox(context)

        # Try with non-integer input
        result = toolbox._micro_compact(ui, sandbox, "abc")

        # Verify error was returned
        self.assertIn("Error", result)
        self.assertIn("Invalid number", result)


if __name__ == "__main__":
    unittest.main()
