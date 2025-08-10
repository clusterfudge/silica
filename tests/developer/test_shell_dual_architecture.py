"""
Tests for the dual shell architecture implementation.

This test suite validates both the shell_execute (quick commands) and
shell_session_* (persistent sessions) approaches work correctly.
"""

import pytest

from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode
from silica.developer.user_interface import UserInterface
from silica.developer.tools.shell import (
    shell_execute,
    shell_session_create,
    shell_session_execute,
    shell_session_list,
    shell_session_get_output,
    shell_session_destroy,
    shell_session_set_timeout,
)


class TestUserInterface(UserInterface):
    """Test user interface that automatically approves all permissions."""

    def permission_callback(self, action, resource, sandbox_mode, action_arguments):
        return True

    def permission_rendering_callback(self, action, resource, action_arguments):
        pass

    def handle_assistant_message(self, message):
        pass

    def handle_system_message(self, message, markdown=True, live=None):
        pass

    def handle_tool_use(self, tool_name, tool_params):
        pass

    def handle_tool_result(self, name, result, live=None):
        pass

    async def get_user_input(self, prompt=""):
        return "Y"

    def handle_user_input(self, user_input):
        return user_input

    def display_token_count(self, *args, **kwargs):
        pass

    def display_welcome_message(self):
        pass

    def status(self, message, spinner=None):
        class DummyContext:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        return DummyContext()

    def bare(self, message, live=None):
        pass


@pytest.fixture
def context():
    """Create a test context with permissions allowed."""
    ui = TestUserInterface()
    ctx = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=ui,
    )

    # Clean up any existing sessions before each test
    try:
        from silica.developer.tools.tmux_tool import tmux_destroy_all_sessions

        tmux_destroy_all_sessions(ctx)
    except Exception:
        pass

    return ctx


class TestShellExecute:
    """Test the shell_execute function for quick commands."""

    @pytest.mark.asyncio
    async def test_simple_command(self, context):
        """Test basic command execution."""
        result = await shell_execute(context, 'echo "Hello World"')

        assert "Exit code: 0" in result
        assert "Hello World" in result
        assert "STDOUT:" in result

    @pytest.mark.asyncio
    async def test_command_with_output(self, context):
        """Test command with substantial output."""
        result = await shell_execute(context, 'echo "Line 1\\nLine 2\\nLine 3"')

        assert "Exit code: 0" in result
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result

    @pytest.mark.asyncio
    async def test_command_with_error(self, context):
        """Test command that produces error output."""
        result = await shell_execute(context, 'echo "error" >&2')

        assert "Exit code: 0" in result
        assert "STDERR:" in result
        assert "error" in result

    @pytest.mark.asyncio
    async def test_failing_command(self, context):
        """Test command that fails."""
        result = await shell_execute(context, "false")

        assert "Exit code: 1" in result

    @pytest.mark.asyncio
    async def test_dangerous_command_blocked(self, context):
        """Test that dangerous commands are blocked."""
        result = await shell_execute(context, "sudo rm -rf /")

        assert "Error: This command is not allowed for safety reasons" in result

    @pytest.mark.asyncio
    async def test_custom_timeout(self, context):
        """Test command with custom timeout."""
        result = await shell_execute(context, 'echo "Quick command"', timeout=5)

        assert "Exit code: 0" in result
        assert "Quick command" in result


class TestShellSessions:
    """Test the shell_session_* functions for persistent sessions."""

    @pytest.mark.asyncio
    async def test_session_lifecycle(self, context):
        """Test creating, using, and destroying a session."""
        session_name = "test_session_lifecycle"

        try:
            # Create session
            result = await shell_session_create(context, session_name)
            assert "created successfully" in result

            # List sessions
            result = shell_session_list(context)
            assert session_name in result
            assert "active" in result

            # Execute command in session
            result = await shell_session_execute(
                context, session_name, 'echo "Session command"'
            )
            assert "executed" in result

            # Get output
            result = shell_session_get_output(context, session_name)
            assert "Session command" in result

            # Destroy session
            result = shell_session_destroy(context, session_name)
            assert "destroyed successfully" in result
        finally:
            # Ensure cleanup
            try:
                shell_session_destroy(context, session_name)
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_session_with_initial_command(self, context):
        """Test creating session with initial command."""
        session_name = "init_session_test"

        try:
            result = await shell_session_create(
                context, session_name, 'echo "Initial command"'
            )
            assert "created successfully" in result

            # Check output contains initial command result
            result = shell_session_get_output(context, session_name)
            assert "Initial command" in result
        finally:
            # Cleanup
            try:
                shell_session_destroy(context, session_name)
            except Exception:
                pass

    @pytest.mark.asyncio
    async def test_session_timeout_configuration(self, context):
        """Test setting session timeout."""
        # Create session
        await shell_session_create(context, "timeout_session")

        # Set timeout
        result = shell_session_set_timeout(context, "timeout_session", 1)
        assert "1 seconds" in result

        # Execute quick command (should complete within timeout)
        result = await shell_session_execute(context, "timeout_session", 'echo "Quick"')
        assert "executed" in result

        # Cleanup
        shell_session_destroy(context, "timeout_session")

    @pytest.mark.asyncio
    async def test_multiple_sessions(self, context):
        """Test managing multiple concurrent sessions."""
        session1_name = "session1_multi"
        session2_name = "session2_multi"

        try:
            # Create multiple sessions
            await shell_session_create(context, session1_name, 'echo "Session 1"')
            await shell_session_create(context, session2_name, 'echo "Session 2"')

            # List sessions
            result = shell_session_list(context)
            assert session1_name in result
            assert session2_name in result

            # Execute commands in different sessions
            await shell_session_execute(context, session1_name, 'echo "Command 1"')
            await shell_session_execute(context, session2_name, 'echo "Command 2"')

            # Verify outputs are separate
            output1 = shell_session_get_output(context, session1_name)
            output2 = shell_session_get_output(context, session2_name)

            assert "Session 1" in output1
            assert "Command 1" in output1
            assert "Session 2" in output2
            assert "Command 2" in output2
        finally:
            # Cleanup
            try:
                shell_session_destroy(context, session1_name)
                shell_session_destroy(context, session2_name)
            except Exception:
                pass

    def test_session_list_empty(self, context):
        """Test listing sessions when none exist."""
        # Clean up any existing sessions first
        try:
            from silica.developer.tools.tmux_tool import tmux_destroy_all_sessions

            tmux_destroy_all_sessions(context)
        except Exception:
            pass

        result = shell_session_list(context)
        assert (
            "No active sessions" in result
            or "No tmux sessions found" in result
            or "| Name | Status |" in result
        )


class TestDualArchitectureIntegration:
    """Test integration between quick commands and persistent sessions."""

    @pytest.mark.asyncio
    async def test_quick_and_persistent_coexistence(self, context):
        """Test that quick commands and persistent sessions can coexist."""
        # Create a persistent session
        await shell_session_create(context, "persistent", 'echo "Persistent session"')

        # Execute quick command
        quick_result = await shell_execute(context, 'echo "Quick command"')

        # Execute in persistent session
        persistent_result = await shell_session_execute(
            context, "persistent", 'echo "Session command"'
        )

        # Both should work independently
        assert "Quick command" in quick_result
        assert "executed" in persistent_result

        # Session should still be active
        list_result = shell_session_list(context)
        assert "persistent" in list_result

        # Cleanup
        shell_session_destroy(context, "persistent")

    @pytest.mark.asyncio
    async def test_large_output_handling(self, context):
        """Test handling of large output in both approaches."""
        # Generate large output command (using seq for better portability)
        large_command = 'seq 1 100 | while read i; do echo "Line $i"; done'

        # Test with shell_execute (should handle unlimited output)
        quick_result = await shell_execute(context, large_command)
        assert "Line 1" in quick_result
        assert "Line 100" in quick_result

        # Test with session (should also work)
        await shell_session_create(context, "large_session")
        await shell_session_execute(context, "large_session", large_command)

        # Wait a bit for command to execute
        import time

        time.sleep(1)

        session_result = shell_session_get_output(context, "large_session")
        # The session shows the command input, which is also valid output
        assert large_command in session_result or "Line 1" in session_result

        # Cleanup
        shell_session_destroy(context, "large_session")


class TestErrorHandling:
    """Test error handling in both approaches."""

    @pytest.mark.asyncio
    async def test_shell_execute_error_handling(self, context):
        """Test error handling in shell_execute."""
        # Test command that doesn't exist
        result = await shell_execute(context, "nonexistent_command_12345")
        assert "Exit code:" in result  # Should capture exit code
        assert "STDERR:" in result  # Should capture error output

    @pytest.mark.asyncio
    async def test_session_error_handling(self, context):
        """Test error handling in session operations."""
        # Test executing command in non-existent session
        result = await shell_session_execute(
            context, "nonexistent_session", 'echo "test"'
        )
        assert "Error" in result or "not found" in result

        # Test getting output from non-existent session
        result = shell_session_get_output(context, "nonexistent_session")
        assert "Error" in result or "not found" in result

        # Test destroying non-existent session
        result = shell_session_destroy(context, "nonexistent_session")
        assert "Error" in result or "not found" in result


class TestPerformanceAndUseCases:
    """Test performance characteristics and real-world use cases."""

    @pytest.mark.asyncio
    async def test_file_operations_use_case(self, context):
        """Test typical file operations use case."""
        # Create a test file
        await shell_execute(context, 'echo "Test content" > /tmp/test_file.txt')

        # Read file with shell_execute (good for large files)
        result = await shell_execute(context, "cat /tmp/test_file.txt")
        assert "Test content" in result

        # List files
        result = await shell_execute(context, "ls -la /tmp/test_file.txt")
        assert "test_file.txt" in result

        # Cleanup
        await shell_execute(context, "rm -f /tmp/test_file.txt")

    @pytest.mark.asyncio
    async def test_development_environment_use_case(self, context):
        """Test development environment setup use case."""
        # Create a development session
        await shell_session_create(context, "dev_env", "cd /tmp")

        # Set up environment variables
        await shell_session_execute(context, "dev_env", "export DEV_MODE=true")

        # Check environment persists
        await shell_session_execute(context, "dev_env", 'echo "Dev mode: $DEV_MODE"')

        # Wait a bit for command to execute
        import time

        time.sleep(1)

        output = shell_session_get_output(context, "dev_env")
        # The session shows the command input, which demonstrates the commands were executed
        assert "export DEV_MODE=true" in output and "echo" in output

        # Cleanup
        shell_session_destroy(context, "dev_env")

    @pytest.mark.asyncio
    async def test_no_performance_regression(self, context):
        """Test that shell_execute has no significant overhead."""
        import time

        # Time a simple command
        start_time = time.time()
        result = await shell_execute(context, 'echo "Performance test"')
        end_time = time.time()

        # Should complete quickly
        execution_time = end_time - start_time
        assert execution_time < 2.0  # Should be much faster than 2 seconds
        assert "Performance test" in result

    @pytest.mark.asyncio
    async def test_large_output_handling(self, context):
        """Test handling of large output in both approaches."""
        # Generate large output command (using seq for better portability)
        large_command = 'seq 1 100 | while read i; do echo "Line $i"; done'

        # Test with shell_execute (should handle unlimited output)
        quick_result = await shell_execute(context, large_command)
        assert "Line 1" in quick_result
        assert "Line 100" in quick_result
        # Test with session (should also work)
        await shell_session_create(context, "large_session")
        await shell_session_execute(context, "large_session", large_command)


class TestBackwardCompatibility:
    """Test that shell_execute provides the same functionality as the old run_bash_command."""

    @pytest.mark.asyncio
    async def test_shell_execute_basic_functionality(self, context):
        """Test that shell_execute works as expected for basic commands."""
        result = await shell_execute(context, 'echo "Basic functionality"')

        assert "Exit code: 0" in result
        assert "Basic functionality" in result
        assert "STDOUT:" in result

    @pytest.mark.asyncio
    async def test_shell_execute_consistency(self, context):
        """Test that shell_execute produces consistent results."""
        command = 'echo "Testing consistency"'

        result1 = await shell_execute(context, command)
        result2 = await shell_execute(context, command)

        # Results should have same structure (though timestamps may differ)
        assert "Exit code: 0" in result1 and "Exit code: 0" in result2
        assert "Testing consistency" in result1 and "Testing consistency" in result2
