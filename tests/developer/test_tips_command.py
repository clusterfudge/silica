"""
Tests for the /tips command functionality
"""

from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode
from silica.developer.toolbox import Toolbox
from silica.developer.hdev import CLIUserInterface
from rich.console import Console


class TestTipsCommand:
    """Test the /tips command functionality"""

    def test_tips_command_registration(self):
        """Test that the /tips command is properly registered"""
        console = Console()

        context = AgentContext.create(
            model_spec={
                "title": "Test Model",
                "max_tokens": 4000,
                "context_window": 8000,
                "pricing": {"input": 0.001, "output": 0.002},
            },
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=CLIUserInterface(console, SandboxMode.ALLOW_ALL),
        )

        toolbox = Toolbox(context)

        # Check if tips is registered
        assert "tips" in toolbox.local, "Tips command not found in toolbox.local"

        # Check the docstring
        expected_docstring = "Show usage tips and tricks"
        actual_docstring = toolbox.local["tips"]["docstring"]
        assert (
            actual_docstring == expected_docstring
        ), f"Expected '{expected_docstring}', got '{actual_docstring}'"

        # Test that the function exists and is callable
        tips_func = toolbox.local["tips"]["invoke"]
        assert callable(tips_func), "Tips function is not callable"

    def test_tips_command_content(self):
        """Test that the tips command contains expected content"""
        console = Console()

        context = AgentContext.create(
            model_spec={
                "title": "Test Model",
                "max_tokens": 4000,
                "context_window": 8000,
                "pricing": {"input": 0.001, "output": 0.002},
            },
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=CLIUserInterface(console, SandboxMode.ALLOW_ALL),
        )

        toolbox = Toolbox(context)

        # Mock user interface to capture output
        class MockUserInterface:
            def __init__(self):
                self.messages = []

            def handle_system_message(self, message, markdown=True):
                self.messages.append(message)

        mock_ui = MockUserInterface()

        # Call the tips function
        toolbox._tips(mock_ui, context.sandbox, "", [])

        # Check that we got output
        assert (
            len(mock_ui.messages) == 1
        ), "Expected one system message from tips command"

        tips_output = mock_ui.messages[0]

        # Check for expected content sections
        expected_sections = [
            "Usage Tips and Tricks",
            "Multi-line Input:",
            "Output Formatting:",
            "File Management:",
            "Command Shortcuts:",
            "Session Management:",
            "Efficiency Tips:",
            "File References:",
            "Advanced Features:",
        ]

        for section in expected_sections:
            assert (
                section in tips_output
            ), f"Expected section '{section}' not found in tips output"

        # Check for specific tips that were moved from welcome message
        moved_tips = [
            "Start with `{` on a new line",
            "Markdown formatting",
            "syntax highlighted",
        ]

        for tip in moved_tips:
            assert tip in tips_output, f"Expected tip '{tip}' not found in tips output"

    def test_help_command_still_works(self):
        """Test that the help command still works after adding tips"""
        console = Console()

        context = AgentContext.create(
            model_spec={
                "title": "Test Model",
                "max_tokens": 4000,
                "context_window": 8000,
                "pricing": {"input": 0.001, "output": 0.002},
            },
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=CLIUserInterface(console, SandboxMode.ALLOW_ALL),
        )

        toolbox = Toolbox(context)

        # Check that help is still registered
        assert "help" in toolbox.local, "Help command not found in toolbox.local"

        # Test that the function exists and is callable
        help_func = toolbox.local["help"]["invoke"]
        assert callable(help_func), "Help function is not callable"

        # Mock user interface to capture output
        class MockUserInterface:
            def __init__(self):
                self.messages = []

            def handle_system_message(self, message, markdown=True):
                self.messages.append(message)

        mock_ui = MockUserInterface()

        # Call the help function
        toolbox._help(mock_ui, context.sandbox, "", [])

        # Check that we got output
        assert (
            len(mock_ui.messages) == 1
        ), "Expected one system message from help command"

        help_output = mock_ui.messages[0]

        # Check that tips is mentioned in help output
        assert "/tips" in help_output, "Tips command should be mentioned in help output"
        assert (
            "Show usage tips and tricks" in help_output
        ), "Tips description should be in help output"

    def test_simplified_welcome_message(self):
        """Test that the welcome message is simplified and lowercase"""
        import io

        # Capture the welcome message output
        string_buffer = io.StringIO()
        console = Console(file=string_buffer, force_terminal=False)

        ui = CLIUserInterface(console, SandboxMode.ALLOW_ALL)
        ui.display_welcome_message()

        # Get the captured output
        welcome_output = string_buffer.getvalue()

        # Check that the simplified content is present
        expected_content = (
            "welcome to silica. /help for commands, /tips to get started."
        )
        assert (
            expected_content in welcome_output
        ), f"Expected simplified content not found: {expected_content}"

        # Check that old verbose content is gone
        old_content = [
            "Welcome to the silica Developer CLI",
            "Your personal coding assistant powered by AI",
            "## Welcome",
            "Type `/help` to see available commands or `/tips` for usage tips",
        ]

        for old in old_content:
            assert old not in welcome_output, f"Old verbose content still found: {old}"
