"""Tests for project-scoped user tool discovery."""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from silica.developer.tools.user_tools import (
    DiscoveredTool,
    ToolMetadata,
    _get_git_root,
    discover_all_tools,
    get_project_tools_dirs,
)


@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory structure with a fake git root."""
    # Simulate a git repo by making git rev-parse return tmp_path
    project_root = tmp_path / "project"
    project_root.mkdir()
    sub = project_root / "packages" / "foo"
    sub.mkdir(parents=True)
    return project_root, sub


def _make_tool_file(tools_dir: Path, name: str, description: str = "A tool"):
    """Create a minimal valid tool file in the given directory."""
    tools_dir.mkdir(parents=True, exist_ok=True)
    tool_file = tools_dir / f"{name}.py"
    tool_file.write_text(
        textwrap.dedent(f'''\
        # /// script
        # requires-python = ">=3.11"
        # dependencies = ["cyclopts"]
        # ///
        """A tool.

        Metadata:
            category: test
        """
        import cyclopts
        from _silica_toolspec import generate_schema

        app = cyclopts.App(name="{name}", help="{description}")

        @app.default
        def main(name: str = "world"):
            """{description}"""
            print(f"hello {{name}}")

        @app.command(name="--toolspec")
        def toolspec():
            import json
            print(json.dumps(generate_schema(main, "{name}")))

        if __name__ == "__main__":
            app()
        ''')
    )
    return tool_file


class TestGetProjectToolsDirs:
    def test_finds_silica_tools_in_cwd(self, tmp_path):
        tools_dir = tmp_path / ".silica" / "tools"
        tools_dir.mkdir(parents=True)

        with patch("silica.developer.tools.user_tools.Path.cwd", return_value=tmp_path):
            with patch(
                "silica.developer.tools.user_tools._get_git_root", return_value=None
            ):
                dirs = get_project_tools_dirs()

        assert len(dirs) == 1
        assert dirs[0] == tools_dir

    def test_finds_agent_tools_in_cwd(self, tmp_path):
        tools_dir = tmp_path / ".agent" / "tools"
        tools_dir.mkdir(parents=True)

        with patch("silica.developer.tools.user_tools.Path.cwd", return_value=tmp_path):
            with patch(
                "silica.developer.tools.user_tools._get_git_root", return_value=None
            ):
                dirs = get_project_tools_dirs()

        assert len(dirs) == 1
        assert dirs[0] == tools_dir

    def test_finds_both_silica_and_agent(self, tmp_path):
        (tmp_path / ".silica" / "tools").mkdir(parents=True)
        (tmp_path / ".agent" / "tools").mkdir(parents=True)

        with patch("silica.developer.tools.user_tools.Path.cwd", return_value=tmp_path):
            with patch(
                "silica.developer.tools.user_tools._get_git_root", return_value=None
            ):
                dirs = get_project_tools_dirs()

        assert len(dirs) == 2

    def test_walks_to_git_root(self, tmp_path):
        git_root = tmp_path / "repo"
        sub = git_root / "packages" / "foo"
        sub.mkdir(parents=True)

        (git_root / ".silica" / "tools").mkdir(parents=True)
        (sub / ".silica" / "tools").mkdir(parents=True)

        with patch("silica.developer.tools.user_tools.Path.cwd", return_value=sub):
            with patch(
                "silica.developer.tools.user_tools._get_git_root",
                return_value=git_root,
            ):
                dirs = get_project_tools_dirs()

        # Should find both, closest first
        assert len(dirs) == 2
        assert dirs[0] == sub / ".silica" / "tools"
        assert dirs[1] == git_root / ".silica" / "tools"

    def test_no_project_dirs_returns_empty(self, tmp_path):
        with patch("silica.developer.tools.user_tools.Path.cwd", return_value=tmp_path):
            with patch(
                "silica.developer.tools.user_tools._get_git_root", return_value=None
            ):
                dirs = get_project_tools_dirs()

        assert dirs == []

    def test_not_in_git_only_checks_cwd(self, tmp_path):
        """When not in a git repo, only cwd is checked (not parents)."""
        parent = tmp_path / "parent"
        child = parent / "child"
        child.mkdir(parents=True)

        # Put tools in parent but not child
        (parent / ".silica" / "tools").mkdir(parents=True)

        with patch("silica.developer.tools.user_tools.Path.cwd", return_value=child):
            with patch(
                "silica.developer.tools.user_tools._get_git_root", return_value=None
            ):
                dirs = get_project_tools_dirs()

        # Should NOT find parent's tools since we're not in a git repo
        assert dirs == []

    def test_ordering_closest_first(self, tmp_path):
        """Directories closer to cwd should come first."""
        root = tmp_path / "repo"
        mid = root / "src"
        leaf = mid / "pkg"
        leaf.mkdir(parents=True)

        (root / ".silica" / "tools").mkdir(parents=True)
        (mid / ".agent" / "tools").mkdir(parents=True)
        (leaf / ".silica" / "tools").mkdir(parents=True)

        with patch("silica.developer.tools.user_tools.Path.cwd", return_value=leaf):
            with patch(
                "silica.developer.tools.user_tools._get_git_root", return_value=root
            ):
                dirs = get_project_tools_dirs()

        assert len(dirs) == 3
        assert dirs[0] == leaf / ".silica" / "tools"
        assert dirs[1] == mid / ".agent" / "tools"
        assert dirs[2] == root / ".silica" / "tools"


class TestDiscoverAllTools:
    def test_global_tools_have_global_source(self):
        """Global tools should be tagged with source='global'."""
        mock_tool = DiscoveredTool(
            name="hello",
            path=Path("/fake/hello.py"),
            spec={"name": "hello"},
            metadata=ToolMetadata(),
        )

        with patch(
            "silica.developer.tools.user_tools.discover_tools", return_value=[mock_tool]
        ):
            with patch(
                "silica.developer.tools.user_tools.get_project_tools_dirs",
                return_value=[],
            ):
                tools = discover_all_tools()

        assert len(tools) == 1
        assert tools[0].source == "global"

    def test_project_tool_overrides_global(self):
        """A project tool should override a global tool with the same name."""
        global_tool = DiscoveredTool(
            name="my_tool",
            path=Path("/home/user/.silica/tools/my_tool.py"),
            spec={"name": "my_tool", "description": "global version"},
            metadata=ToolMetadata(),
        )
        project_tool = DiscoveredTool(
            name="my_tool",
            path=Path("/project/.silica/tools/my_tool.py"),
            spec={"name": "my_tool", "description": "project version"},
            metadata=ToolMetadata(),
            source="/project",
        )

        with patch(
            "silica.developer.tools.user_tools.discover_tools",
            return_value=[global_tool],
        ):
            with patch(
                "silica.developer.tools.user_tools.get_project_tools_dirs",
                return_value=[Path("/project/.silica/tools")],
            ):
                with patch(
                    "silica.developer.tools.user_tools._discover_tools_from_dir",
                    return_value=[project_tool],
                ):
                    tools = discover_all_tools()

        assert len(tools) == 1
        assert tools[0].spec["description"] == "project version"
        assert tools[0].path == Path("/project/.silica/tools/my_tool.py")

    def test_closer_project_dir_overrides_farther(self):
        """A tool in cwd/.silica/tools/ should override one in git_root/.silica/tools/."""
        far_tool = DiscoveredTool(
            name="my_tool",
            path=Path("/repo/.silica/tools/my_tool.py"),
            spec={"name": "my_tool", "description": "repo root version"},
            metadata=ToolMetadata(),
        )
        close_tool = DiscoveredTool(
            name="my_tool",
            path=Path("/repo/pkg/.silica/tools/my_tool.py"),
            spec={"name": "my_tool", "description": "cwd version"},
            metadata=ToolMetadata(),
        )

        project_dirs = [
            Path("/repo/pkg/.silica/tools"),  # closer (index 0)
            Path("/repo/.silica/tools"),  # farther (index 1)
        ]

        def mock_discover_from_dir(tools_dir, check_auth=False, source="global"):
            if "pkg" in str(tools_dir):
                close_tool.source = source
                return [close_tool]
            else:
                far_tool.source = source
                return [far_tool]

        with patch("silica.developer.tools.user_tools.discover_tools", return_value=[]):
            with patch(
                "silica.developer.tools.user_tools.get_project_tools_dirs",
                return_value=project_dirs,
            ):
                with patch(
                    "silica.developer.tools.user_tools._discover_tools_from_dir",
                    side_effect=mock_discover_from_dir,
                ):
                    tools = discover_all_tools()

        assert len(tools) == 1
        assert tools[0].spec["description"] == "cwd version"

    def test_merges_different_tools_from_all_sources(self):
        """Tools with different names from different sources should all be present."""
        global_tool = DiscoveredTool(
            name="global_only",
            path=Path("/home/.silica/tools/global_only.py"),
            spec={"name": "global_only"},
            metadata=ToolMetadata(),
        )
        project_tool = DiscoveredTool(
            name="project_only",
            path=Path("/project/.silica/tools/project_only.py"),
            spec={"name": "project_only"},
            metadata=ToolMetadata(),
        )

        with patch(
            "silica.developer.tools.user_tools.discover_tools",
            return_value=[global_tool],
        ):
            with patch(
                "silica.developer.tools.user_tools.get_project_tools_dirs",
                return_value=[Path("/project/.silica/tools")],
            ):
                with patch(
                    "silica.developer.tools.user_tools._discover_tools_from_dir",
                    return_value=[project_tool],
                ):
                    tools = discover_all_tools()

        names = {t.name for t in tools}
        assert names == {"global_only", "project_only"}


class TestGetGitRoot:
    def test_returns_none_when_not_in_git(self, tmp_path):
        with patch("silica.developer.tools.user_tools.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 128
            result = _get_git_root()
        assert result is None

    def test_returns_path_when_in_git(self, tmp_path):
        with patch("silica.developer.tools.user_tools.subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = str(tmp_path) + "\n"
            result = _get_git_root()
        assert result == tmp_path
