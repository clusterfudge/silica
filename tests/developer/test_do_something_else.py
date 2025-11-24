import pytest
from unittest.mock import MagicMock, patch

from silica.developer.sandbox import Sandbox, SandboxMode, DoSomethingElseError


def test_do_something_else_error():
    # Mock a permission callback that raises DoSomethingElseError
    mock_callback = MagicMock(side_effect=DoSomethingElseError())

    # Create a sandbox with the mock callback
    sandbox = Sandbox(
        ".", SandboxMode.REQUEST_EVERY_TIME, permission_check_callback=mock_callback
    )

    # Verify that the error is properly raised
    with pytest.raises(DoSomethingElseError):
        sandbox.check_permissions("test_action", "test_resource")

    # Verify the callback was called with correct parameters
    mock_callback.assert_called_once_with(
        "test_action", "test_resource", SandboxMode.REQUEST_EVERY_TIME, None
    )


def test_default_permission_callback_do_something_else(monkeypatch):
    # Mock the input function to return 'd'
    monkeypatch.setattr("builtins.input", lambda _: "d")

    # Create a sandbox using the default permission callback
    sandbox = Sandbox(".", SandboxMode.REQUEST_EVERY_TIME)

    # Verify that DoSomethingElseError is raised when user enters 'd'
    with pytest.raises(DoSomethingElseError):
        sandbox.check_permissions("test_action", "test_resource")


# TODO: what is the goal of this test?
# def test_tool_propagates_do_something_else_error():
#     """Test that tools correctly propagate the DoSomethingElseError."""
#     from silica.developer.tools.files import read_file
#
#     # Create a mock context with a sandbox that raises DoSomethingElseError
#     mock_context = MagicMock()
#     silica.developer.tools.files.read_file.side_effect = DoSomethingElseError()
#
#     # Call the read_file tool, which should propagate the exception
#     with pytest.raises(DoSomethingElseError):
#         read_file(mock_context, "test_file.txt")


@patch("silica.developer.tools.framework.invoke_tool")
async def test_toolbox_propagates_do_something_else_error(mock_invoke_tool):
    """Test that the toolbox correctly propagates the DoSomethingElseError."""
    from silica.developer.toolbox import Toolbox

    # Setup mock - make it async
    async def mock_async_invoke_tool(*args, **kwargs):
        raise DoSomethingElseError()

    mock_invoke_tool.side_effect = mock_async_invoke_tool

    # Create toolbox and context
    mock_context = MagicMock()
    toolbox = Toolbox(mock_context)

    # Create a mock tool_use object
    mock_tool_use = MagicMock()

    # Call invoke_agent_tool, which should propagate the exception
    with pytest.raises(DoSomethingElseError):
        await toolbox.invoke_agent_tool(mock_tool_use)

    # Verify invoke_tool was called
    mock_invoke_tool.assert_called_once()


def test_agent_workflow_do_something_else():
    """Test the complete agent workflow when 'do something else' is selected."""

    # Create a chat history with a user message and an assistant message
    chat_history = [
        {"role": "user", "content": "Can you help me optimize this code?"},
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "I'll help you optimize this code."}],
        },
    ]

    # Simulate the handling of DoSomethingElseError in subagent.py
    # This essentially replicates the error handling block in subagent.py

    # 1. Remove the last assistant message
    if chat_history and chat_history[-1]["role"] == "assistant":
        chat_history.pop()

    # 2. Get alternative prompt (simulated)
    alternate_prompt = "Let me describe the code instead"

    # 3. Append alternate prompt to the last user message
    for i in reversed(range(len(chat_history))):
        if chat_history[i]["role"] == "user":
            # Add the alternate prompt to the previous user message
            if isinstance(chat_history[i]["content"], str):
                chat_history[i]["content"] += (
                    f"\n\nAlternate request: {alternate_prompt}"
                )
            elif isinstance(chat_history[i]["content"], list):
                # Handle content as list of blocks
                chat_history[i]["content"].append(
                    {
                        "type": "text",
                        "text": f"\n\nAlternate request: {alternate_prompt}",
                    }
                )
            break

    # Verify the chat history was modified correctly
    assert (
        len(chat_history) == 1
    ), "Assistant message should have been removed from chat history"
    assert chat_history[0]["role"] == "user", "First message should be from user"

    # The user message should now contain the alternate request
    assert (
        "Alternate request: Let me describe the code instead"
        in chat_history[0]["content"]
    ), "User message should contain the alternate request"


@patch("silica.developer.sandbox.DoSomethingElseError", DoSomethingElseError)
def test_agent_tool_handling_with_do_something_else():
    """Test the handling of DoSomethingElseError during tool invocation in the agent."""
    from silica.developer.sandbox import DoSomethingElseError

    # Create mock objects for the test
    mock_ui = MagicMock()
    mock_ui.get_user_input.return_value = "I want to try a different approach"

    # Mock the part object representing a tool use
    mock_part = MagicMock()
    mock_part.name = "read_file"
    mock_part.input = {"path": "test.py"}

    # Mock the tool invocation to raise DoSomethingElseError
    mock_toolbox = MagicMock()
    mock_toolbox.invoke_agent_tool.side_effect = DoSomethingElseError()

    # Set up chat history with a user and assistant message
    chat_history = [
        {"role": "user", "content": "Help me understand this code"},
        {"role": "assistant", "content": "I'll analyze the code for you"},
    ]

    # Create an empty tool result buffer
    tool_result_buffer = []

    # Simulate the error handling code from subagent.py
    try:
        # This will raise DoSomethingElseError
        result = mock_toolbox.invoke_agent_tool(mock_part)
        tool_result_buffer.append(result)
        mock_ui.handle_tool_result(mock_part.name, result)
    except DoSomethingElseError:
        # Handle "do something else" workflow:
        # 1. Remove the last assistant message
        if chat_history and chat_history[-1]["role"] == "assistant":
            chat_history.pop()

        # 2. Get user's alternate prompt
        mock_ui.handle_system_message(
            "You selected 'do something else'. Please enter what you'd like to do instead:"
        )
        alternate_prompt = mock_ui.get_user_input()

        # 3. Append alternate prompt to the last user message
        for i in reversed(range(len(chat_history))):
            if chat_history[i]["role"] == "user":
                # Add the alternate prompt to the previous user message
                if isinstance(chat_history[i]["content"], str):
                    chat_history[i]["content"] += (
                        f"\n\nAlternate request: {alternate_prompt}"
                    )
                elif isinstance(chat_history[i]["content"], list):
                    # Handle content as list of blocks
                    chat_history[i]["content"].append(
                        {
                            "type": "text",
                            "text": f"\n\nAlternate request: {alternate_prompt}",
                        }
                    )
                break

        # Clear the tool result buffer to avoid processing the current tool request
        tool_result_buffer.clear()

    # Verify UI was used to get alternate prompt
    mock_ui.handle_system_message.assert_called_with(
        "You selected 'do something else'. Please enter what you'd like to do instead:"
    )
    mock_ui.get_user_input.assert_called_once()

    # Check the chat history was properly modified
    assert len(chat_history) == 1, "Expected only the user message in chat history"
    assert (
        chat_history[0]["role"] == "user"
    ), "Expected the remaining message to be from user"
    assert (
        "Alternate request: I want to try a different approach"
        in chat_history[0]["content"]
    ), "User message should contain the alternate request"

    # Check that tool_result_buffer was cleared
    assert len(tool_result_buffer) == 0, "Expected tool_result_buffer to be cleared"


def test_cli_user_interface_do_something_else():
    """Test that the CLI user interface permission callback properly handles 'do something else'."""
    from silica.developer.hdev import CLIUserInterface
    from rich.console import Console

    # Create a mock console that returns 'd' for input
    mock_console = MagicMock(spec=Console)
    mock_console.input.return_value = "d"

    # Create the user interface
    ui = CLIUserInterface(mock_console, SandboxMode.REQUEST_EVERY_TIME)

    # Test the permission callback
    with pytest.raises(DoSomethingElseError):
        ui.permission_callback(
            "test_action", "test_resource", SandboxMode.REQUEST_EVERY_TIME, {}
        )

    # Verify the console was used to get input with the correct prompt
    mock_console.input.assert_called_once_with(
        "[bold yellow]Allow this action? (y/N/D for 'do something else'): [/bold yellow]"
    )
