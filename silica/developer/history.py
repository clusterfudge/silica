#!/usr/bin/env python3
"""
History Viewer for Heare Developer Conversations.
Provides an interactive CLI view of conversation history using Rich.
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich import box
from rich.prompt import Prompt


class ConversationViewer:
    """Interactive viewer for conversation history using Rich."""

    # Define colors and styles for different elements
    STYLES = {
        "user_message": "green",
        "assistant_message": "blue",
        "tool_use": "yellow",
        "tool_result": "cyan",
        "selected": "yellow",
        "highlight": "bold magenta",
        "header": "bold cyan",
        "token_count": "bright_black",
        "error": "bold red",
        "success": "bold green",
        "warning": "bold yellow",
        "help": "italic bright_white",
    }

    def __init__(self, history_dir: Optional[str] = None):
        """Initialize the conversation viewer.

        Args:
            history_dir: Directory containing conversation history files.
                         If None, uses tests/data/history by default.
        """
        self.console = Console()
        self.history_dir = (
            Path(history_dir) if history_dir else Path("tests/data/history")
        )
        self.conversations = {}
        self.current_conversation_id = None
        self.current_conversation = None
        self.expanded_messages = set()  # Track which messages are expanded
        self.selected_index = 0  # Currently selected message index
        self.page_size = 10  # Number of messages to show at once
        self.current_page = 0  # Current page in pagination

    def load_conversations(self) -> None:
        """Load all available conversations from the history directory."""
        if not self.history_dir.exists():
            self.console.print(
                f"History directory not found: {self.history_dir}", style="bold red"
            )
            return

        # Clear existing conversations
        self.conversations = {}

        for conversation_dir in self.history_dir.iterdir():
            if conversation_dir.is_dir():
                root_file = conversation_dir / "root.json"
                if root_file.exists():
                    try:
                        with open(root_file, "r") as f:
                            conversation_data = json.load(f)
                            self.conversations[conversation_dir.name] = (
                                conversation_data
                            )
                    except (json.JSONDecodeError, IOError) as e:
                        self.console.print(
                            f"Error loading {root_file}: {e}", style="bold red"
                        )

    def list_conversations(self) -> None:
        """Display a list of available conversations."""
        if not self.conversations:
            self.console.print("No conversations found.", style="bold yellow")
            return

        table = Table(title="Available Conversations", box=box.ROUNDED)
        table.add_column("ID", style="cyan")
        table.add_column("Messages", style="green")
        table.add_column("Model", style="blue")

        for conv_id, conv_data in self.conversations.items():
            message_count = len(conv_data.get("messages", []))
            model = conv_data.get("model_spec", {}).get("title", "Unknown")

            table.add_row(conv_id, str(message_count), model)

        self.console.print(table)

    def load_conversation(self, conversation_id: str) -> bool:
        """Load a specific conversation by ID.

        Args:
            conversation_id: UUID of the conversation to load

        Returns:
            bool: True if loaded successfully, False otherwise
        """
        # Find the first conversation that starts with the given ID prefix
        matching_ids = [
            cid for cid in self.conversations.keys() if cid.startswith(conversation_id)
        ]

        if not matching_ids:
            self.console.print(
                f"Conversation {conversation_id} not found.", style="bold red"
            )
            return False

        full_id = matching_ids[0]
        self.current_conversation_id = full_id
        self.current_conversation = self.conversations[full_id]
        self.expanded_messages = set()  # Reset expanded messages
        self.selected_index = 0  # Reset selection
        return True

    def _format_message(
        self,
        message: Dict[str, Any],
        index: int,
        is_selected: bool,
        expanded: bool = False,
    ) -> Panel:
        """Format a message for display.

        Args:
            message: Message data dictionary
            index: Message index in the conversation
            is_selected: Whether this message is currently selected
            expanded: Whether to show expanded view

        Returns:
            Panel: Rich panel containing formatted message
        """
        role = message.get("role", "unknown")

        # Extract simple text content if it's a string, or handle complex content
        if isinstance(message.get("content"), str):
            content = message["content"]
        elif isinstance(message.get("content"), list):
            # Handle content that is a list of components
            content_parts = []
            for item in message["content"]:
                if isinstance(item, dict) and "text" in item:
                    content_parts.append(item["text"])
                elif (
                    isinstance(item, dict)
                    and "type" in item
                    and item["type"] == "tool_use"
                ):
                    content_parts.append(f"[Tool Use: {item.get('name', 'unnamed')}]")
                elif (
                    isinstance(item, dict)
                    and "type" in item
                    and item["type"] == "tool_result"
                ):
                    content_parts.append("[Tool Result]")
            content = "\n".join(content_parts)
        else:
            content = str(message.get("content", "No content"))

        # Border style based on role and selection
        if is_selected:
            border_style = "yellow" if role == "user" else "yellow"
        else:
            border_style = "green" if role == "user" else "blue"

        # Expanded/collapsed indicator
        expansion_status = "[-]" if expanded else "[+]"

        # Create summary view (collapsed)
        if not expanded:
            # Truncate content for summary view
            if len(content) > 80:
                content_preview = content[:77] + "..."
            else:
                content_preview = content

            text = Text()
            text.append(f"{index}. ", style="bold cyan")
            text.append(
                f"{role}: ", style="bold green" if role == "user" else "bold blue"
            )
            text.append(content_preview.replace("\n", " "))

            return Panel(
                text,
                title=f"{expansion_status} Message {index}",
                title_align="left",
                border_style=border_style,
                padding=(1, 2),
            )

        # Create expanded view
        else:
            # Create a rich layout for the expanded view
            message_table = Table(box=None, padding=0, expand=True)
            message_table.add_column("Property", style="cyan", width=12)
            message_table.add_column("Value", style="white", ratio=3)

            message_table.add_row("Role", role)

            # Handle complex content
            if isinstance(message.get("content"), list):
                text = Text()
                for item in message["content"]:
                    if isinstance(item, dict):
                        if "text" in item:
                            text.append(item["text"] + "\n\n", style="white")
                        elif "type" in item and item["type"] == "tool_use":
                            tool_name = item.get("name", "unnamed")
                            text.append(f"[Tool Use: {tool_name}]\n", style="yellow")
                            if "input" in item:
                                text.append(
                                    json.dumps(item["input"], indent=2) + "\n\n",
                                    style="bright_black",
                                )
                        elif "type" in item and item["type"] == "tool_result":
                            text.append("[Tool Result]\n", style="green")
                            if "content" in item:
                                text.append(
                                    item["content"] + "\n\n", style="bright_black"
                                )
                message_table.add_row("Content", text)
            else:
                # If content is simple, show it with word wrap
                # Use rich markdown renderer instead of syntax highlighter
                from rich.markdown import Markdown

                if role == "assistant":
                    # Use markdown for assistant content
                    content_display = Markdown(content, word_wrap=True)
                else:
                    # Use plain text for user content
                    content_display = Text(content, style="default")

                message_table.add_row("Content", content_display)

            return Panel(
                message_table,
                title=f"{expansion_status} Message {index}",
                title_align="left",
                border_style=border_style,
                padding=(1, 2),
            )

    def _calculate_token_usage(self) -> Tuple[int, int, float]:
        """Calculate token usage statistics for the current conversation.

        Returns:
            Tuple of (total input tokens, total output tokens, estimated cost)
        """
        if not self.current_conversation:
            return (0, 0, 0.0)

        usage_data = self.current_conversation.get("usage", [])
        total_input = sum(entry[0].get("input_tokens", 0) for entry in usage_data)
        total_output = sum(entry[0].get("output_tokens", 0) for entry in usage_data)

        # Calculate cost if pricing information is available
        model_spec = self.current_conversation.get("model_spec", {})
        pricing = model_spec.get("pricing", {})
        input_price = (
            pricing.get("input", 0) / 1000000
        )  # Convert from per-million price
        output_price = pricing.get("output", 0) / 1000000

        estimated_cost = (total_input * input_price) + (total_output * output_price)

        return (total_input, total_output, estimated_cost)

    def display_conversation(self) -> None:
        """Display the current conversation with expandable messages."""
        if not self.current_conversation:
            self.console.print("No conversation loaded.", style="bold yellow")
            return

        messages = self.current_conversation.get("messages", [])

        # Show metadata
        model_spec = self.current_conversation.get("model_spec", {})
        model_name = model_spec.get("title", "Unknown model")

        # Calculate token usage
        total_input, total_output, estimated_cost = self._calculate_token_usage()

        meta_table = Table(box=box.ROUNDED, show_header=False, expand=True)
        meta_table.add_column("Key", style="cyan")
        meta_table.add_column("Value")

        meta_table.add_row("Conversation ID", self.current_conversation_id)
        meta_table.add_row("Model", model_name)
        meta_table.add_row("Messages", str(len(messages)))
        meta_table.add_row("Input Tokens", f"{total_input:,}")
        meta_table.add_row("Output Tokens", f"{total_output:,}")
        meta_table.add_row("Est. Cost", f"${estimated_cost:.4f}")

        meta_panel = Panel(meta_table, title="Conversation Info", border_style="cyan")
        self.console.print(meta_panel)

        # Show instructions
        help_text = Text()
        help_text.append("Navigation: ", style="bold yellow")
        help_text.append("Use numbers to select message, ")
        help_text.append("↑/↓ ", style="bold cyan")
        help_text.append("to navigate, ")
        help_text.append("+/- ", style="bold cyan")
        help_text.append("to expand/collapse, ")
        help_text.append("q ", style="bold red")
        help_text.append("to quit, ")
        help_text.append("b ", style="bold green")
        help_text.append("to go back to list")

        self.console.print(Panel(help_text, border_style="yellow"))

        # Display messages
        for i, message in enumerate(messages):
            is_selected = i == self.selected_index
            is_expanded = i in self.expanded_messages
            panel = self._format_message(message, i, is_selected, expanded=is_expanded)
            self.console.print(panel)

    def run(self) -> None:
        """Run the interactive viewer with command-based navigation."""
        self.load_conversations()
        if not self.conversations:
            self.console.print("No conversations found.", style="bold red")
            return

        exit_app = False

        while not exit_app:
            self.console.clear()
            self.list_conversations()

            choice = Prompt.ask(
                "\nEnter conversation ID (prefix), or [bold red]q[/bold red] to quit",
                default="q",
            )

            if choice.lower() == "q":
                exit_app = True
                continue

            if not self.load_conversation(choice):
                continue

            self.view_conversation()

    def view_conversation(self) -> None:
        """View and interact with a specific conversation."""
        if not self.current_conversation:
            return

        messages = self.current_conversation.get("messages", [])
        back_to_list = False

        while not back_to_list:
            self.console.clear()
            self.display_conversation()

            prompt_text = "\nEnter command ("
            prompt_text += "[bold cyan]↑/↓[/bold cyan] or message #, "
            prompt_text += "[bold green]+/-[/bold green] to expand/collapse, "
            prompt_text += (
                "[bold red]b[/bold red] for back, [bold red]q[/bold red] to quit)"
            )

            command = Prompt.ask(prompt_text)

            if command.lower() == "q":
                sys.exit(0)
            elif command.lower() == "b":
                back_to_list = True
            elif command == "+":
                # Expand current message
                self.expanded_messages.add(self.selected_index)
            elif command == "-":
                # Collapse current message
                if self.selected_index in self.expanded_messages:
                    self.expanded_messages.remove(self.selected_index)
            elif command.lower() == "up" or command == "↑":
                # Navigate up
                if self.selected_index > 0:
                    self.selected_index -= 1
            elif command.lower() == "down" or command == "↓":
                # Navigate down
                if self.selected_index < len(messages) - 1:
                    self.selected_index += 1
            elif command.isdigit():
                # Select message by number
                msg_idx = int(command)
                if 0 <= msg_idx < len(messages):
                    self.selected_index = msg_idx


def main():
    """Main entry point for the conversation viewer."""
    console = Console()

    # Parse command line arguments
    import argparse

    parser = argparse.ArgumentParser(
        description="Interactive conversation history viewer"
    )
    parser.add_argument("--dir", "-d", help="Directory containing conversation history")
    args = parser.parse_args()

    try:
        viewer = ConversationViewer(args.dir)
        viewer.run()
    except KeyboardInterrupt:
        console.print("\nExiting...", style="bold yellow")
    except Exception as e:
        console.print(f"Error: {e}", style="bold red")
        import traceback

        console.print(traceback.format_exc(), style="red")


if __name__ == "__main__":
    main()
