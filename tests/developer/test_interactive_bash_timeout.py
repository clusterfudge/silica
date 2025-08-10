"""Tests for interactive bash command timeout functionality."""

import pytest

from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode
from silica.developer.user_interface import UserInterface
from silica.developer.tools.shell import shell_execute
from silica.developer.tools.repl import (
    _run_bash_command_with_interactive_timeout,
)


class MockUserInterface(UserInterface):
    """Mock user interface for testing."""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.response_index = 0
        self.messages = []

    def handle_assistant_message(self, message: str) -> None:
        pass

    def handle_system_message(self, message: str, markdown=True, live=None) -> None:
        self.messages.append(("system", message))

    def permission_callback(
        self, action: str, resource: str, sandbox_mode: SandboxMode, action_arguments
    ):
        return True

    def permission_rendering_callback(
        self, action: str, resource: str, action_arguments
    ):
        pass

    def handle_tool_use(self, tool_name: str, tool_params):
        pass

    def handle_tool_result(self, name: str, result, live=None):
        pass

    async def get_user_input(self, prompt: str = "") -> str:
        if self.response_index < len(self.responses):
            response = self.responses[self.response_index]
            self.response_index += 1
            return response
        return "C"  # Default to continue

    def handle_user_input(self, user_input: str) -> str:
        return user_input

    def display_token_count(self, *args, **kwargs):
        pass

    def display_welcome_message(self):
        pass

    def status(self, message: str, spinner: str = None):
        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return DummyContext()

    def bare(self, message, live=None):
        pass


class TestInteractiveBashTimeout:
    """Test suite for interactive bash timeout functionality."""

    def create_test_context(self, responses=None):
        """Create a test context with mock UI."""
        ui = MockUserInterface(responses)
        return AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=ui,
        )

    @pytest.mark.asyncio
    async def test_quick_command_completion(self):
        """Test that quick commands complete without timeout."""
        context = self.create_test_context()

        result = await shell_execute(context, "echo 'hello world'")

        assert "Exit code: 0" in result
        assert "hello world" in result

    @pytest.mark.asyncio
    async def test_timeout_kill_process(self):
        """Test killing a process when timeout occurs."""
        context = self.create_test_context(responses=["K"])

        result = await _run_bash_command_with_interactive_timeout(
            context, "sleep 2", initial_timeout=0.1
        )

        assert "Command was killed by user" in result
        assert "Execution time:" in result

    @pytest.mark.asyncio
    async def test_timeout_background_process(self):
        """Test backgrounding a process when timeout occurs."""
        context = self.create_test_context(responses=["B"])

        result = await _run_bash_command_with_interactive_timeout(
            context, "sleep 2", initial_timeout=0.1
        )

        assert "Command backgrounded" in result
        assert "PID:" in result
        assert "Process continues running" in result

    @pytest.mark.asyncio
    async def test_timeout_continue_then_kill(self):
        """Test continuing wait then killing process."""
        context = self.create_test_context(responses=["C", "K"])

        # Need a longer sleep to ensure it doesn't complete between timeouts
        result = await _run_bash_command_with_interactive_timeout(
            context, "sleep 3", initial_timeout=0.1
        )

        assert "Command was killed by user" in result

    @pytest.mark.asyncio
    async def test_output_capture_during_timeout(self):
        """Test that output is captured properly during timeout."""
        context = self.create_test_context(responses=["K"])

        # Create a command that produces output then sleeps
        command = "echo 'line1'; echo 'line2'; sleep 2"

        result = await _run_bash_command_with_interactive_timeout(
            context, command, initial_timeout=0.1
        )

        assert "Command was killed by user" in result
        assert "line1" in result
        assert "line2" in result

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked(self):
        """Test that dangerous commands are blocked."""
        context = self.create_test_context()

        result = await shell_execute(context, "sudo rm -rf /")

        assert "Error: This command is not allowed for safety reasons" in result

    @pytest.mark.asyncio
    async def test_system_message_on_timeout(self):
        """Test that system messages are shown on timeout."""
        ui = MockUserInterface(responses=["K"])
        context = AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=ui,
        )

        await _run_bash_command_with_interactive_timeout(
            context, "sleep 2", initial_timeout=0.1
        )

        # Check that system messages were sent
        system_messages = [msg for msg in ui.messages if msg[0] == "system"]
        assert len(system_messages) > 0
        assert any("Command has been running for" in msg[1] for msg in system_messages)

    @pytest.mark.asyncio
    async def test_process_completes_during_user_input_wait(self):
        """Test that if process completes while waiting for user input, it's detected."""
        import asyncio

        class SlowUserInterface(MockUserInterface):
            """User interface that delays responses to simulate user thinking."""

            async def get_user_input(self, prompt: str = "") -> str:
                # Simulate user taking time to respond
                await asyncio.sleep(0.3)  # 300ms delay
                return await super().get_user_input(prompt)

        ui = SlowUserInterface(
            responses=["K"]
        )  # User would choose K, but process should complete first
        context = AgentContext.create(
            model_spec={},
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=ui,
        )

        # Use a command that will complete shortly after timeout but before user responds
        # Timeout after 0.1s, then user takes 0.3s to respond, but sleep only lasts 0.2s total
        result = await _run_bash_command_with_interactive_timeout(
            context, "sleep 0.2", initial_timeout=0.1
        )

        # Process should have completed naturally, not killed by user
        assert "Exit code: 0" in result
        assert "Command was killed by user" not in result
        assert "Command backgrounded" not in result

        # Should show process completed successfully
        # The sleep command exits with code 0 when it completes normally

    @pytest.mark.asyncio
    async def test_live_streaming_functionality(self):
        """Test that live streaming mode works correctly."""
        from silica.developer.tools.repl import run_bash_command_with_live_streaming

        context = self.create_test_context()

        # Test with a quick command that should complete without timeout
        result = await run_bash_command_with_live_streaming(
            context, "echo 'live streaming test'"
        )

        assert "Exit code: 0" in result
        assert "live streaming test" in result

        # Test that we can run the function without errors
        # (Real live streaming would be visible in terminal but not captured in tests)
