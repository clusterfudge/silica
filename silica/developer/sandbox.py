import os
import tempfile
import subprocess
from enum import Enum, auto
from typing import Dict, Callable, Optional, Set, Tuple, Union

import aiofiles

from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern


class DoSomethingElseError(Exception):
    """Raised when the user chooses to 'do something else' instead of allowing or denying a permission."""


class SandboxMode(Enum):
    REQUEST_EVERY_TIME = auto()
    REMEMBER_PER_RESOURCE = auto()
    REMEMBER_ALL = auto()
    ALLOW_ALL = auto()


# Enhanced permission callback return types:
# - bool: True (allow this time) or False (deny)
# - str: "always_tool" or "always_group"
# - tuple: ("always_commands", set_of_commands) for shell commands
PermissionResult = Union[bool, str, Tuple[str, Set[str]]]

PermissionCheckCallback = Callable[
    [str, str, "SandboxMode", Dict | None, Optional[str]], PermissionResult
]
PermissionCheckRenderingCallback = Callable[[str, str, Dict | None], None]


def _default_permission_check_callback(
    action: str,
    resource: str,
    mode: "SandboxMode",
    action_arguments: Dict | None = None,
    group: Optional[str] = None,
) -> PermissionResult:
    """Default permission check callback with enhanced options.

    For non-shell tools:
        [Y] Yes, this time
        [N] No
        [A] Always allow <tool>
        [G] Always allow group (<group>)
        [D] Do something else

    For shell commands (when action == "shell"):
        Integrates with shell_parser to offer appropriate options.
    """
    # Build prompt based on whether this is a shell command
    if action == "shell":
        return _default_shell_permission_prompt(resource, mode, group)
    else:
        return _default_tool_permission_prompt(
            action, resource, mode, action_arguments, group
        )


def _default_tool_permission_prompt(
    action: str,
    resource: str,
    mode: "SandboxMode",
    action_arguments: Dict | None,
    group: Optional[str],
) -> PermissionResult:
    """Default permission prompt for non-shell tools."""
    prompt = f"\nAllow {action} on '{resource}'?\n"
    prompt += "  [Y] Yes, this time\n"
    prompt += "  [N] No\n"
    prompt += f"  [A] Always allow {action}\n"
    if group:
        prompt += f"  [G] Always allow group ({group})\n"
    prompt += "  [D] Do something else\n"
    prompt += "Choice: "

    response = input(prompt).strip().upper()

    if response == "D":
        raise DoSomethingElseError()
    elif response == "A":
        return "always_tool"
    elif response == "G" and group:
        return "always_group"
    elif response == "Y":
        return True
    else:
        return False


def _default_shell_permission_prompt(
    command: str,
    mode: "SandboxMode",
    group: Optional[str],
) -> PermissionResult:
    """Default permission prompt for shell commands with parser integration."""
    from .tools.shell_parser import parse_shell_command

    parsed = parse_shell_command(command)

    # Build prompt based on parsed result
    prompt = f"\nAllow shell: '{command}'?\n"

    # Show detected commands for compound commands
    if parsed.commands and len(parsed.commands) > 1:
        prompt += f"  Detected commands: {', '.join(parsed.commands)}\n"

    prompt += "  [Y] Yes, this time\n"
    prompt += "  [N] No\n"

    # Offer prefix option based on parse result
    if parsed.parse_error:
        # Unparseable - no prefix option, but still allow group
        pass
    elif parsed.is_simple and parsed.commands:
        # Simple command - offer to allow single command prefix
        cmd = parsed.commands[0]
        prompt += f"  [P] Always allow '{cmd}' commands\n"
    elif parsed.commands:
        # Compound - offer to allow all detected commands
        prompt += f"  [P] Always allow: {', '.join(parsed.commands)}\n"

    if group:
        prompt += f"  [G] Always allow group ({group})\n"
    prompt += "  [D] Do something else\n"
    prompt += "Choice: "

    response = input(prompt).strip().upper()

    if response == "D":
        raise DoSomethingElseError()
    elif response == "P" and parsed.commands and not parsed.parse_error:
        return ("always_commands", set(parsed.commands))
    elif response == "G" and group:
        return "always_group"
    elif response == "Y":
        return True
    else:
        return False


def _default_permission_check_rendering_callback(
    action: str, resource: str, action_arguments: Dict | None = None
):
    pass


class Sandbox:
    def __init__(
        self,
        root_directory: str,
        mode: SandboxMode,
        permission_check_callback: PermissionCheckCallback = None,
        permission_check_rendering_callback: PermissionCheckRenderingCallback = None,
    ):
        self.root_directory = os.path.abspath(root_directory)
        self.mode = mode
        self._permission_check_callback = (
            permission_check_callback or _default_permission_check_callback
        )
        self._permission_check_rendering_callback = (
            permission_check_rendering_callback
            or _default_permission_check_rendering_callback
        )
        self.permissions_cache = self._initialize_cache()
        self.gitignore_spec = self._load_gitignore()

        # Enhanced permission tracking
        self.allowed_tools: Set[str] = set()  # Permanently allowed tools
        self.allowed_groups: Set[str] = set()  # Permanently allowed groups
        self.permissions_manager = None  # Set by Toolbox after init

    def _initialize_cache(self):
        if self.mode in [SandboxMode.REMEMBER_PER_RESOURCE, SandboxMode.REMEMBER_ALL]:
            return {}
        return None

    def _load_gitignore(self):
        gitignore_path = os.path.join(self.root_directory, ".gitignore")
        patterns = [".git"]  # Always ignore .git directory
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r") as f:
                patterns.extend(
                    [
                        line.strip()
                        for line in f
                        if line.strip() and not line.startswith("#")
                    ]
                )
        return PathSpec.from_lines(GitWildMatchPattern, patterns)

    def get_directory_listing(self, path="", recursive=True, limit=1000):
        listing = []
        target_dir = os.path.join(self.root_directory, path)

        if not self._is_path_in_sandbox(target_dir):
            raise ValueError(f"Path {path} is outside the sandbox")

        if not os.path.exists(target_dir):
            return []

        for root, dirs, files in os.walk(target_dir, followlinks=True):
            # Remove ignored directories to prevent further traversal
            dirs[:] = [
                d
                for d in dirs
                if not self.gitignore_spec.match_file(os.path.join(root, d))
            ]

            for item in files:
                full_path = os.path.join(root, item)
                rel_path = os.path.relpath(full_path, target_dir)
                if not self.gitignore_spec.match_file(os.path.join(path, rel_path)):
                    listing.append(rel_path)

            if not recursive:
                break  # Only process the first level for non-recursive listing

            if len(listing) >= limit:
                return []

        return sorted(listing)

    def _shell_permission_check(self, command: str, group: Optional[str]) -> bool:
        """Special handling for shell command permissions.

        Integrates with shell_parser to check against allow/deny lists
        and provide appropriate prompts.
        """
        from .tools.shell_parser import parse_shell_command

        parsed = parse_shell_command(command)

        # Check against shell allow/deny lists from permissions_manager
        if self.permissions_manager and self.permissions_manager.permissions:
            shell_perms = self.permissions_manager.permissions
            allowed = list(shell_perms.shell_allowed_commands)
            denied = list(shell_perms.shell_denied_commands)

            # Check for denied commands
            denied_found = [cmd for cmd in parsed.commands if cmd in denied]
            if denied_found:
                # Show denied message and require explicit approval
                return self._prompt_for_denied_commands(
                    command, parsed, denied_found, group
                )

            # If all commands already allowed, permit
            if parsed.commands and all(cmd in allowed for cmd in parsed.commands):
                return True

        # Fall through to normal permission prompt
        return self._prompt_for_shell_permission(command, parsed, group)

    def _prompt_for_denied_commands(
        self,
        command: str,
        parsed,
        denied_commands: list,
        group: Optional[str],
    ) -> bool:
        """Prompt for shell command with denied commands detected."""
        # Use the permission callback to handle the prompt
        # The callback will show appropriate warning about denied commands
        self._permission_check_rendering_callback(
            "shell", command, {"denied": denied_commands}
        )

        # Build a special prompt showing denied commands
        result = self._permission_check_callback(
            "shell",
            command,
            self.mode,
            {"denied": denied_commands, "parsed": parsed},
            group,
        )

        return self._handle_permission_result(
            result, "shell", group, parsed.commands if parsed else None
        )

    def _prompt_for_shell_permission(
        self,
        command: str,
        parsed,
        group: Optional[str],
    ) -> bool:
        """Prompt for shell command permission."""
        self._permission_check_rendering_callback("shell", command, None)

        result = self._permission_check_callback(
            "shell", command, self.mode, {"parsed": parsed}, group
        )

        return self._handle_permission_result(
            result, "shell", group, parsed.commands if parsed else None
        )

    def _handle_permission_result(
        self,
        result: PermissionResult,
        action: str,
        group: Optional[str],
        shell_commands: Optional[list] = None,
    ) -> bool:
        """Handle the result from a permission callback.

        Persists "always" choices to the permissions manager.
        """
        if result == "always_tool":
            self.allowed_tools.add(action)
            if self.permissions_manager:
                self.permissions_manager.add_to_allow(tool_name=action)
                self.permissions_manager.save()
            return True
        elif result == "always_group" and group:
            self.allowed_groups.add(group)
            if self.permissions_manager:
                self.permissions_manager.add_to_allow(group=group)
                self.permissions_manager.save()
            return True
        elif (
            isinstance(result, tuple)
            and len(result) == 2
            and result[0] == "always_commands"
        ):
            commands = result[1]
            if self.permissions_manager:
                for cmd in commands:
                    self.permissions_manager.add_shell_command(cmd, allow=True)
                self.permissions_manager.save()
            return True
        elif isinstance(result, bool):
            return result
        else:
            # Unknown result type, default to deny
            return False

    def check_permissions(
        self,
        action: str,
        resource: str,
        action_arguments: Dict | None = None,
        group: Optional[str] = None,
    ) -> bool:
        """Check permissions for an action on a resource.

        Args:
            action: The action being performed (e.g., "read_file", "shell")
            resource: The resource being accessed (e.g., file path, command)
            action_arguments: Optional additional arguments for display
            group: Optional tool group for group-based permissions

        Returns:
            True if permission is granted, False otherwise.

        Raises:
            DoSomethingElseError: If user chooses "do something else"
        """
        # ALLOW_ALL mode (--dwr flag) bypasses all permission checks
        if self.mode == SandboxMode.ALLOW_ALL:
            return True

        # Check if tool is permanently allowed (in-memory)
        if action in self.allowed_tools:
            return True

        # Check if group is permanently allowed (in-memory)
        if group and group in self.allowed_groups:
            return True

        # Check permissions_manager for persisted permissions
        if self.permissions_manager and self.permissions_manager.permissions:
            perms = self.permissions_manager.permissions
            # Check if tool is in allow list
            if action in perms.allow_tools:
                self.allowed_tools.add(action)  # Cache it
                return True
            # Check if group is in allow list
            if group and group in perms.allow_groups:
                self.allowed_groups.add(group)  # Cache it
                return True

        # Special handling for shell commands
        if action == "shell":
            return self._shell_permission_check(resource, group)

        # Check cache based on mode
        key = f"{action}:{resource}"
        allowed = False

        if self.mode == SandboxMode.REMEMBER_ALL:
            assert isinstance(self.permissions_cache, dict)
            if key in self.permissions_cache:
                allowed = self.permissions_cache[key]
        elif self.mode == SandboxMode.REMEMBER_PER_RESOURCE:
            assert isinstance(self.permissions_cache, dict)
            if (
                action in self.permissions_cache
                and resource in self.permissions_cache[action]
            ):
                allowed = self.permissions_cache[action][resource]

        self._permission_check_rendering_callback(action, resource, action_arguments)

        if allowed:
            return True

        # Call permission check callback, which may raise DoSomethingElseError
        result = self._permission_check_callback(
            action, resource, self.mode, action_arguments, group
        )

        # Handle enhanced permission results
        allowed = self._handle_permission_result(result, action, group)

        # Cache only affirmative responses based on the mode
        if allowed:
            if self.mode == SandboxMode.REMEMBER_PER_RESOURCE:
                assert isinstance(self.permissions_cache, dict)
                self.permissions_cache.setdefault(action, {})[resource] = True
            elif self.mode == SandboxMode.REMEMBER_ALL:
                assert isinstance(self.permissions_cache, dict)
                self.permissions_cache[key] = True

        return allowed

    def _is_path_in_sandbox(self, path):
        abs_path = os.path.abspath(path)
        return (
            os.path.commonpath([abs_path, self.root_directory]) == self.root_directory
        )

    async def read_file(self, file_path):
        """
        Read the contents of a file within the sandbox.
        """
        if not self.check_permissions("read_file", file_path, group="Files"):
            raise PermissionError
        full_path = os.path.join(self.root_directory, file_path)
        if not self._is_path_in_sandbox(full_path):
            raise ValueError(f"File path {file_path} is outside the sandbox")

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"File {file_path} does not exist in the sandbox")

        async with aiofiles.open(full_path, "r") as file:
            return await file.read()

    def write_file(self, file_path, content):
        """
        Write content to a file within the sandbox.
        If the file already exists, generates a diff in patch format.
        """
        full_path = os.path.join(self.root_directory, file_path)
        if not self._is_path_in_sandbox(full_path):
            raise ValueError(f"File path {file_path} is outside the sandbox")

        if os.path.exists(full_path):
            # Create a temporary file with the new content
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".tmp", delete=False
            ) as tmp_file:
                tmp_file.write(content)
                tmp_path = tmp_file.name

            try:
                # Generate diff between the existing file and new content
                result = subprocess.run(
                    ["diff", "-u", full_path, tmp_path], capture_output=True, text=True
                )
                diff_output = result.stdout
                if not diff_output:  # No differences
                    diff_output = "(no changes)"

                # Update action_arguments with the diff instead of full content
                if not self.check_permissions(
                    "edit_file", file_path, {"diff": diff_output}, group="Files"
                ):
                    raise PermissionError

                # Write the new content if permissions were granted
                with open(full_path, "w") as file:
                    file.write(content)
            finally:
                # Clean up temporary file
                os.unlink(tmp_path)
        else:
            # For new files, show full content in permissions check
            if not self.check_permissions(
                "write_file", file_path, {"content": content}, group="Files"
            ):
                raise PermissionError

            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as file:
                file.write(content)

    def create_file(self, file_path, content=""):
        """
        Create a new file within the sandbox with optional content.
        """
        if not self.check_permissions(
            "write_file", file_path, {"content": content}, group="Files"
        ):
            raise PermissionError
        full_path = os.path.join(self.root_directory, file_path)
        if not self._is_path_in_sandbox(full_path):
            raise ValueError(f"File path {file_path} is outside the sandbox")

        if os.path.exists(full_path):
            raise FileExistsError(f"File {file_path} already exists in the sandbox")

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as file:
            file.write(content)
