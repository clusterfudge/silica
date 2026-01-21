"""Hybrid User Interface - presents prompts in both CLI and Agent Island.

When Agent Island is available, blocking operations (permissions, prompts, etc.)
are presented in BOTH interfaces simultaneously. The first response wins, and
the other interface is dismissed.

When Agent Island is not available, falls back to CLI-only behavior.
"""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4
import contextlib

from .user_interface import UserInterface, PermissionResult
from .sandbox import SandboxMode, DoSomethingElseError


# Default socket path for Agent Island
DEFAULT_SOCKET_PATH = Path("~/.agent-island/agent.sock").expanduser()


class HybridUserInterface(UserInterface):
    """User interface that presents in both CLI and Agent Island.

    For blocking operations (permissions, prompts, etc.):
    - If Agent Island is connected: present in BOTH, first response wins
    - If not connected: CLI only

    For non-blocking events (messages, tool results):
    - Always show in CLI
    - Also send to Island if connected (fire-and-forget)
    """

    def __init__(
        self,
        cli_interface: "UserInterface",
        socket_path: Path = DEFAULT_SOCKET_PATH,
    ):
        """Initialize hybrid interface.

        Args:
            cli_interface: The CLI user interface to wrap
            socket_path: Path to Agent Island socket
        """
        self.cli = cli_interface
        self.socket_path = socket_path
        self._island = None  # IslandClient, lazily created
        self._island_available = None  # None = not checked, True/False = checked

    @property
    def hybrid_mode(self) -> bool:
        """Check if we're in hybrid mode (Island connected)."""
        return self._island is not None and self._island.connected

    async def connect_to_island(self) -> bool:
        """Try to connect to Agent Island.

        Returns:
            True if connected, False otherwise.
        """
        if self._island_available is False:
            return False

        if self._island is not None and self._island.connected:
            return True

        # Check if socket exists
        if not self.socket_path.exists():
            self._island_available = False
            return False

        try:
            # Import here to avoid circular dependency and allow running without client installed
            from agent_island import IslandClient

            self._island = IslandClient(socket_path=str(self.socket_path))
            connected = await self._island.connect()

            if connected:
                self._island_available = True
                return True
            else:
                self._island_available = False
                self._island = None
                return False

        except ImportError:
            # agent_island client not installed
            self._island_available = False
            return False
        except Exception:
            self._island_available = False
            self._island = None
            return False

    async def disconnect_from_island(self) -> None:
        """Disconnect from Agent Island."""
        if self._island is not None:
            try:
                await self._island.disconnect()
            except Exception:
                pass
            self._island = None

    async def register_session(
        self,
        session_id: str,
        working_directory: str,
        model: Optional[str] = None,
        persona: Optional[str] = None,
    ) -> bool:
        """Register session with Agent Island.

        Args:
            session_id: Unique session identifier
            working_directory: Current working directory
            model: Optional model name
            persona: Optional persona name

        Returns:
            True if registered (or Island not available)
        """
        if not self.hybrid_mode:
            return True  # Nothing to register

        try:
            return await self._island.register_session(
                session_id=session_id,
                working_directory=working_directory,
                model=model,
                persona=persona,
            )
        except Exception:
            return True  # Don't fail if registration fails

    async def unregister_session(self, session_id: str) -> bool:
        """Unregister session from Agent Island."""
        if not self.hybrid_mode:
            return True

        try:
            return await self._island.unregister_session(session_id)
        except Exception:
            return True

    # ========== Blocking Operations (Race Pattern) ==========

    def permission_callback(
        self,
        action: str,
        resource: str,
        sandbox_mode: SandboxMode,
        action_arguments: Dict | None,
        group: Optional[str] = None,
    ) -> PermissionResult:
        """Permission callback - presents in both interfaces if hybrid mode.

        Uses threading to run both CLI and Island permission requests concurrently.
        """

        # Try to connect if not already
        if self._island_available is None:
            # Lazy check - try connecting in current context
            try:
                loop = asyncio.get_running_loop()
                # Schedule connection check
                future = asyncio.run_coroutine_threadsafe(
                    self.connect_to_island(), loop
                )
                try:
                    future.result(timeout=2.0)  # Brief timeout
                except Exception:
                    pass
            except RuntimeError:
                # No running loop
                try:
                    asyncio.get_event_loop().run_until_complete(
                        self.connect_to_island()
                    )
                except Exception:
                    pass

        # If not in hybrid mode, use CLI only
        if not self.hybrid_mode:
            return self.cli.permission_callback(
                action, resource, sandbox_mode, action_arguments, group
            )

        # Hybrid mode: use threading to race
        return self._permission_callback_threaded(
            action, resource, sandbox_mode, action_arguments, group
        )

    def _permission_callback_threaded(
        self,
        action: str,
        resource: str,
        sandbox_mode: SandboxMode,
        action_arguments: Dict | None,
        group: Optional[str] = None,
    ) -> PermissionResult:
        """Threaded implementation of permission callback race."""
        import threading

        dialog_id = str(uuid4())
        result_holder = {"value": None, "source": None}
        done_event = threading.Event()

        # Parse shell commands for Island
        shell_parsed = None
        if action == "shell":
            try:
                from .tools.shell_parser import parse_shell_command

                parsed = parse_shell_command(resource)
                shell_parsed = {
                    "commands": parsed.commands,
                    "is_simple": parsed.is_simple,
                    "parse_error": parsed.parse_error,
                }
            except Exception:
                pass

        def cli_worker():
            """CLI thread."""
            try:
                result = self.cli.permission_callback(
                    action, resource, sandbox_mode, action_arguments, group
                )
                if not done_event.is_set():
                    result_holder["value"] = result
                    result_holder["source"] = "cli"
                    done_event.set()
            except DoSomethingElseError:
                if not done_event.is_set():
                    result_holder["value"] = "do_something_else"
                    result_holder["source"] = "cli"
                    done_event.set()
            except Exception:
                if not done_event.is_set():
                    result_holder["value"] = False
                    result_holder["source"] = "cli"
                    done_event.set()

        def island_worker():
            """Island thread - creates its own client and runs async code.

            TODO: This approach has issues with the async IslandClient in a separate
            thread/event loop. The permission_request call seems to hang or fail silently.
            Need to investigate:
            1. Maybe use a synchronous/blocking client for the race
            2. Or restructure to keep Island comms on the main thread
            3. Or use process-based concurrency instead of threading
            """
            try:
                # Import the client
                from agent_island import IslandClient

                # Create new event loop for this thread
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def do_island_request():
                    # Create a fresh client for this thread
                    client = IslandClient(socket_path=str(self.socket_path))
                    if not await client.connect():
                        return None
                    try:
                        response = await client.permission_request(
                            action=action,
                            resource=resource,
                            dialog_id=dialog_id,
                            group=group,
                            details=action_arguments,
                            shell_parsed=shell_parsed,
                            hint="(or respond in terminal)",
                        )
                        return response
                    finally:
                        await client.disconnect()

                try:
                    response = loop.run_until_complete(do_island_request())
                    if response and not done_event.is_set():
                        result_holder["value"] = response.to_silica_result()
                        result_holder["source"] = "island"
                        done_event.set()
                finally:
                    loop.close()
            except Exception:
                # Island failed, let CLI win
                pass

        # Start both threads
        cli_thread = threading.Thread(target=cli_worker, daemon=True)
        island_thread = threading.Thread(target=island_worker, daemon=True)

        cli_thread.start()
        island_thread.start()

        # Wait for first response
        done_event.wait()

        # Clean up
        if result_holder["source"] == "cli":
            # Cancel Island dialog if it's still pending
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(self._island.cancel_dialog(dialog_id))
                finally:
                    loop.close()
            except Exception:
                pass
            self.cli.handle_system_message(
                "[dim]✓ Responded in terminal[/dim]", markdown=False
            )
        else:
            self.cli.handle_system_message(
                "[dim]✓ Responded in Agent Island[/dim]", markdown=False
            )

        # Handle do_something_else
        if result_holder["value"] == "do_something_else":
            raise DoSomethingElseError()

        return result_holder["value"]

    async def _permission_callback_async(
        self,
        action: str,
        resource: str,
        sandbox_mode: SandboxMode,
        action_arguments: Dict | None,
        group: Optional[str] = None,
    ) -> PermissionResult:
        """Async implementation of permission callback."""

        # Try to connect to Island if not already
        await self.connect_to_island()

        if not self.hybrid_mode:
            # CLI only
            return self.cli.permission_callback(
                action, resource, sandbox_mode, action_arguments, group
            )

        # Hybrid mode: race between CLI and Island
        dialog_id = str(uuid4())
        result_holder: Dict[str, Any] = {"value": None, "source": None}
        done_event = asyncio.Event()

        # Parse shell commands for Island
        shell_parsed = None
        if action == "shell":
            try:
                from .tools.shell_parser import parse_shell_command

                parsed = parse_shell_command(resource)
                shell_parsed = {
                    "commands": parsed.commands,
                    "is_simple": parsed.is_simple,
                    "parse_error": parsed.parse_error,
                }
            except Exception:
                pass

        async def cli_race():
            """CLI responder."""
            try:
                # Note: CLI permission_callback is synchronous
                # We run it in the default executor to not block
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None,
                    lambda: self.cli.permission_callback(
                        action, resource, sandbox_mode, action_arguments, group
                    ),
                )
                if not done_event.is_set():
                    result_holder["value"] = result
                    result_holder["source"] = "cli"
                    done_event.set()
            except DoSomethingElseError:
                if not done_event.is_set():
                    result_holder["value"] = "do_something_else"
                    result_holder["source"] = "cli"
                    done_event.set()
            except asyncio.CancelledError:
                pass
            except Exception:
                if not done_event.is_set():
                    result_holder["value"] = False
                    result_holder["source"] = "cli"
                    done_event.set()

        async def island_race():
            """Island responder."""
            try:
                response = await self._island.permission_request(
                    action=action,
                    resource=resource,
                    dialog_id=dialog_id,
                    group=group,
                    details=action_arguments,
                    shell_parsed=shell_parsed,
                    hint="(or respond in terminal)",
                )
                if not done_event.is_set():
                    result_holder["value"] = response.to_silica_result()
                    result_holder["source"] = "island"
                    done_event.set()
            except asyncio.CancelledError:
                pass
            except Exception:
                # Island failed, let CLI win
                pass

        # Show that hybrid race is starting
        self.cli.handle_system_message(
            "[dim]Starting hybrid permission race (CLI + Island)...[/dim]",
            markdown=False,
        )

        cli_task = asyncio.create_task(cli_race())
        island_task = asyncio.create_task(island_race())

        # Wait for first response
        await done_event.wait()

        # Clean up
        if result_holder["source"] == "cli":
            island_task.cancel()
            try:
                await self._island.cancel_dialog(dialog_id)
            except Exception:
                pass
            # Show confirmation in CLI
            self.cli.handle_system_message(
                "[dim]✓ Responded in terminal[/dim]", markdown=False
            )
        else:
            cli_task.cancel()
            # Show confirmation that Island was used
            self.cli.handle_system_message(
                "[dim]✓ Responded in Agent Island[/dim]", markdown=False
            )

        # Wait for tasks to complete
        await asyncio.gather(cli_task, island_task, return_exceptions=True)

        # Handle do_something_else
        if result_holder["value"] == "do_something_else":
            raise DoSomethingElseError()

        return result_holder["value"]

    def permission_rendering_callback(
        self,
        action: str,
        resource: str,
        action_arguments: Dict | None,
    ) -> None:
        """Pass through to CLI."""
        self.cli.permission_rendering_callback(action, resource, action_arguments)

    async def get_user_input(self, prompt: str = "") -> str:
        """Get user input - from CLI (Island doesn't handle free-form input yet)."""
        return await self.cli.get_user_input(prompt)

    async def get_user_choice(self, question: str, options: List[str]) -> str:
        """Present choices - in both interfaces if hybrid mode."""
        await self.connect_to_island()

        if not self.hybrid_mode:
            return await self.cli.get_user_choice(question, options)

        # Hybrid: race between interfaces
        dialog_id = str(uuid4())
        result_holder: Dict[str, Any] = {"value": None, "source": None}
        done_event = asyncio.Event()

        async def cli_race():
            try:
                result = await self.cli.get_user_choice(question, options)
                if not done_event.is_set():
                    result_holder["value"] = result
                    result_holder["source"] = "cli"
                    done_event.set()
            except asyncio.CancelledError:
                pass

        async def island_race():
            try:
                result = await self._island.select(
                    title="Selection",
                    message=question,
                    options=options,
                    allow_custom=True,
                    dialog_id=dialog_id,
                    hint="(or respond in terminal)",
                )
                if result is not None and not done_event.is_set():
                    result_holder["value"] = result
                    result_holder["source"] = "island"
                    done_event.set()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        cli_task = asyncio.create_task(cli_race())
        island_task = asyncio.create_task(island_race())

        await done_event.wait()

        if result_holder["source"] == "cli":
            island_task.cancel()
            try:
                await self._island.cancel_dialog(dialog_id)
            except Exception:
                pass
        else:
            cli_task.cancel()
            self.cli.handle_system_message(
                "[dim]✓ Responded in Agent Island[/dim]", markdown=False
            )

        await asyncio.gather(cli_task, island_task, return_exceptions=True)

        return result_holder["value"]

    async def run_questionnaire(
        self, title: str, questions: list
    ) -> dict[str, str] | None:
        """Run questionnaire - first interface to start wins."""
        await self.connect_to_island()

        if not self.hybrid_mode:
            return await self.cli.run_questionnaire(title, questions)

        # For questionnaires: present "start" in both, first to engage runs it
        # This is simpler than syncing partial progress
        dialog_id = str(uuid4())
        result_holder: Dict[str, Any] = {"interface": None}
        started_event = asyncio.Event()

        async def cli_starter():
            try:
                # Show a prompt to start
                self.cli.handle_system_message(
                    f"[bold cyan]Questionnaire: {title}[/bold cyan]\n"
                    "Press Enter to answer here (or use Agent Island window)...",
                    markdown=False,
                )
                await self.cli.get_user_input("")
                if not started_event.is_set():
                    result_holder["interface"] = "cli"
                    started_event.set()
            except asyncio.CancelledError:
                pass

        async def island_starter():
            try:
                # Send questionnaire start notification
                await self._island.alert(
                    title=f"Questionnaire: {title}",
                    message=f"Click OK to start answering {len(questions)} questions",
                    dialog_id=dialog_id,
                    hint="(or press Enter in terminal)",
                )
                if not started_event.is_set():
                    result_holder["interface"] = "island"
                    started_event.set()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        cli_task = asyncio.create_task(cli_starter())
        island_task = asyncio.create_task(island_starter())

        await started_event.wait()

        if result_holder["interface"] == "cli":
            island_task.cancel()
            try:
                await self._island.cancel_dialog(dialog_id)
            except Exception:
                pass
            # Complete in CLI
            return await self.cli.run_questionnaire(title, questions)
        else:
            cli_task.cancel()
            self.cli.handle_system_message(
                "[dim]Completing questionnaire in Agent Island...[/dim]", markdown=False
            )
            # Complete in Island
            q_dicts = []
            for q in questions:
                q_dicts.append(
                    {
                        "id": q.id,
                        "prompt": q.prompt,
                        "options": q.options,
                        "default": q.default,
                    }
                )
            return await self._island.questionnaire(
                title=title,
                questions=q_dicts,
            )

    # ========== Non-Blocking Events (Show in Both) ==========

    def handle_assistant_message(self, message: str) -> None:
        """Display assistant message in both interfaces."""
        self.cli.handle_assistant_message(message)

        if self.hybrid_mode:
            asyncio.create_task(
                self._island.notify_assistant_message(
                    content=message, format="markdown"
                )
            )

    def handle_system_message(self, message: str, markdown=True, live=None) -> None:
        """Display system message in both interfaces."""
        self.cli.handle_system_message(message, markdown=markdown, live=live)

        if self.hybrid_mode:
            asyncio.create_task(
                self._island.notify_system_message(message=message, style="info")
            )

    def handle_tool_use(self, tool_name: str, tool_params: Dict[str, Any]) -> None:
        """Display tool use in both interfaces."""
        self.cli.handle_tool_use(tool_name, tool_params)

        if self.hybrid_mode:
            asyncio.create_task(
                self._island.notify_tool_use(
                    tool_name=tool_name, tool_params=tool_params
                )
            )

    def handle_tool_result(self, name: str, result: Dict[str, Any], live=None) -> None:
        """Display tool result in both interfaces."""
        self.cli.handle_tool_result(name, result, live=live)

        if self.hybrid_mode:
            asyncio.create_task(
                self._island.notify_tool_result(
                    tool_name=name, result=result, success=True
                )
            )

    def handle_user_input(self, user_input: str) -> str:
        """Pass through to CLI."""
        return self.cli.handle_user_input(user_input)

    def handle_thinking_content(
        self, content: str, tokens: int, cost: float, collapsed: bool = True
    ) -> None:
        """Display thinking content in both interfaces."""
        self.cli.handle_thinking_content(content, tokens, cost, collapsed)

        if self.hybrid_mode:
            asyncio.create_task(
                self._island.notify_thinking(content=content, tokens=tokens, cost=cost)
            )

    def update_thinking_status(self, tokens: int, budget: int, cost: float) -> None:
        """Pass through to CLI."""
        if hasattr(self.cli, "update_thinking_status"):
            self.cli.update_thinking_status(tokens, budget, cost)

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
        elapsed_seconds: float | None = None,
        plan_slug: str | None = None,
        plan_tasks_completed: int | None = None,
        plan_tasks_verified: int | None = None,
        plan_tasks_total: int | None = None,
    ) -> None:
        """Display token count in both interfaces."""
        self.cli.display_token_count(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            total_cost=total_cost,
            cached_tokens=cached_tokens,
            conversation_size=conversation_size,
            context_window=context_window,
            thinking_tokens=thinking_tokens,
            thinking_cost=thinking_cost,
            elapsed_seconds=elapsed_seconds,
            plan_slug=plan_slug,
            plan_tasks_completed=plan_tasks_completed,
            plan_tasks_verified=plan_tasks_verified,
            plan_tasks_total=plan_tasks_total,
        )

        if self.hybrid_mode:
            asyncio.create_task(
                self._island.notify_token_usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_cost=total_cost,
                    cached_tokens=cached_tokens,
                    conversation_size=conversation_size,
                    context_window=context_window,
                    thinking_tokens=thinking_tokens,
                    elapsed_seconds=elapsed_seconds,
                )
            )

    def display_welcome_message(self) -> None:
        """Display welcome message."""
        self.cli.display_welcome_message()

        # Also show hybrid mode status
        if self.socket_path.exists():
            self.cli.handle_system_message(
                "[dim]Agent Island detected - UI dialogs will appear in both terminal and app[/dim]",
                markdown=False,
            )

    def status(
        self, message: str, spinner: str = None
    ) -> contextlib.AbstractContextManager:
        """Pass through to CLI."""
        # Also notify Island
        if self.hybrid_mode:
            asyncio.create_task(
                self._island.notify_status(message=message, spinner=spinner is not None)
            )

        return self.cli.status(message, spinner)

    def bare(self, message: str | Any, live=None) -> None:
        """Pass through to CLI."""
        self.cli.bare(message, live=live)

    async def get_session_choice(self, sessions: List[Dict[str, Any]]) -> str | None:
        """Pass through to CLI (session management is CLI-only)."""
        return await self.cli.get_session_choice(sessions)

    # ========== Delegation for optional methods ==========

    def set_toolbox(self, toolbox):
        """Pass through to CLI if it has this method."""
        if hasattr(self.cli, "set_toolbox"):
            self.cli.set_toolbox(toolbox)
