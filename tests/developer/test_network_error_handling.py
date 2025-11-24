"""Test graceful handling of network errors during API streaming."""

import pytest
from unittest.mock import Mock, patch
from dataclasses import dataclass
import httpx

from silica.developer.agent_loop import run
from silica.developer.user_interface import UserInterface
from silica.developer.sandbox import SandboxMode
from silica.developer.context import AgentContext


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class MockMessage:
    type: str
    text: str = None
    content: list = None
    usage: Usage = None
    stop_reason: str = None


@dataclass
class MockResponse:
    headers: dict


class MockStream:
    """Mock stream that can simulate successful responses or network errors."""

    def __init__(self, content, should_fail=False, fail_count=0):
        self.content = content
        self.should_fail = should_fail
        self.fail_count = fail_count
        self.attempt_count = 0
        self.final_message = MockMessage(
            type="message",
            content=[{"type": "text", "text": content}],
            usage=Usage(input_tokens=100, output_tokens=50),
            stop_reason="end_turn",
        )
        self.response = MockResponse(
            {
                "anthropic-ratelimit-tokens-remaining": "100000",
                "anthropic-ratelimit-tokens-reset": "2024-03-20T00:00:00Z",
            }
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def __iter__(self):
        self.attempt_count += 1

        # Simulate failure for first N attempts
        if self.should_fail and self.attempt_count <= self.fail_count:
            raise httpx.RemoteProtocolError(
                "peer closed connection without sending complete message body (incomplete chunked read)"
            )

        # Succeed after retry attempts
        yield MockMessage(type="text", text=self.content)

    def get_final_message(self):
        return self.final_message


class MockUserInterface(UserInterface):
    def __init__(self):
        self.messages = []
        self.inputs = []
        self.current_input_index = 0

    def handle_assistant_message(self, message: str) -> None:
        self.messages.append(("assistant", message))

    def handle_system_message(self, message: str, markdown=True, live=None) -> None:
        self.messages.append(("system", message))

    async def get_user_input(self, prompt: str = "") -> str:
        if self.current_input_index < len(self.inputs):
            result = self.inputs[self.current_input_index]
            self.current_input_index += 1
            return result
        return "/quit"

    def handle_user_input(self, user_input: str) -> str:
        self.messages.append(("user", user_input))
        return user_input

    def handle_tool_use(self, tool_name: str, tool_params: dict) -> bool:
        return True

    def handle_tool_result(self, name: str, result: dict, live=None) -> None:
        pass

    def display_token_count(self, *args, **kwargs) -> None:
        pass

    def display_welcome_message(self) -> None:
        pass

    def permission_callback(
        self,
        action: str,
        resource: str,
        sandbox_mode: SandboxMode,
        action_arguments: dict | None,
    ) -> bool:
        return True

    def permission_rendering_callback(
        self,
        action: str,
        resource: str,
        action_arguments: dict | None,
    ):
        pass

    def status(self, message: str, spinner: str = None):
        class NoOpContextManager:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        return NoOpContextManager()

    def bare(self, message: str, live=None) -> None:
        pass


@pytest.fixture
def model_config():
    return {
        "title": "claude-3-opus-20240229",
        "pricing": {"input": 15.0, "output": 75.0},
        "cache_pricing": {"write": 15.50, "read": 1.0},
        "max_tokens": 8192,
    }


@pytest.fixture
def agent_context(model_config, persona_base_dir):
    ui = MockUserInterface()
    ctx = AgentContext.create(
        model_spec=model_config,
        sandbox_mode=SandboxMode.REMEMBER_PER_RESOURCE,
        sandbox_contents=[],
        user_interface=ui,
        persona_base_directory=persona_base_dir,
    )
    ctx.flush = Mock()
    return ctx


@pytest.mark.asyncio
async def test_network_error_with_successful_retry(agent_context):
    """Test that network errors are retried and eventually succeed."""

    with (
        patch("anthropic.Client") as mock_anthropic_client,
        patch("silica.developer.agent_loop.load_dotenv"),
        patch("os.getenv", return_value="test-key"),
        patch(
            "silica.developer.agent_loop.create_system_message",
            return_value="Test system",
        ),
        patch("silica.developer.agent_loop.Toolbox") as mock_toolbox_class,
        patch("time.sleep"),
    ):  # Mock sleep to speed up test
        # Setup mock client with streams that fail once then succeed
        mock_client = Mock()
        call_count = [0]  # Use list to allow modification in nested function

        def create_stream(**kwargs):
            call_count[0] += 1
            # First call fails, second succeeds
            if call_count[0] == 1:
                return MockStream("Test response", should_fail=True, fail_count=1)
            else:
                return MockStream("Test response", should_fail=False, fail_count=0)

        mock_client.messages.stream.side_effect = create_stream
        mock_anthropic_client.return_value = mock_client

        # Setup mock toolbox
        mock_toolbox = Mock()
        mock_toolbox.agent_schema = []
        mock_toolbox.local = {}
        mock_toolbox_class.return_value = mock_toolbox

        # Run the agent with a single prompt
        await run(
            agent_context=agent_context,
            initial_prompt="Test prompt",
            single_response=True,
        )

        # Verify retry behavior
        assert mock_client.messages.stream.call_count == 2, "Should have retried once"

        # Verify user was informed about retry
        system_messages = [
            msg
            for msg_type, msg in agent_context.user_interface.messages
            if msg_type == "system"
        ]
        retry_messages = [
            msg
            for msg in system_messages
            if "Network error" in msg and "Retrying" in msg
        ]
        assert len(retry_messages) > 0, "Should have displayed retry message to user"


@pytest.mark.asyncio
async def test_network_error_max_retries_exceeded(agent_context):
    """Test that network errors eventually fail after max retries."""

    with (
        patch("anthropic.Client") as mock_anthropic_client,
        patch("silica.developer.agent_loop.load_dotenv"),
        patch("os.getenv", return_value="test-key"),
        patch(
            "silica.developer.agent_loop.create_system_message",
            return_value="Test system",
        ),
        patch("silica.developer.agent_loop.Toolbox") as mock_toolbox_class,
        patch("time.sleep"),
    ):  # Mock sleep to speed up test
        # Setup mock client with a stream that always fails
        mock_client = Mock()
        mock_client.messages.stream.side_effect = lambda **kwargs: MockStream(
            "",
            should_fail=True,
            fail_count=999,  # Always fail
        )
        mock_anthropic_client.return_value = mock_client

        # Setup mock toolbox
        mock_toolbox = Mock()
        mock_toolbox.agent_schema = []
        mock_toolbox.local = {}
        mock_toolbox_class.return_value = mock_toolbox

        # Run the agent and expect it to raise an error after max retries
        with pytest.raises(httpx.RemoteProtocolError):
            await run(
                agent_context=agent_context,
                initial_prompt="Test prompt",
                single_response=True,
            )

        # Verify it tried multiple times (5 retries as per the code)
        assert (
            mock_client.messages.stream.call_count == 5
        ), "Should have attempted max retries"

        # Verify user was informed about retries
        system_messages = [
            msg
            for msg_type, msg in agent_context.user_interface.messages
            if msg_type == "system"
        ]
        retry_messages = [msg for msg in system_messages if "Network error" in msg]
        assert len(retry_messages) > 0, "Should have displayed retry messages to user"


@pytest.mark.asyncio
async def test_other_errors_not_caught(agent_context):
    """Test that non-network errors are not caught by network error handler."""

    with (
        patch("anthropic.Client") as mock_anthropic_client,
        patch("silica.developer.agent_loop.load_dotenv"),
        patch("os.getenv", return_value="test-key"),
        patch(
            "silica.developer.agent_loop.create_system_message",
            return_value="Test system",
        ),
        patch("silica.developer.agent_loop.Toolbox") as mock_toolbox_class,
    ):
        # Setup mock client that raises a different error
        mock_client = Mock()
        mock_client.messages.stream.side_effect = ValueError("Some other error")
        mock_anthropic_client.return_value = mock_client

        # Setup mock toolbox
        mock_toolbox = Mock()
        mock_toolbox.agent_schema = []
        mock_toolbox.local = {}
        mock_toolbox_class.return_value = mock_toolbox

        # Run the agent and expect the ValueError to propagate
        with pytest.raises(ValueError, match="Some other error"):
            await run(
                agent_context=agent_context,
                initial_prompt="Test prompt",
                single_response=True,
            )

        # Should only try once since it's not a retryable error
        assert mock_client.messages.stream.call_count == 1
