import pytest
from unittest.mock import Mock, patch
from dataclasses import dataclass
from silica.developer.agent_loop import run
from silica.developer.user_interface import UserInterface
from silica.developer.sandbox import SandboxMode
from silica.developer.context import AgentContext
from typing import List, Any


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
    content: List[str] = None
    usage: Usage = None
    stop_reason: str = None


@dataclass
class MockResponse:
    headers: dict


class MockStream:
    def __init__(self, content):
        self.content = content
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

    def bare(self, message: str | Any, live=None) -> None:
        pass


class MockToolbox:
    def __init__(self, local_tools=None):
        self.local = local_tools or {}
        self.agent_schema = []

    async def invoke_agent_tool(self, tool_use):
        return {"type": "tool_result", "tool_use_id": "test", "content": "test result"}

    async def invoke_agent_tools(self, tool_uses):
        results = []
        for tool_use in tool_uses:
            result = await self.invoke_agent_tool(tool_use)
            results.append(result)
        return results


@pytest.fixture
def mock_anthropic():
    with patch("anthropic.Client") as mock:
        mock_client = Mock()
        stream = MockStream("Test response")
        mock_client.messages.stream.return_value = stream
        mock.return_value = mock_client
        yield mock


@pytest.fixture
def mock_environment():
    with patch("silica.developer.agent_loop.load_dotenv"), patch(
        "os.getenv", return_value="test-key"
    ):
        yield


@pytest.fixture
def model_config():
    return {
        "title": "claude-3-opus-20240229",
        "pricing": {"input": 15.0, "output": 75.0},
        "cache_pricing": {"write": 15.50, "read": 1.0},
        "max_tokens": 8192,
    }


@pytest.fixture
def mock_system_message():
    with patch("silica.developer.agent_loop.create_system_message") as mock:
        mock.return_value = "Test system message"
        yield mock


@pytest.fixture
def mock_toolbox():
    with patch("silica.developer.agent_loop.Toolbox") as mock:
        mock_instance = MockToolbox()
        mock.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def agent_context(model_config):
    ui = MockUserInterface()
    ctx = AgentContext.create(
        model_spec=model_config,
        sandbox_mode=SandboxMode.REMEMBER_PER_RESOURCE,
        sandbox_contents=[],
        user_interface=ui,
    )
    ctx.flush = Mock()
    return ctx


async def test_single_response_mode(
    mock_anthropic, mock_environment, agent_context, mock_system_message, mock_toolbox
):
    await run(
        agent_context=agent_context,
        initial_prompt="Hello",
        single_response=True,
    )

    # Verify initial prompt was processed
    assert any(
        "Hello" in str(msg)
        for msg in agent_context.user_interface.messages
        if msg[0] == "user"
    )
    # Verify the session ended after one response
    assert mock_anthropic.return_value.messages.stream.call_count == 1
    # Verify we got a response
    assert any(
        "Test response" in str(msg)
        for msg in agent_context.user_interface.messages
        if msg[0] == "assistant"
    )


async def test_initial_prompt_without_single_response(
    mock_anthropic, mock_environment, agent_context, mock_system_message, mock_toolbox
):
    agent_context.user_interface.inputs = [
        "/quit"
    ]  # Add quit command to end the session

    await run(
        agent_context=agent_context,
        initial_prompt="Hello",
        single_response=False,
    )

    # Print all messages for debugging
    print("\nAll messages:")
    for msg_type, content in agent_context.user_interface.messages:
        print(f"{msg_type}: {content}")

    # Verify initial prompt was processed
    assert any(
        "Hello" in str(msg)
        for msg in agent_context.user_interface.messages
        if msg[0] == "user"
    ), "Initial prompt 'Hello' not found in messages"

    # Verify we got a response
    assert any(
        "Test response" in str(msg)
        for msg in agent_context.user_interface.messages
        if msg[0] == "assistant"
    ), "Test response not found in assistant messages"

    def handle_system_message(self, message: str, markdown=True, live=None) -> None:
        pass
