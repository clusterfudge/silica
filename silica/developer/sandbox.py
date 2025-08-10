import os
import tempfile
import subprocess
from enum import Enum, auto
from typing import Dict, Callable

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


PermissionCheckCallback = Callable[[str, str, SandboxMode, Dict | None], bool]
PermissionCheckRenderingCallback = Callable[[str, str, Dict | None], None]


def _default_permission_check_callback(
    action: str, resource: str, mode: SandboxMode, action_arguments: Dict | None = None
) -> bool:
    # Request human input
    response = input(
        f"Allow {action} on {resource} with arguments {action_arguments}? (Y/N/D for 'do something else'): "
    ).lower()
    if response == "d":
        # Special return value to indicate "do something else"
        raise DoSomethingElseError()
    return response == "y"


def _default_permission_check_rendering_callback(
    action: str, resource: str, mode: SandboxMode, action_arguments: Dict | None = None
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

        for root, dirs, files in os.walk(target_dir):
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

    def check_permissions(
        self, action: str, resource: str, action_arguments: Dict | None = None
    ) -> bool:
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

        if allowed or self.mode == SandboxMode.ALLOW_ALL:
            return True

        # Call permission check callback, which may raise DoSomethingElseError
        allowed = self._permission_check_callback(
            action, resource, self.mode, action_arguments
        )

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
        if not self.check_permissions("read_file", file_path):
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
                    "edit_file", file_path, {"diff": diff_output}
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
                "write_file", file_path, {"content": content}
            ):
                raise PermissionError

            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as file:
                file.write(content)

    def create_file(self, file_path, content=""):
        """
        Create a new file within the sandbox with optional content.
        """
        if not self.check_permissions("write_file", file_path, {"content": content}):
            raise PermissionError
        full_path = os.path.join(self.root_directory, file_path)
        if not self._is_path_in_sandbox(full_path):
            raise ValueError(f"File path {file_path} is outside the sandbox")

        if os.path.exists(full_path):
            raise FileExistsError(f"File {file_path} already exists in the sandbox")

        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "w") as file:
            file.write(content)
