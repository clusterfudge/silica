import contextlib
from abc import ABC, abstractmethod
from typing import Dict, Any, List

from silica.developer.sandbox import SandboxMode


class UserInterface(ABC):
    @abstractmethod
    def handle_assistant_message(self, message: str) -> None:
        """
        Handle and display a new message from the assistant.

        :param message: The message from the assistant
        """

    @abstractmethod
    def handle_system_message(self, message: str, markdown=True, live=None) -> None:
        """
        Handle and display a new system message.

        :param message: The message
        :param markdown: Whether to render as markdown
        :param live: Optional Rich Live instance for real-time updates
        """

    @abstractmethod
    def permission_callback(
        self,
        action: str,
        resource: str,
        sandbox_mode: SandboxMode,
        action_arguments: Dict | None,
    ) -> bool:
        """
        :param action:
        :param resource:
        :param sandbox_mode:
        :param action_arguments:
        :return:
        """

    @abstractmethod
    def permission_rendering_callback(
        self,
        action: str,
        resource: str,
        action_arguments: Dict | None,
    ) -> None:
        """
        :param action:
        :param resource:
        :param action_arguments:
        :return: None
        """

    @abstractmethod
    def handle_tool_use(
        self,
        tool_name: str,
        tool_params: Dict[str, Any],
    ):
        """
        Handle and display information about a tool being used, optionally check for permissions.

        :param tool_name: The name of the tool being used
        :param tool_params: The parameters passed to the tool
        """

    @abstractmethod
    def handle_tool_result(self, name: str, result: Dict[str, Any], live=None) -> None:
        """
        Handle and display the result of a tool use.

        :param name:  The name of the original tool invocation
        :param result: The result returned by the tool
        :param live: Optional Rich Live instance for real-time updates
        """

    @abstractmethod
    async def get_user_input(self, prompt: str = "") -> str:
        """
        Get input from the user.

        :param prompt: An optional prompt to display to the user
        :return: The user's input as a string
        """

    @abstractmethod
    def handle_user_input(self, user_input: str) -> str:
        """
        Handle and display input from the user

        :param user_input: the input from the user
        """

    @abstractmethod
    def display_token_count(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        total_cost: float,
        cached_tokens: int | None = None,
        conversation_size: int | None = None,
        context_window: int | None = None,
        thinking_tokens: int | None = None,
        thinking_cost: float | None = None,
    ) -> None:
        """
        Display token count information.

        :param prompt_tokens: Number of tokens in the prompt
        :param completion_tokens: Number of tokens in the completion
        :param total_tokens: Total number of tokens
        :param total_cost: Total cost of the operation
        :param cached_tokens: Number of tokens read from cache
        :param conversation_size: Current size of the conversation in tokens
        :param context_window: Total context window size for the current model
        :param thinking_tokens: Number of thinking tokens used
        :param thinking_cost: Cost of thinking tokens
        """

    @abstractmethod
    def display_welcome_message(self) -> None:
        """
        Display a welcome message to the user.
        """

    @abstractmethod
    def status(
        self, message: str, spinner: str = None
    ) -> contextlib.AbstractContextManager:
        """
        Display a status message to the user.
        :param message:
        :param spinner:
        :return:
        """

    @abstractmethod
    def bare(self, message: str | Any, live=None) -> None:
        """
        Display bare message to the user
        :param message:
        :param live: Optional Rich Live instance for real-time updates
        :return:
        """

    def handle_thinking_content(
        self, content: str, tokens: int, cost: float, collapsed: bool = True
    ) -> None:
        """
        Handle and display thinking content from the model.

        :param content: The thinking content
        :param tokens: Number of thinking tokens used
        :param cost: Cost of the thinking tokens
        :param collapsed: Whether to display in collapsed format (default: True)
        """
        # Default implementation does nothing - subclasses can override

    def update_thinking_status(self, tokens: int, budget: int, cost: float) -> None:
        """
        Update the status display with thinking progress.

        :param tokens: Current number of thinking tokens used
        :param budget: Total thinking token budget
        :param cost: Current cost of thinking tokens
        """
        # Default implementation does nothing - subclasses can override

    async def get_user_choice(self, question: str, options: List[str]) -> str:
        """
        Present multiple options to the user and get their selection.

        This method renders an interactive selector in the terminal with the
        given options. A "Say something else..." option is automatically
        added at the end, allowing the user to provide free-form text input.

        :param question: The question or prompt to display
        :param options: List of option strings to choose from
        :return: The user's selection or custom text input
        """
        # Default implementation falls back to get_user_input
        # Subclasses can override for interactive selector support
        options_text = "\n".join(f"  {i + 1}. {opt}" for i, opt in enumerate(options))
        options_text += f"\n  {len(options) + 1}. Say something else..."

        prompt = f"{question}\n\n{options_text}\n\nEnter choice (number or text): "
        return await self.get_user_input(prompt)

    async def get_session_choice(self, sessions: List[Dict[str, Any]]) -> str | None:
        """
        Present an interactive selector for session resumption.

        This method displays sessions with their metadata and allows the user
        to select one to resume. Unlike get_user_choice, this does not include
        a "Say something else..." option.

        :param sessions: List of session dictionaries with metadata
        :return: Selected session ID, or None if cancelled
        """
        # Default implementation falls back to get_user_choice
        # Subclasses can override for better formatting
        if not sessions:
            return None

        options = []
        for session in sessions:
            short_id = session.get("session_id", "")[:8]
            msg_count = session.get("message_count", 0)
            first_msg = session.get("first_message", "")
            if first_msg and len(first_msg) > 40:
                first_msg = first_msg[:37] + "..."
            option = f"[{short_id}] ({msg_count} msgs)"
            if first_msg:
                option += f' "{first_msg}"'
            options.append(option)

        result = await self.get_user_choice("Select a session to resume:", options)

        if result == "cancelled":
            return None

        # Find which option was selected
        for i, option in enumerate(options):
            if result == option:
                return sessions[i]["session_id"]

        # User typed something else - return as session ID
        return result if result else None
