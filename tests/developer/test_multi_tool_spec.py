"""Tests for multi-tool file support.

Multi-tool files (like gcal.py, gmail.py) contain multiple subcommands that each
expose their own tool spec. When --toolspec is called on these files, they return
a JSON array of tool specs instead of a single spec object.

This tests:
1. ValidationResult handles both single and multi-tool specs
2. validate_tool() correctly validates each spec in a multi-tool array
3. discover_tools() splits multi-tool files into individual DiscoveredTool entries
4. toolbox_create display works for multi-tool files
5. toolbox_inspect display works for multi-tool files
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from silica.developer.tools.user_tools import (
    ValidationResult,
    _discover_tools_from_file,
    validate_tool,
)


# ---- ValidationResult tests ----


class TestValidationResultMultiTool:
    """Tests for ValidationResult with multi-tool specs."""

    def test_single_spec_is_not_multi_tool(self):
        spec = {
            "name": "test_tool",
            "description": "A test tool",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }
        result = ValidationResult(valid=True, errors=[], warnings=[], spec=spec)
        assert result.is_multi_tool is False
        assert result.specs == [spec]

    def test_list_spec_is_multi_tool(self):
        specs = [
            {
                "name": "tool_a",
                "description": "Tool A",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "tool_b",
                "description": "Tool B",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
        ]
        result = ValidationResult(valid=True, errors=[], warnings=[], spec=specs)
        assert result.is_multi_tool is True
        assert result.specs == specs
        assert len(result.specs) == 2

    def test_none_spec_returns_empty_specs(self):
        result = ValidationResult(valid=False, errors=["fail"], warnings=[])
        assert result.is_multi_tool is False
        assert result.specs == []

    def test_empty_list_spec(self):
        result = ValidationResult(valid=True, errors=[], warnings=[], spec=[])
        assert result.is_multi_tool is True
        assert result.specs == []


# ---- validate_tool() with multi-tool specs ----


class TestValidateToolMultiSpec:
    """Tests for validate_tool() handling of multi-tool --toolspec output."""

    def _make_valid_spec(self, name: str, desc: str = "A tool") -> dict:
        return {
            "name": name,
            "description": desc,
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }

    @patch("silica.developer.tools.user_tools.subprocess.run")
    def test_valid_multi_tool_spec(self, mock_run):
        """A --toolspec returning a list of valid specs should pass validation."""
        specs = [
            self._make_valid_spec("cal_list"),
            self._make_valid_spec("cal_create"),
            self._make_valid_spec("cal_delete"),
        ]

        # First call: ruff check (success)
        ruff_result = MagicMock()
        ruff_result.returncode = 0

        # Second call: --toolspec (returns array)
        toolspec_result = MagicMock()
        toolspec_result.returncode = 0
        toolspec_result.stdout = json.dumps(specs)

        mock_run.side_effect = [ruff_result, toolspec_result]

        path = MagicMock()
        path.exists.return_value = True
        path.read_text.return_value = '"""docstring"""\npass'
        path.parent = Path("/tmp")

        result = validate_tool(path)
        assert result.valid is True
        assert result.is_multi_tool is True
        assert len(result.specs) == 3
        assert result.specs[0]["name"] == "cal_list"

    @patch("silica.developer.tools.user_tools.subprocess.run")
    def test_multi_tool_spec_with_one_invalid(self, mock_run):
        """If one spec in a multi-tool array is invalid, validation should fail."""
        specs = [
            self._make_valid_spec("cal_list"),
            {"name": "bad_tool"},  # missing description and input_schema
        ]

        ruff_result = MagicMock()
        ruff_result.returncode = 0

        toolspec_result = MagicMock()
        toolspec_result.returncode = 0
        toolspec_result.stdout = json.dumps(specs)

        mock_run.side_effect = [ruff_result, toolspec_result]

        path = MagicMock()
        path.exists.return_value = True
        path.read_text.return_value = '"""docstring"""\npass'
        path.parent = Path("/tmp")

        result = validate_tool(path)
        assert result.valid is False
        # Errors should mention the tool name
        assert any("bad_tool" in e for e in result.errors)

    @patch("silica.developer.tools.user_tools.subprocess.run")
    def test_multi_tool_spec_with_non_dict_item(self, mock_run):
        """If a multi-tool array contains a non-dict, validation should fail."""
        specs = [self._make_valid_spec("cal_list"), "not a dict"]

        ruff_result = MagicMock()
        ruff_result.returncode = 0

        toolspec_result = MagicMock()
        toolspec_result.returncode = 0
        toolspec_result.stdout = json.dumps(specs)

        mock_run.side_effect = [ruff_result, toolspec_result]

        path = MagicMock()
        path.exists.return_value = True
        path.read_text.return_value = '"""docstring"""\npass'
        path.parent = Path("/tmp")

        result = validate_tool(path)
        assert result.valid is False
        assert any("not a dict" in e for e in result.errors)

    @patch("silica.developer.tools.user_tools.subprocess.run")
    def test_single_tool_spec_still_works(self, mock_run):
        """A --toolspec returning a single dict should still work as before."""
        spec = self._make_valid_spec("my_tool")

        ruff_result = MagicMock()
        ruff_result.returncode = 0

        toolspec_result = MagicMock()
        toolspec_result.returncode = 0
        toolspec_result.stdout = json.dumps(spec)

        mock_run.side_effect = [ruff_result, toolspec_result]

        path = MagicMock()
        path.exists.return_value = True
        path.read_text.return_value = '"""docstring"""\npass'
        path.parent = Path("/tmp")

        result = validate_tool(path)
        assert result.valid is True
        assert result.is_multi_tool is False
        assert result.specs == [spec]


# ---- _discover_tools_from_file() with multi-tool specs ----


class TestDiscoverMultiToolFile:
    """Tests for _discover_tools_from_file with multi-tool outputs."""

    def _make_valid_spec(self, name: str, desc: str = "A tool") -> dict:
        return {
            "name": name,
            "description": desc,
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }

    @patch("silica.developer.tools.user_tools.subprocess.run")
    def test_multi_tool_creates_multiple_discovered_tools(self, mock_run):
        """A file returning an array of specs should produce multiple DiscoveredTool objects."""
        specs = [
            self._make_valid_spec("calendar_list_events", "List events"),
            self._make_valid_spec("calendar_create_event", "Create event"),
            self._make_valid_spec("calendar_delete_event", "Delete event"),
        ]

        toolspec_result = MagicMock()
        toolspec_result.returncode = 0
        toolspec_result.stdout = json.dumps(specs)

        mock_run.return_value = toolspec_result

        path = MagicMock()
        path.stem = "gcal"
        path.read_text.return_value = '"""Google Calendar tools.\n\nMetadata:\n    category: productivity\n"""\npass'

        tools = _discover_tools_from_file(path, check_auth=False)

        assert len(tools) == 3
        assert tools[0].name == "calendar_list_events"
        assert tools[1].name == "calendar_create_event"
        assert tools[2].name == "calendar_delete_event"

        # All should share the same path and file_stem
        for t in tools:
            assert t.path == path
            assert t.file_stem == "gcal"
            assert t.metadata.category == "productivity"

    @patch("silica.developer.tools.user_tools.subprocess.run")
    def test_single_tool_file_still_works(self, mock_run):
        """A file returning a single spec dict still works."""
        spec = self._make_valid_spec("hello_world", "Say hello")

        toolspec_result = MagicMock()
        toolspec_result.returncode = 0
        toolspec_result.stdout = json.dumps(spec)

        mock_run.return_value = toolspec_result

        path = MagicMock()
        path.stem = "hello_world"
        path.read_text.return_value = '"""Hello world tool."""\npass'

        tools = _discover_tools_from_file(path, check_auth=False)

        assert len(tools) == 1
        assert tools[0].name == "hello_world"
        assert tools[0].spec == spec

    @patch("silica.developer.tools.user_tools.subprocess.run")
    def test_multi_tool_schema_validation_per_tool(self, mock_run):
        """Each tool in a multi-tool file gets its own schema validation."""
        specs = [
            self._make_valid_spec("good_tool"),
            {
                "name": "bad_tool",
                "description": "Missing input_schema",
                # no input_schema
            },
        ]

        toolspec_result = MagicMock()
        toolspec_result.returncode = 0
        toolspec_result.stdout = json.dumps(specs)

        mock_run.return_value = toolspec_result

        path = MagicMock()
        path.stem = "mixed"
        path.read_text.return_value = '"""Mixed tools."""\npass'

        tools = _discover_tools_from_file(path, check_auth=False)

        assert len(tools) == 2
        good = next(t for t in tools if t.name == "good_tool")
        bad = next(t for t in tools if t.name == "bad_tool")

        assert good.schema_valid is True
        assert good.schema_errors == []
        assert bad.schema_valid is False
        assert len(bad.schema_errors) > 0


# ---- toolbox_create display for multi-tool files ----


class TestToolboxCreateMultiTool:
    """Tests for toolbox_create output when creating multi-tool files."""

    def test_create_multi_tool_display(self):
        """Test that toolbox_create shows all tools from a multi-tool file."""
        from silica.developer.tools.toolbox_tools import _append_spec_summary

        output = []
        spec = {
            "name": "my_tool",
            "description": "Does something",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        }
        _append_spec_summary(output, spec, indent="  ")

        assert any("my_tool" in line for line in output)
        assert any("Does something" in line for line in output)
        assert any("query" in line and "(required)" in line for line in output)

    def test_append_spec_summary_with_custom_indent(self):
        """Test that _append_spec_summary respects indent parameter."""
        from silica.developer.tools.toolbox_tools import _append_spec_summary

        output = []
        spec = {
            "name": "test_tool",
            "description": "Test",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        }
        _append_spec_summary(output, spec, indent="    ")

        for line in output:
            assert line.startswith("    ")


# ---- toolbox_inspect display for multi-tool files ----


class TestToolboxInspectMultiTool:
    """Tests for toolbox_inspect output for multi-tool files."""

    def test_multi_tool_inspect_shows_all_specs(self):
        """Verify that inspect would show multiple specs for multi-tool files.

        We test the ValidationResult methods used by inspect, since the actual
        toolbox_inspect function requires file I/O.
        """
        specs = [
            {
                "name": "cal_list",
                "description": "List events",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            {
                "name": "cal_create",
                "description": "Create event",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
        ]
        result = ValidationResult(valid=True, errors=[], warnings=[], spec=specs)

        assert result.is_multi_tool is True
        assert len(result.specs) == 2

        # Simulate what toolbox_inspect does
        output = []
        if result.spec:
            output.append("## Tool Specification")
            if result.is_multi_tool:
                output.append(f"*Multi-tool file with {len(result.specs)} tools:*")
                for spec in result.specs:
                    output.append(f"### {spec.get('name', 'unnamed')}")
                    output.append(json.dumps(spec, indent=2))
            else:
                output.append(json.dumps(result.spec, indent=2))

        text = "\n".join(output)
        assert "Multi-tool file with 2 tools" in text
        assert "### cal_list" in text
        assert "### cal_create" in text


# ---- Integration: Real multi-tool file discovery ----


class TestRealMultiToolDiscovery:
    """Integration tests using actual multi-tool files if available."""

    def test_discover_gcal_if_exists(self):
        """If gcal.py exists in tools dir, it should produce multiple tools."""
        from silica.developer.tools.user_tools import get_tools_dir

        gcal_path = get_tools_dir() / "gcal.py"
        if not gcal_path.exists():
            pytest.skip("gcal.py not found in tools directory")

        tools = _discover_tools_from_file(gcal_path, check_auth=False)

        # gcal.py should produce 6 tools
        assert len(tools) >= 2, f"Expected multiple tools, got {len(tools)}"

        tool_names = [t.name for t in tools]
        # Check some expected tool names
        assert "calendar_list_events" in tool_names
        assert "calendar_create_event" in tool_names

        # All should share the same file_stem
        for t in tools:
            assert t.file_stem == "gcal"

    def test_subcommand_metadata_in_specs(self):
        """Multi-tool specs should include _subcommand metadata from generate_schemas_for_commands."""
        from silica.developer.tools.user_tools import get_tools_dir

        gcal_path = get_tools_dir() / "gcal.py"
        if not gcal_path.exists():
            pytest.skip("gcal.py not found in tools directory")

        tools = _discover_tools_from_file(gcal_path, check_auth=False)

        # At minimum, tools from generate_schemas_for_commands should have _subcommand
        # (Only present if the helper has been updated with _subcommand support)
        for t in tools:
            if "_subcommand" in t.spec:
                # The subcommand should be the function name, not the tool name
                assert (
                    t.spec["_subcommand"] != t.name
                ), "_subcommand should be the function name, not the tool name"

    def test_discover_gmail_if_exists(self):
        """If gmail.py exists in tools dir, it should produce multiple tools."""
        from silica.developer.tools.user_tools import get_tools_dir

        gmail_path = get_tools_dir() / "gmail.py"
        if not gmail_path.exists():
            pytest.skip("gmail.py not found in tools directory")

        tools = _discover_tools_from_file(gmail_path, check_auth=False)

        assert len(tools) >= 2, f"Expected multiple tools, got {len(tools)}"

        # All should share the same file_stem
        for t in tools:
            assert t.file_stem == "gmail"


# ---- Invocation subcommand derivation ----


class TestMultiToolInvocationSubcommand:
    """Tests for subcommand derivation when invoking multi-tool files."""

    def test_subcommand_from_spec_metadata(self):
        """When spec has _subcommand, it should be used for invocation."""
        from silica.developer.tools.user_tools import (
            DiscoveredTool,
            ToolMetadata,
            invoke_user_tool,
        )
        from unittest.mock import patch

        tool = DiscoveredTool(
            name="calendar_list_events",
            path=Path("/fake/gcal.py"),
            spec={
                "name": "calendar_list_events",
                "description": "List events",
                "input_schema": {"type": "object", "properties": {}, "required": []},
                "_subcommand": "list_events",
            },
            metadata=ToolMetadata(),
            file_stem="gcal",
        )

        with patch(
            "silica.developer.tools.user_tools.find_tool", return_value=tool
        ), patch("silica.developer.tools.user_tools._invoke_tool_file") as mock_invoke:
            mock_invoke.return_value = MagicMock(success=True, output="ok")
            invoke_user_tool("calendar_list_events", {"days": 1})

            # Should invoke with subcommand "list_events" (from _subcommand),
            # not "calendar_list_events" (the tool name)
            mock_invoke.assert_called_once_with(
                Path("/fake/gcal.py"), "list_events", {"days": 1}, 60
            )

    def test_subcommand_fallback_prefix_strip(self):
        """Without _subcommand metadata, should strip file_stem prefix."""
        from silica.developer.tools.user_tools import (
            DiscoveredTool,
            ToolMetadata,
            invoke_user_tool,
        )
        from unittest.mock import patch

        tool = DiscoveredTool(
            name="gmail_search",
            path=Path("/fake/gmail.py"),
            spec={
                "name": "gmail_search",
                "description": "Search",
                "input_schema": {"type": "object", "properties": {}, "required": []},
                # No _subcommand field
            },
            metadata=ToolMetadata(),
            file_stem="gmail",
        )

        with patch(
            "silica.developer.tools.user_tools.find_tool", return_value=tool
        ), patch("silica.developer.tools.user_tools._invoke_tool_file") as mock_invoke:
            mock_invoke.return_value = MagicMock(success=True, output="ok")
            invoke_user_tool("gmail_search", {"query": "test"})

            # Should strip "gmail_" prefix -> subcommand "search"
            mock_invoke.assert_called_once_with(
                Path("/fake/gmail.py"), "search", {"query": "test"}, 60
            )

    def test_single_tool_no_subcommand(self):
        """Single-tool files should not use a subcommand."""
        from silica.developer.tools.user_tools import (
            DiscoveredTool,
            ToolMetadata,
            invoke_user_tool,
        )
        from unittest.mock import patch

        tool = DiscoveredTool(
            name="hello_world",
            path=Path("/fake/hello_world.py"),
            spec={
                "name": "hello_world",
                "description": "Say hello",
                "input_schema": {"type": "object", "properties": {}, "required": []},
            },
            metadata=ToolMetadata(),
            file_stem="hello_world",
        )

        with patch(
            "silica.developer.tools.user_tools.find_tool", return_value=tool
        ), patch("silica.developer.tools.user_tools._invoke_tool_file") as mock_invoke:
            mock_invoke.return_value = MagicMock(success=True, output="ok")
            invoke_user_tool("hello_world", {"name": "World"})

            # name == file_stem -> no subcommand
            mock_invoke.assert_called_once_with(
                Path("/fake/hello_world.py"), None, {"name": "World"}, 60
            )


# ---- API schema stripping ----


class TestApiSchemaStripping:
    """Tests that internal metadata fields are stripped from API schemas."""

    def test_subcommand_stripped_from_api_schema(self):
        """_subcommand field should not appear in schemas sent to the API."""
        from silica.developer.toolbox import Toolbox
        from silica.developer.tools.user_tools import DiscoveredTool, ToolMetadata

        context = MagicMock()
        context.user_interface = MagicMock()

        toolbox = Toolbox(context, tool_names=[])
        toolbox.user_tools.clear()

        spec_with_metadata = {
            "name": "calendar_list_events",
            "description": "List events",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "_subcommand": "list_events",
        }
        toolbox.user_tools["calendar_list_events"] = DiscoveredTool(
            name="calendar_list_events",
            path=Path("/tmp/gcal.py"),
            spec=spec_with_metadata,
            metadata=ToolMetadata(),
            schema_valid=True,
            schema_errors=[],
        )

        schemas = toolbox.schemas(enable_caching=False)
        cal_schema = next(s for s in schemas if s["name"] == "calendar_list_events")

        # _subcommand should be stripped
        assert "_subcommand" not in cal_schema
        # But the real fields should still be there
        assert "name" in cal_schema
        assert "description" in cal_schema
        assert "input_schema" in cal_schema
