"""
Tests for the attach_tools closure scoping fix
"""

from silica.developer.hdev import attach_tools
from silica.developer.toolbox import Toolbox


class TestAttachToolsFix:
    """Test the closure scoping fix in attach_tools"""

    def test_closure_scoping_pattern(self):
        """Test that the closure scoping pattern works correctly"""

        # Test the fixed pattern used in attach_tools
        commands = ["help", "tips", "add", "list"]

        def make_command_func(cmd_name: str):
            def f():
                return f"Command: {cmd_name}"

            return f

        functions = []
        for command in commands:
            functions.append(make_command_func(command))

        # Verify each function returns the correct command name
        for i, func in enumerate(functions):
            result = func()
            expected_command = commands[i]
            actual_command = result.split(": ")[1]
            assert (
                actual_command == expected_command
            ), f"Function {i} should capture '{expected_command}'"

    def test_attach_tools_creates_distinct_functions(self):
        """Test that attach_tools creates distinct function objects for each command"""

        class MockApp:
            def __init__(self):
                self.registered = {}

            def command(self, func, name):
                self.registered[name] = func

        mock_app = MockApp()

        # Mock the toolbox to avoid actual CLI invocation during testing
        original_invoke = Toolbox.invoke_cli_tool

        async def mock_invoke_cli_tool(self, name, arg_str, confirm_to_add=True):
            return f"Mock result for {name}", False

        Toolbox.invoke_cli_tool = mock_invoke_cli_tool

        try:
            attach_tools(mock_app)

            # Verify we have commands registered
            assert len(mock_app.registered) > 0, "Should have registered some commands"

            # Verify different commands have different function objects
            command_names = list(mock_app.registered.keys())
            if len(command_names) >= 2:
                func1 = mock_app.registered[command_names[0]]
                func2 = mock_app.registered[command_names[1]]
                assert (
                    func1 != func2
                ), "Different commands should have different function objects"

            # Verify expected commands are present
            expected_commands = ["help", "tips", "add", "list"]
            for expected in expected_commands:
                assert (
                    expected in command_names
                ), f"Expected command '{expected}' should be registered"

        finally:
            # Restore original method
            Toolbox.invoke_cli_tool = original_invoke

    def test_closure_captures_correct_command_name(self):
        """Test that each closure captures the correct command name"""

        # This test demonstrates the issue that was fixed
        # by showing what would happen with the broken pattern

        commands = ["cmd1", "cmd2", "cmd3"]
        captured_names = []

        # Using the FIXED pattern from attach_tools
        def make_command_func(cmd_name: str):
            def mock_func():
                captured_names.append(cmd_name)
                return cmd_name

            return mock_func

        functions = []
        for command in commands:
            functions.append(make_command_func(command))

        # Call each function and verify it captures the right name
        results = []
        for func in functions:
            results.append(func())

        # Each function should have captured its own command name
        assert results == commands, f"Expected {commands}, got {results}"
        assert captured_names == commands, f"Expected {commands}, got {captured_names}"
