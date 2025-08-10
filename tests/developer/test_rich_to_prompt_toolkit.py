import unittest
from rich.text import Text
from rich.panel import Panel
from prompt_toolkit.formatted_text import ANSI

from silica.developer.hdev import rich_to_prompt_toolkit


class TestRichToPromptToolkit(unittest.TestCase):
    def test_simple_text_conversion(self):
        """Test conversion of simple text without formatting"""
        # Create a simple text string
        text = "Hello, world!"

        # Convert to Rich format
        rich_text = Text(text)

        # Convert to prompt_toolkit format
        pt_text = rich_to_prompt_toolkit(rich_text)

        # Validate the conversion is an ANSI object
        self.assertIsInstance(pt_text, ANSI)

        # The content should contain the original text
        self.assertIn(text, pt_text.value)

    def test_styled_text_produces_ansi_codes(self):
        """Test that styled Rich text is converted to ANSI escape codes"""
        # Create styled Rich text
        styled_text = Text("Bold text", style="bold red")

        # Convert to prompt_toolkit format
        pt_text = rich_to_prompt_toolkit(styled_text)

        # Validate the conversion is an ANSI object
        self.assertIsInstance(pt_text, ANSI)

        # ANSI codes should be present in the output
        self.assertIn(
            "\x1b[",
            pt_text.value,
            "Output should contain ANSI escape codes but found: " + repr(pt_text.value),
        )

        # The original text content should be preserved
        self.assertIn(
            "Bold text",
            "".join(ch for ch in pt_text.value if ch.isalpha() or ch.isspace()),
        )

    def test_rich_markup_produces_ansi(self):
        """Test that Rich markup is properly converted to ANSI escape sequences"""
        # Create a string with Rich markup
        rich_markup = "[bold red]Alert![/bold red] This is [blue]important[/blue]."

        # Convert to prompt_toolkit format
        pt_text = rich_to_prompt_toolkit(rich_markup)

        # Validate the conversion is an ANSI object
        self.assertIsInstance(pt_text, ANSI)

        # ANSI codes should be present in the output
        self.assertIn(
            "\x1b[",
            pt_text.value,
            "Output should contain ANSI escape codes but found: " + repr(pt_text.value),
        )

        # The original text content should be preserved
        plain_text = "".join(
            ch for ch in pt_text.value if ch.isalnum() or ch.isspace() or ch in ":.!"
        )
        for text in ["Alert", "This is", "important"]:
            self.assertIn(text, plain_text)

    def test_panel_produces_ansi(self):
        """Test that Rich Panel objects are converted to ANSI escape sequences"""
        # Create a Rich Panel
        panel = Panel(
            "[bold]Important[/bold] information",
            title="[red]Alert[/red]",
            border_style="green",
        )

        # Convert to prompt_toolkit format
        pt_text = rich_to_prompt_toolkit(panel)

        # Validate the conversion is an ANSI object
        self.assertIsInstance(pt_text, ANSI)

        # ANSI codes should be present in the output
        self.assertIn(
            "\x1b[",
            pt_text.value,
            "Output should contain ANSI escape codes but found: " + repr(pt_text.value),
        )

        # The panel content and title should be preserved
        # We just need to verify individual terms are present, since the panel formatting
        # can vary and might split up words with control characters
        self.assertIn("Alert", pt_text.value)
        self.assertIn("Important", pt_text.value)
        self.assertIn("information", pt_text.value)


if __name__ == "__main__":
    unittest.main()
