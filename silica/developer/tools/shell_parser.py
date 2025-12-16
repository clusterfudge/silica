"""
Shell command parsing for security permission checks.

This module provides functionality to parse shell commands using bashlex
and extract information needed for permission checking.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import bashlex
import bashlex.ast
import bashlex.errors


@dataclass
class ParsedShellCommand:
    """Represents a parsed shell command with extracted metadata.

    Attributes:
        original: The original command string
        commands: All command names found (e.g., ["git", "npm"])
        is_compound: True if multiple commands (pipes, &&, ||, ;, for, while, etc.)
        has_substitution: True if $() or backticks present
        has_redirection: True if >, <, >> present
        parse_error: Error message if parsing failed
    """

    original: str
    commands: List[str] = field(default_factory=list)
    is_compound: bool = False
    has_substitution: bool = False
    has_redirection: bool = False
    parse_error: Optional[str] = None

    @property
    def is_simple(self) -> bool:
        """True if single command, not compound, no substitution.

        A simple command is one where we can easily identify the single
        command being run without any shell constructs that could
        introduce additional commands.
        """
        return (
            len(self.commands) == 1
            and not self.is_compound
            and not self.has_substitution
            and self.parse_error is None
        )


class ShellCommandVisitor(bashlex.ast.nodevisitor):
    """AST visitor that extracts command information from parsed shell commands.

    This visitor walks the bashlex AST and collects:
    - All command names found
    - Whether the command has pipes, lists (&&, ||, ;), or compound statements
    - Whether command substitution ($() or backticks) is used
    - Whether I/O redirection is used
    """

    def __init__(self):
        self.commands: List[str] = []
        self.has_pipeline: bool = False
        self.has_list: bool = False
        self.has_compound: bool = False
        self.has_substitution: bool = False
        self.has_redirection: bool = False

    def visitcommand(self, n, parts):
        """Visit a command node and extract the command name.

        The first word in a command is typically the command name.
        """
        for part in parts:
            if hasattr(part, "word") and part.kind == "word":
                # Only capture the command name (first word)
                self.commands.append(part.word)
                break
        return parts

    def visitpipeline(self, n, parts):
        """Visit a pipeline node (cmd1 | cmd2)."""
        self.has_pipeline = True
        return parts

    def visitlist(self, n, parts):
        """Visit a list node (cmd1 && cmd2, cmd1 || cmd2, cmd1; cmd2)."""
        self.has_list = True
        return parts

    def visitcompound(self, n, list, redirects):
        """Visit a compound node (for, while, if, { })."""
        self.has_compound = True
        return list, redirects

    def visitcommandsubstitution(self, n, command):
        """Visit a command substitution node ($() or backticks)."""
        self.has_substitution = True
        return command

    def visitredirect(self, n, input, output, type, heredoc):
        """Visit a redirect node (>, <, >>)."""
        self.has_redirection = True
        return input, output, type, heredoc


def parse_shell_command(command: str) -> ParsedShellCommand:
    """Parse a shell command string and extract metadata.

    Uses bashlex to parse the command and extract information about:
    - All commands that would be executed
    - Whether it's a compound command (pipes, &&, ||, ;, for, while, etc.)
    - Whether command substitution is present
    - Whether I/O redirection is present

    Args:
        command: The shell command string to parse

    Returns:
        ParsedShellCommand with all extracted information.
        On parse error, parse_error is set and is_compound defaults to True
        (conservative assumption for security).
    """
    result = ParsedShellCommand(original=command)

    try:
        parts = bashlex.parse(command)
    except bashlex.errors.ParsingError as e:
        # On parse error, assume the worst for security
        result.parse_error = str(e)
        result.is_compound = True  # Conservative assumption
        return result
    except Exception as e:
        # Catch any other unexpected errors
        result.parse_error = f"Unexpected error: {e}"
        result.is_compound = True  # Conservative assumption
        return result

    # Visit all parts of the parsed AST
    visitor = ShellCommandVisitor()
    for part in parts:
        visitor.visit(part)

    # Extract results from visitor
    result.commands = visitor.commands
    result.has_substitution = visitor.has_substitution
    result.has_redirection = visitor.has_redirection

    # Determine if compound:
    # - Multiple commands (from pipeline, list, or compound statements)
    # - Or explicit compound structures (for, while, if, { })
    result.is_compound = (
        visitor.has_pipeline
        or visitor.has_list
        or visitor.has_compound
        or len(visitor.commands) > 1
    )

    return result


def check_commands_allowed(
    parsed: ParsedShellCommand,
    allowed_commands: List[str],
    denied_commands: List[str],
) -> Tuple[bool, List[str], List[str]]:
    """Check if all commands in a parsed result are allowed.

    Checks each command against the allowed and denied lists.
    The deny list takes precedence over the allow list.

    Args:
        parsed: The parsed shell command result
        allowed_commands: List of command names that are allowed
        denied_commands: List of command names that are denied

    Returns:
        A tuple of (all_allowed, allowed_list, denied_list):
        - all_allowed: True if all commands are allowed and none are denied
        - allowed_list: List of commands that are in the allowed list
        - denied_list: List of commands that are in the denied list
    """
    allowed_set = set(allowed_commands)
    denied_set = set(denied_commands)

    allowed_list = []
    denied_list = []

    for cmd in parsed.commands:
        # Deny list takes precedence
        if cmd in denied_set:
            denied_list.append(cmd)
        elif cmd in allowed_set:
            allowed_list.append(cmd)

    # All commands must be explicitly allowed and none denied
    all_allowed = (
        len(denied_list) == 0
        and len(allowed_list) == len(parsed.commands)
        and parsed.parse_error is None
    )

    return all_allowed, allowed_list, denied_list
