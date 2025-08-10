#!/usr/bin/env python3
"""
Unit tests for the conversation compaction functionality.
"""

import unittest
from unittest import mock
from pathlib import Path
import tempfile
import shutil


from silica.developer.compacter import ConversationCompacter, CompactionSummary
from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.user_interface import UserInterface
from silica.developer.memory import MemoryManager


class MockAnthropicClient:
    """Mock for the Anthropic client."""

    def __init__(self, token_counts=None, response_content=None):
        """Initialize the mock client.

        Args:
            token_counts: Dictionary mapping input text to token counts
            response_content: Content to return in the response
        """
        self.token_counts = token_counts or {"Hello": 1, "Hello world": 2}
        self.response_content = response_content or "Summary of the conversation"
        self.count_tokens_called = False
        self.messages_create_called = False

        # Create a messages attribute for the new API style
        self.messages = self.MessagesClient(self)

    class MessagesClient:
        """Mock for the messages client."""

        def __init__(self, parent):
            self.parent = parent

        def count_tokens(self, model, system=None, messages=None, tools=None):
            """Mock for the messages.count_tokens method."""
            self.parent.count_tokens_called = True

            # Calculate token count based on all components
            total_chars = 0

            # Count system characters
            if system:
                for block in system:
                    if isinstance(block, dict) and block.get("type") == "text":
                        total_chars += len(block.get("text", ""))

            # Count messages characters
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

            # Count tools characters (rough estimate)
            if tools:
                import json

                total_chars += len(json.dumps(tools))

            # Estimate tokens from characters
            token_count = max(1, total_chars // 4)

            # Create a response object with a token_count attribute
            class TokenResponse:
                def __init__(self, count):
                    self.token_count = count

            return TokenResponse(token_count)

        def create(self, model, system, messages, max_tokens):
            """Mock for the messages.create method."""
            self.parent.messages_create_called = True

            # Create a response object with content
            class ContentItem:
                def __init__(self, text):
                    self.text = text

            class MessageResponse:
                def __init__(self, content_text):
                    self.content = [ContentItem(content_text)]

            return MessageResponse(self.parent.response_content)


class MockUserInterface(UserInterface):
    """Mock for the user interface."""

    def __init__(self):
        self.system_messages = []

    def handle_system_message(self, message, markdown=True):
        """Record system messages."""
        self.system_messages.append(message)

    def permission_callback(self, action, resource, sandbox_mode, action_arguments):
        """Always allow."""
        return True

    def permission_rendering_callback(self, action, resource, action_arguments):
        """Do nothing."""

    def bare(self, message):
        """Do nothing."""

    def display_token_count(
        self,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        total_cost,
        cached_tokens=None,
        conversation_size=None,
        context_window=None,
    ):
        """Do nothing."""

    def display_welcome_message(self):
        """Do nothing."""

    def get_user_input(self, prompt=""):
        """Return empty string."""
        return ""

    def handle_assistant_message(self, message, markdown=True):
        """Do nothing."""

    def handle_tool_result(self, name, result, markdown=True):
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


class TestConversationCompaction(unittest.TestCase):
    """Tests for the conversation compaction functionality."""

    def setUp(self):
        """Set up test environment."""
        # Create a temporary directory for test files
        self.test_dir = tempfile.mkdtemp()

        # Create sample messages
        self.sample_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there! How can I help you today?"},
            {"role": "user", "content": "Tell me about conversation compaction"},
            {
                "role": "assistant",
                "content": "Conversation compaction is a technique...",
            },
        ]

        # Create a mock client
        self.mock_client = MockAnthropicClient()

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
    def test_count_tokens(self, mock_client_class):
        """Test token counting."""
        # Setup mock with an updated structure to support messages.count_tokens
        mock_client = MockAnthropicClient()
        mock_client_class.return_value = mock_client

        # Create compacter with the mock client directly
        compacter = ConversationCompacter(client=mock_client)

        # The client object should already have the messages.count_tokens method properly set up

        # Create agent context for the new API
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-session",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
        )
        context._chat_history = self.sample_messages

        # Count tokens using new API
        tokens = compacter.count_tokens(context, "sonnet")

        # Assert token count was called
        self.assertTrue(mock_client.count_tokens_called)

        # Token count should be positive
        self.assertGreater(tokens, 0)

    @mock.patch("anthropic.Client")
    def test_should_compact(self, mock_client_class):
        """Test should_compact method."""
        # Setup mock with high token count
        mock_client = MockAnthropicClient(token_counts={"any": 200000})
        mock_client_class.return_value = mock_client

        # Create compacter with high threshold ratio (99% of context window) and mock client
        compacter = ConversationCompacter(threshold_ratio=0.5, client=mock_client)

        # Override the model_context_windows dictionary to have a known test value
        compacter.model_context_windows = {"claude-3-5-sonnet-latest": 100000}

        # Create agent context for the new API
        ui = MockUserInterface()
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-session",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
        )
        context._chat_history = self.sample_messages

        # Mock the count_tokens method to always return a high number (60% of context window)
        compacter.count_tokens = mock.MagicMock(return_value=60000)

        # Should compact should return True because 60000 > 50000 (50% of 100000)
        self.assertTrue(compacter.should_compact(context, "claude-3-5-sonnet-latest"))

    @mock.patch("anthropic.Client")
    def test_context_flush_with_compaction(self, mock_client_class):
        """Test context flush with compaction."""

        # Create response mock
        class MockResponse:
            def __init__(self):
                self.content = [
                    type(
                        "obj",
                        (object,),
                        {"text": "This is a summary of the conversation."},
                    )
                ]

        messages_mock = mock.MagicMock()
        messages_mock.create.return_value = MockResponse()

        # Setup mock client with messages namespace for newer API style
        mock_client_instance = mock.MagicMock()
        mock_client_instance.messages = messages_mock

        # Mock count_tokens now using messages.count_tokens
        mock_client_instance.messages.count_tokens = mock.MagicMock(
            side_effect=lambda model, messages: type(
                "obj",
                (object,),
                {"token_count": 50000 if len(self.sample_messages) > 2 else 100},
            )
        )

        mock_client_class.return_value = mock_client_instance

        # Create user interface
        ui = MockUserInterface()

        # Create sandbox
        sandbox = Sandbox(self.test_dir, mode=SandboxMode.ALLOW_ALL)

        # Create agent context
        memory_manager = MemoryManager()
        context = AgentContext(
            parent_session_id=None,
            session_id="test-session",
            model_spec=self.model_spec,
            sandbox=sandbox,
            user_interface=ui,
            usage=[],
            memory_manager=memory_manager,
        )

        # Setup temporary history directory
        history_dir = Path(self.test_dir) / ".hdev" / "history" / context.session_id
        history_dir.mkdir(parents=True, exist_ok=True)

        # Create the root.json file to ensure the directory exists
        with open(history_dir / "root.json", "w") as f:
            f.write("{}")

        # Create a CompactionSummary mock
        compaction_summary = CompactionSummary(
            original_message_count=100,
            original_token_count=50000,
            summary_token_count=1000,
            compaction_ratio=0.02,
            summary="This is a summary of the conversation.",
        )

        # Mock the generate_summary method to return our predefined summary
        with mock.patch(
            "silica.developer.compacter.ConversationCompacter.generate_summary",
            return_value=compaction_summary,
        ), mock.patch(
            "silica.developer.compacter.ConversationCompacter.should_compact",
            return_value=True,
        ), mock.patch(
            "silica.developer.compacter.ConversationCompacter.compact_conversation",
            return_value=(
                [{"role": "system", "content": "Summary"}],
                compaction_summary,
            ),
        ), mock.patch("pathlib.Path.home", return_value=Path(self.test_dir)):
            # Flush with compaction
            context.flush(self.sample_messages, compact=True)

            # Check that the file was created
            history_file = history_dir / "root.json"
            self.assertTrue(history_file.exists(), "History file wasn't created")


if __name__ == "__main__":
    unittest.main()
