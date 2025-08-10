import os
from typing import Dict, Any

import pytest
import tempfile
from unittest.mock import patch, MagicMock
from silica.developer.user_interface import UserInterface
from silica.developer.sandbox import SandboxMode
from silica.developer.cli import main


class MockUserInterface(UserInterface):
    def __init__(self):
        self.messages = []
        self.next_input = ""

    def handle_assistant_message(self, message: str) -> None:
        self.messages.append(("assistant", message))

    def handle_system_message(self, message: str, markdown=True) -> None:
        self.messages.append(("system", message))

    def get_user_input(self, prompt: str = "") -> str:
        result = self.next_input
        return result

    def handle_user_input(self, user_input: str) -> str:
        return user_input

    def handle_tool_use(self, tool_name: str, tool_params: dict) -> bool:
        return True

    def handle_tool_result(self, name: str, result: dict) -> None:
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
        return self.next_input.lower() == "y"

    def permission_rendering_callback(
        self,
        action: str,
        resource: str,
        action_arguments: Dict | None,
    ) -> None:
        pass

    def status(self, message: str, spinner: str = None):
        class NoOpContextManager:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

        return NoOpContextManager()

    def bare(self, message: str | Any) -> None:
        pass


def test_permission_check_single_line():
    ui = MockUserInterface()
    ui.next_input = "y"
    result = ui.permission_callback(
        "read", "file.txt", SandboxMode.REMEMBER_PER_RESOURCE, None
    )
    assert result


def test_permission_check_multi_line():
    ui = MockUserInterface()
    ui.next_input = "This is a\nmulti-line\ninput\ny"
    result = ui.permission_callback(
        "write", "file.txt", SandboxMode.REMEMBER_PER_RESOURCE, None
    )
    assert not result  # Because we're only comparing with "y", this should fail


def test_permission_check_negative_response():
    ui = MockUserInterface()
    ui.next_input = "n"
    result = ui.permission_callback(
        "delete", "file.txt", SandboxMode.REMEMBER_PER_RESOURCE, None
    )
    assert not result


@pytest.fixture
def temp_prompt_file():
    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
        f.write("Test prompt content")
    yield f.name
    os.unlink(f.name)


@patch("silica.developer.hdev.run")
@patch("silica.developer.cli.CLIUserInterface")
def test_cli_with_direct_prompt(mock_ui_class, mock_run):
    with patch("sys.argv", ["test.py", "--prompt", "Hello, assistant"]):
        # Setup mock interface
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui

        main()
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["initial_prompt"] == "Hello, assistant"
        assert call_kwargs["single_response"] is True


@patch("silica.developer.hdev.run")
@patch("silica.developer.cli.CLIUserInterface")
def test_cli_with_file_prompt(mock_ui_class, mock_run, temp_prompt_file):
    with patch("sys.argv", ["test.py", "--prompt", f"@{temp_prompt_file}"]):
        # Setup mock interface
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui

        main()
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["initial_prompt"] == "Test prompt content"
        assert call_kwargs["single_response"] is True


@patch("silica.developer.hdev.run")
@patch("silica.developer.cli.CLIUserInterface")
def test_cli_with_nonexistent_prompt_file(mock_ui_class, mock_run, capsys):
    with patch("sys.argv", ["test.py", "--prompt", "@nonexistent.txt"]):
        # Setup mock interface
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui

        main()
        mock_run.assert_not_called()
        captured = capsys.readouterr()
        assert "Error: Could not find file" in captured.out


@patch("silica.developer.hdev.run")
@patch("silica.developer.cli.CLIUserInterface")
def test_cli_without_prompt(mock_ui_class, mock_run):
    with patch("sys.argv", ["test.py"]):
        # Setup mock interface
        mock_ui = MagicMock()
        mock_ui_class.return_value = mock_ui
        mock_ui.get_user_input.return_value = "/quit"

        main()
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs["initial_prompt"] is None
        assert call_kwargs["single_response"] is False
