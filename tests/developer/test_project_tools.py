"""Tests for project-local tools discovery."""

import os


class TestProjectToolsDiscovery:
    """Test project-local tools discovery functionality."""

    def test_get_project_tools_dir_no_project(self, tmp_path):
        """Test that no project tools dir is found when not in a project."""
        from silica.developer.tools.user_tools import get_project_tools_dir

        # Change to a temporary directory with no .silica or .git
        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = get_project_tools_dir()
            assert result is None
        finally:
            os.chdir(original_cwd)

    def test_get_project_tools_dir_with_silica_tools(self, tmp_path):
        """Test finding project tools in .silica/tools directory."""
        from silica.developer.tools.user_tools import get_project_tools_dir

        # Create .silica/tools directory
        project_tools = tmp_path / ".silica" / "tools"
        project_tools.mkdir(parents=True)

        # Also create a .git directory to mark it as a project root
        (tmp_path / ".git").mkdir()

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            result = get_project_tools_dir()
            assert result == project_tools
        finally:
            os.chdir(original_cwd)

    def test_get_project_tools_dir_from_subdirectory(self, tmp_path):
        """Test finding project tools when in a subdirectory."""
        from silica.developer.tools.user_tools import get_project_tools_dir

        # Create project structure
        project_tools = tmp_path / ".silica" / "tools"
        project_tools.mkdir(parents=True)
        (tmp_path / ".git").mkdir()

        # Create a subdirectory
        subdir = tmp_path / "src" / "module"
        subdir.mkdir(parents=True)

        original_cwd = os.getcwd()
        try:
            os.chdir(subdir)
            result = get_project_tools_dir()
            assert result == project_tools
        finally:
            os.chdir(original_cwd)

    def test_get_all_tools_dirs_order(self, tmp_path):
        """Test that personal tools come before project tools."""
        from silica.developer.tools.user_tools import (
            get_all_tools_dirs,
            get_tools_dir,
        )

        # Create project tools directory
        project_tools = tmp_path / ".silica" / "tools"
        project_tools.mkdir(parents=True)
        (tmp_path / ".git").mkdir()

        original_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            dirs = get_all_tools_dirs()

            # Should have personal tools first
            assert len(dirs) >= 1
            assert dirs[0] == get_tools_dir()

            # If project tools exist, they should be second
            if len(dirs) > 1:
                assert dirs[1] == project_tools
        finally:
            os.chdir(original_cwd)

    def test_discover_tools_from_dir(self, tmp_path):
        """Test discovering tools from a specific directory."""
        from silica.developer.tools.user_tools import (
            discover_tools_from_dir,
            ensure_toolspec_helper_in_dir,
        )

        # Create a simple tool
        tools_dir = tmp_path / "tools"
        tools_dir.mkdir()

        # First ensure the helper exists
        ensure_toolspec_helper_in_dir(tools_dir)

        tool_content = '''#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts"]
# ///
"""Test tool."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema
import cyclopts
app = cyclopts.App()

@app.default
def main(name: str = "World", *, toolspec: bool = False):
    """Say hello."""
    if toolspec:
        print(json.dumps(generate_schema(main, "test_hello")))
        return
    print(json.dumps({"greeting": f"Hello, {name}!"}))

if __name__ == "__main__":
    app()
'''
        tool_path = tools_dir / "test_hello.py"
        tool_path.write_text(tool_content)
        tool_path.chmod(0o755)

        # Discover tools
        tools = discover_tools_from_dir(tools_dir)

        # Should find the tool
        assert len(tools) == 1
        assert tools[0].name == "test_hello"
        assert tools[0].spec.get("name") == "test_hello"

    def test_personal_tools_take_precedence(self, tmp_path):
        """Test that personal tools override project tools with same name."""
        from silica.developer.tools.user_tools import (
            discover_tools,
            ensure_toolspec_helper_in_dir,
            get_tools_dir,
        )

        # Create project with same-named tool
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / ".git").mkdir()
        project_tools = project_root / ".silica" / "tools"
        project_tools.mkdir(parents=True)

        ensure_toolspec_helper_in_dir(project_tools)

        # Create a project tool
        project_tool_content = '''#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = ["cyclopts"]
# ///
"""Project version."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from _silica_toolspec import generate_schema
import cyclopts
app = cyclopts.App()

@app.default
def main(*, toolspec: bool = False):
    """Project tool."""
    if toolspec:
        print(json.dumps(generate_schema(main, "conflict_tool")))
        return
    print(json.dumps({"source": "project"}))

if __name__ == "__main__":
    app()
'''
        project_tool_path = project_tools / "conflict_tool.py"
        project_tool_path.write_text(project_tool_content)
        project_tool_path.chmod(0o755)

        # The personal tools directory already has tools
        # When we discover, personal tools should take precedence
        original_cwd = os.getcwd()
        try:
            os.chdir(project_root)
            tools = discover_tools()

            # Find the conflict_tool if it exists
            conflict_tools = [t for t in tools if t.name == "conflict_tool"]

            # If there's a personal tool with the same name, it should come from personal dir
            # If only project tool exists, it should be from project
            if conflict_tools:
                tool = conflict_tools[0]
                # Personal tools dir takes precedence
                personal_dir = get_tools_dir()
                if (personal_dir / "conflict_tool.py").exists():
                    assert str(personal_dir) in str(tool.path)
                else:
                    # Only project version exists
                    assert str(project_tools) in str(tool.path)
        finally:
            os.chdir(original_cwd)


class TestEnsureToolspecHelper:
    """Test toolspec helper creation in different directories."""

    def test_ensure_toolspec_helper_in_dir_creates_file(self, tmp_path):
        """Test that toolspec helper is created in specified directory."""
        from silica.developer.tools.user_tools import ensure_toolspec_helper_in_dir

        tools_dir = tmp_path / "custom_tools"
        tools_dir.mkdir()

        helper_path = ensure_toolspec_helper_in_dir(tools_dir)

        assert helper_path.exists()
        assert helper_path.name == "_silica_toolspec.py"
        assert helper_path.parent == tools_dir

        # Check content includes generate_schema
        content = helper_path.read_text()
        assert "def generate_schema" in content
        assert "def generate_schemas_for_commands" in content

    def test_ensure_toolspec_helper_creates_directory(self, tmp_path):
        """Test that the directory is created if it doesn't exist."""
        from silica.developer.tools.user_tools import ensure_toolspec_helper_in_dir

        tools_dir = tmp_path / "new" / "nested" / "tools"
        assert not tools_dir.exists()

        helper_path = ensure_toolspec_helper_in_dir(tools_dir)

        assert tools_dir.exists()
        assert helper_path.exists()
