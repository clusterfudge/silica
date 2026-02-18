"""Tests for memory entry @reference resolution."""

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from silica.developer.memory.manager import MemoryManager


@pytest.fixture
def memory_dir(tmp_path):
    """Create a temporary memory directory with sample entries."""
    mem = tmp_path / "memory"
    mem.mkdir()
    return mem


def _write_entry(memory_dir: Path, path: str, content: str):
    """Helper to write a memory entry to disk (content + metadata)."""
    full = memory_dir / f"{path}.md"
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
    # MemoryManager.read_entry requires a .metadata.json alongside the .md
    meta_path = full.parent / f"{full.stem}.metadata.json"
    meta_path.write_text(json.dumps({"summary": "", "created": "2025-01-01"}))


class TestRenderContent:
    """Tests for MemoryManager.render_content()."""

    def test_no_references(self, memory_dir):
        """Content without @references is returned unchanged."""
        mgr = MemoryManager(base_dir=memory_dir)
        text = "Hello world\nNo references here\n@notaref because inline"
        assert mgr.render_content(text) == text

    def test_basic_reference(self, memory_dir):
        """A single @reference is replaced with entry content."""
        _write_entry(memory_dir, "greetings/hello", "Hello from memory!")
        mgr = MemoryManager(base_dir=memory_dir)

        text = "Before\n@greetings/hello\nAfter"
        result = mgr.render_content(text)
        assert result == "Before\nHello from memory!\nAfter"

    def test_multiple_references(self, memory_dir):
        """Multiple @references in the same content are all resolved."""
        _write_entry(memory_dir, "a", "Content A")
        _write_entry(memory_dir, "b", "Content B")
        mgr = MemoryManager(base_dir=memory_dir)

        text = "@a\n---\n@b"
        result = mgr.render_content(text)
        assert result == "Content A\n---\nContent B"

    def test_nested_references(self, memory_dir):
        """References within referenced entries are resolved recursively."""
        _write_entry(memory_dir, "inner", "Inner content")
        _write_entry(memory_dir, "outer", "Start\n@inner\nEnd")
        mgr = MemoryManager(base_dir=memory_dir)

        text = "@outer"
        result = mgr.render_content(text)
        assert result == "Start\nInner content\nEnd"

    def test_deeply_nested(self, memory_dir):
        """Three levels of nesting resolves correctly."""
        _write_entry(memory_dir, "level3", "deep content")
        _write_entry(memory_dir, "level2", "@level3")
        _write_entry(memory_dir, "level1", "@level2")
        mgr = MemoryManager(base_dir=memory_dir)

        result = mgr.render_content("@level1")
        assert result == "deep content"

    def test_missing_entry(self, memory_dir):
        """Missing entries produce an HTML comment."""
        mgr = MemoryManager(base_dir=memory_dir)

        text = "Before\n@nonexistent/path\nAfter"
        result = mgr.render_content(text)
        assert result == "Before\n<!-- @nonexistent/path: not found -->\nAfter"

    def test_circular_reference(self, memory_dir):
        """Circular references are detected and produce a comment."""
        _write_entry(memory_dir, "a", "@b")
        _write_entry(memory_dir, "b", "@a")
        mgr = MemoryManager(base_dir=memory_dir)

        result = mgr.render_content("@a")
        assert "<!-- @a: circular reference -->" in result

    def test_self_reference(self, memory_dir):
        """An entry referencing itself is detected as circular."""
        _write_entry(memory_dir, "self", "Before\n@self\nAfter")
        mgr = MemoryManager(base_dir=memory_dir)

        result = mgr.render_content("@self")
        assert "<!-- @self: circular reference -->" in result

    def test_depth_limit(self, memory_dir):
        """References beyond max_depth produce a comment."""
        _write_entry(memory_dir, "d4", "deep")
        _write_entry(memory_dir, "d3", "@d4")
        _write_entry(memory_dir, "d2", "@d3")
        _write_entry(memory_dir, "d1", "@d2")
        mgr = MemoryManager(base_dir=memory_dir)

        # max_depth=2: caller(2) -> d1(1) -> d2(0) -> d3 hits limit
        result = mgr.render_content("@d1", max_depth=2)
        assert "max depth exceeded" in result
        assert "deep" not in result

    def test_depth_limit_zero(self, memory_dir):
        """max_depth=0 means no references are resolved."""
        _write_entry(memory_dir, "entry", "content")
        mgr = MemoryManager(base_dir=memory_dir)

        result = mgr.render_content("@entry", max_depth=0)
        assert result == "<!-- @entry: max depth exceeded -->"

    def test_inline_at_not_matched(self, memory_dir):
        """@ signs in the middle of text are not treated as references."""
        mgr = MemoryManager(base_dir=memory_dir)

        text = "Email me at user@example.com\nThis @mention is inline"
        assert mgr.render_content(text) == text

    def test_leading_whitespace_preserved(self, memory_dir):
        """References with leading whitespace are still matched."""
        _write_entry(memory_dir, "entry", "resolved")
        mgr = MemoryManager(base_dir=memory_dir)

        # The regex matches the whole line including whitespace
        text = "  @entry"
        result = mgr.render_content(text)
        assert result == "resolved"

    def test_empty_content(self, memory_dir):
        """Empty string is returned unchanged."""
        mgr = MemoryManager(base_dir=memory_dir)
        assert mgr.render_content("") == ""

    def test_empty_referenced_entry(self, memory_dir):
        """A reference to an empty entry resolves to empty string."""
        _write_entry(memory_dir, "empty", "")
        mgr = MemoryManager(base_dir=memory_dir)

        text = "Before\n@empty\nAfter"
        result = mgr.render_content(text)
        assert result == "Before\n\nAfter"

    def test_directory_path_not_resolved(self, memory_dir):
        """A reference to a directory (not a leaf) produces not-found."""
        (memory_dir / "mydir").mkdir()
        _write_entry(memory_dir, "mydir/child", "child content")
        mgr = MemoryManager(base_dir=memory_dir)

        # @mydir is a directory, not a file
        text = "@mydir"
        result = mgr.render_content(text)
        assert "not found" in result

    def test_reference_with_dots_and_underscores(self, memory_dir):
        """Paths with dots, underscores, and hyphens work."""
        _write_entry(memory_dir, "my_project/v2.0/status-report", "All good")
        mgr = MemoryManager(base_dir=memory_dir)

        result = mgr.render_content("@my_project/v2.0/status-report")
        assert result == "All good"

    def test_multiline_referenced_content(self, memory_dir):
        """Multi-line entry content is inserted correctly."""
        _write_entry(
            memory_dir,
            "standards",
            "## Coding Standards\n\n- Use type hints\n- Write tests\n- Keep it simple",
        )
        mgr = MemoryManager(base_dir=memory_dir)

        text = "# Persona\n\n@standards\n\n# End"
        result = mgr.render_content(text)
        assert "## Coding Standards" in result
        assert "- Use type hints" in result
        assert "# Persona" in result
        assert "# End" in result


class TestRenderEntry:
    """Tests for MemoryManager.render_entry()."""

    def test_basic_render(self, memory_dir):
        """render_entry reads and resolves in one call."""
        _write_entry(memory_dir, "ref", "Referenced!")
        _write_entry(memory_dir, "main", "Start\n@ref\nEnd")
        mgr = MemoryManager(base_dir=memory_dir)

        result = mgr.render_entry("main")
        assert result == "Start\nReferenced!\nEnd"

    def test_nonexistent_entry(self, memory_dir):
        """render_entry returns None for missing entries."""
        mgr = MemoryManager(base_dir=memory_dir)
        assert mgr.render_entry("nonexistent") is None

    def test_entry_without_references(self, memory_dir):
        """render_entry on plain content returns it unchanged."""
        _write_entry(memory_dir, "plain", "Just text")
        mgr = MemoryManager(base_dir=memory_dir)

        assert mgr.render_entry("plain") == "Just text"


class TestPersonaIntegration:
    """Tests for @reference resolution in persona loading."""

    def test_persona_with_references(self, tmp_path):
        """Persona.md with @references has them resolved in system prompt."""
        from silica.developer.prompt import _load_persona_from_disk

        # Set up persona directory
        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()

        # Write persona.md with a reference
        persona_file = persona_dir / "persona.md"
        persona_file.write_text(
            "# Test Persona\n\nYou are helpful.\n\n## Standards\n@coding/standards"
        )

        # Set up memory directory with the referenced entry
        memory_dir = persona_dir / "memory"
        memory_dir.mkdir()
        _write_entry(
            memory_dir, "coding/standards", "- Always write tests\n- Use type hints"
        )

        # Create a mock context
        mock_context = Mock()
        mock_context.history_base_dir = persona_dir
        mock_context.memory_manager = MemoryManager(base_dir=memory_dir)

        result = _load_persona_from_disk(mock_context)
        assert result is not None
        text = result["text"]

        # Should contain persona content
        assert "Test Persona" in text
        assert "You are helpful." in text

        # Should contain resolved reference content
        assert "Always write tests" in text
        assert "Use type hints" in text

        # Should NOT contain the raw @reference
        assert "@coding/standards" not in text

    def test_persona_without_memory_manager(self, tmp_path):
        """Persona loads fine even without a memory manager."""
        from silica.developer.prompt import _load_persona_from_disk

        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()
        persona_file = persona_dir / "persona.md"
        persona_file.write_text("# Simple Persona\n\n@some/ref")

        mock_context = Mock()
        mock_context.history_base_dir = persona_dir
        mock_context.memory_manager = None

        result = _load_persona_from_disk(mock_context)
        assert result is not None
        # Reference is left unresolved (no memory manager)
        assert "@some/ref" in result["text"]

    def test_persona_with_missing_reference(self, tmp_path):
        """Persona with a reference to a nonexistent entry gets a comment."""
        from silica.developer.prompt import _load_persona_from_disk

        persona_dir = tmp_path / "test_persona"
        persona_dir.mkdir()
        persona_file = persona_dir / "persona.md"
        persona_file.write_text("# Persona\n@missing/entry")

        memory_dir = persona_dir / "memory"
        memory_dir.mkdir()

        mock_context = Mock()
        mock_context.history_base_dir = persona_dir
        mock_context.memory_manager = MemoryManager(base_dir=memory_dir)

        result = _load_persona_from_disk(mock_context)
        assert "<!-- @missing/entry: not found -->" in result["text"]
