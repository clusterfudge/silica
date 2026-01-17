"""Shared test fixtures for developer tests."""

import json
import pytest


@pytest.fixture
def persona_base_dir(tmp_path):
    """Provide a temporary persona base directory for tests."""
    persona_dir = tmp_path / "persona"
    persona_dir.mkdir(exist_ok=True)
    return persona_dir


class MockMessagesClient:
    """Mock for the Anthropic messages client.

    Supports both simple response mode and queued responses for multi-call tests.
    Tracks all calls for assertion purposes.
    """

    def __init__(self, parent):
        self.parent = parent
        self.create_calls = []
        self.count_tokens_calls = []

    def count_tokens(self, model, system=None, messages=None, tools=None):
        """Mock for the messages.count_tokens method.

        Returns the configured token_count if set, otherwise estimates from content.
        """
        self.count_tokens_calls.append(
            {
                "model": model,
                "system": system,
                "messages": messages,
                "tools": tools,
            }
        )
        self.parent.count_tokens_called = True

        # Use configured token count if provided
        if self.parent.token_count is not None:
            count = self.parent.token_count
        else:
            # Estimate token count from content
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
                total_chars += len(json.dumps(tools))

            # Estimate tokens from characters (roughly 4 chars per token)
            count = max(1, total_chars // 4)

        class TokenResponse:
            def __init__(self, token_count):
                self.token_count = token_count

        return TokenResponse(count)

    def create(self, model, system, messages, max_tokens, tools=None, tool_choice=None):
        """Mock for the messages.create method.

        Returns queued responses if available, otherwise returns the default response.
        """
        self.create_calls.append(
            {
                "model": model,
                "system": system,
                "messages": messages,
                "max_tokens": max_tokens,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        self.parent.messages_create_called = True

        # Get the appropriate response
        response_text = self.parent.get_next_response()

        class ContentItem:
            def __init__(self, text):
                self.text = text
                self.type = "text"

        class Usage:
            input_tokens = 100
            output_tokens = 50

        class MessageResponse:
            def __init__(self, content_text):
                self.content = [ContentItem(content_text)]
                self.usage = Usage()
                self.stop_reason = "end_turn"

        return MessageResponse(response_text)


class MockAnthropicClient:
    """Mock Anthropic client for testing.

    Supports:
    - Configurable token counts (fixed or estimated from content)
    - Single response or queued responses for multi-call tests
    - Call tracking for assertions
    - Legacy API compatibility (token_counts dict, response_content)

    Usage examples:

        # Simple usage with default response
        client = MockAnthropicClient()

        # With fixed token count
        client = MockAnthropicClient(token_count=50000)

        # With custom response
        client = MockAnthropicClient(response_content="Custom summary")

        # With multiple responses (for two-pass compaction tests)
        client = MockAnthropicClient(responses=["Guidance", "Summary"])

        # Check if methods were called
        assert client.count_tokens_called
        assert client.messages_create_called

        # Inspect calls
        assert len(client.messages.create_calls) == 2
    """

    def __init__(
        self,
        token_count=None,
        token_counts=None,  # Legacy parameter, ignored
        response_content=None,
        responses=None,
        summary_text=None,  # Alias for response_content
    ):
        """Initialize the mock client.

        Args:
            token_count: Fixed token count to return (None = estimate from content)
            token_counts: Legacy parameter, ignored for backwards compatibility
            response_content: Single response content string
            responses: List of response strings to return in order (for multi-call tests)
            summary_text: Alias for response_content (for backwards compatibility)
        """
        self.token_count = token_count
        self.count_tokens_called = False
        self.messages_create_called = False

        # Handle response configuration
        # Priority: responses > response_content > summary_text > default
        if responses is not None:
            self.responses = responses
        elif response_content is not None:
            self.responses = [response_content]
        elif summary_text is not None:
            self.responses = [summary_text]
        else:
            self.responses = ["Summary of the conversation"]

        self.response_index = 0

        # Create messages client
        self.messages = MockMessagesClient(self)

    @property
    def response_content(self):
        """Get the current/default response content."""
        return self.responses[0] if self.responses else "Summary of the conversation"

    def get_next_response(self):
        """Get the next response in the queue.

        Returns responses in order, repeating the last one if exhausted.
        """
        if self.response_index < len(self.responses):
            response = self.responses[self.response_index]
            self.response_index += 1
            return response
        return self.responses[-1] if self.responses else "Default response"

    def reset(self):
        """Reset the mock state for reuse."""
        self.count_tokens_called = False
        self.messages_create_called = False
        self.response_index = 0
        self.messages.create_calls = []
        self.messages.count_tokens_calls = []


class MockUserInterface:
    """Mock for the user interface.

    Tracks system messages and provides no-op implementations for all UI methods.
    Compatible with both sync and async test contexts.
    """

    def __init__(self):
        self.system_messages = []

    def handle_system_message(self, message, markdown=True, live=None):
        """Record system messages."""
        self.system_messages.append(message)

    def permission_callback(
        self, action, resource, sandbox_mode, action_arguments, group=None
    ):
        """Always allow."""
        return True

    def permission_rendering_callback(self, action, resource, action_arguments):
        """Do nothing."""

    def bare(self, message, live=None):
        """Do nothing."""

    def display_token_count(
        self,
        prompt_tokens=None,
        completion_tokens=None,
        total_tokens=None,
        total_cost=None,
        cached_tokens=None,
        conversation_size=None,
        context_window=None,
        thinking_tokens=None,
        thinking_cost=None,
        **kwargs,
    ):
        """Do nothing."""

    def display_welcome_message(self):
        """Do nothing."""

    def get_user_input(self, prompt=""):
        """Return empty string (sync version)."""
        return ""

    async def get_user_input_async(self, prompt=""):
        """Return empty string (async version)."""
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


@pytest.fixture
def mock_anthropic_client():
    """Create a mock Anthropic client with default settings."""
    return MockAnthropicClient()


@pytest.fixture
def mock_user_interface():
    """Create a mock user interface."""
    return MockUserInterface()
