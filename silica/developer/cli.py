import asyncio
import os
import sys
from typing import List

from dotenv import load_dotenv
from rich.console import Console

from silica.developer.context import AgentContext
from silica.developer.hdev import main as dev_main, CLIUserInterface
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.toolbox import Toolbox
from silica.developer.tools.sessions import (
    list_sessions,
    print_session_list,
    resume_session,
)


def main(args: List[str] = None):
    if not args:
        args = sys.argv
    load_dotenv()
    console = Console()

    # Handle session management commands
    if len(args) > 1:
        if args[1] == "sessions":
            # List available sessions
            workdir = os.getcwd() if len(args) <= 2 else args[2]
            sessions = list_sessions(workdir=workdir)
            print_session_list(sessions)
            return
        elif args[1] == "resume" and len(args) > 2:
            # Resume a specific session
            session_id = args[2]
            resume_session(session_id)
            return

    # Continue with regular CLI processing
    sandbox = Sandbox(".", SandboxMode.ALLOW_ALL)
    context = AgentContext.create(
        model_spec={},
        sandbox_mode=SandboxMode.ALLOW_ALL,
        sandbox_contents=[],
        user_interface=CLIUserInterface(console, sandbox.mode),
    )
    toolbox = Toolbox(context)

    commands = set(toolbox.local.keys())

    if len(args) > 1 and args[1] in commands:
        # Pass remaining arguments to the developer CLI
        # translate tool spec to argparse
        tool_name = args[1]
        tool_args = " ".join(args[2:])  # TODO(2025-03-19): do something with shlex
        asyncio.run(
            toolbox.invoke_cli_tool(tool_name, arg_str=tool_args, confirm_to_add=False)
        )
    else:
        # Pass all arguments to the developer main function
        dev_main(args)


if __name__ == "__main__":
    main()
