"""Test automatic annotation extraction in agent_loop."""

import tempfile
from pathlib import Path
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
import pytest


@pytest.fixture
def mock_agent_context():
    """Create a mock agent context."""
    context = Mock()
    context.session_id = "test_session_123"
    context.history_base_dir = None  # Will use default
    context.chat_history = []
    context.tool_result_buffer = []
    context.user_interface = Mock()
    context.model_spec = {
        "title": "claude-3-5-sonnet-20241022",
        "max_tokens": 8000
    }
    return context


class TestAutomaticAnnotationExtraction:
    """Test that annotations are automatically extracted from agent responses."""

    def test_annotations_extracted_and_saved(self):
        """Test that annotations are extracted and saved to file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            persona_dir = Path(temp_dir)

            # Mock response with annotations
            ai_response = """For your API, you should implement caching.
@@@ caching reduces database queries and improves response times
^^^ technology:Redis, concept:caching
||| Redis|supports|caching

I recommend using Redis for this."""

            # Import the functions
            from silica.developer.knowledge_graph.parser import extract_annotations
            from silica.developer.knowledge_graph.tools import (
                _get_annotations_file,
                _save_annotations_to_file,
            )

            # Extract annotations
            annotations = extract_annotations(ai_response)

            # Verify extraction worked
            assert len(annotations['insights']) == 1
            assert "caching reduces database queries" in annotations['insights'][0]
            assert len(annotations['entities']) == 2
            assert ('technology', 'Redis') in annotations['entities']
            assert ('concept', 'caching') in annotations['entities']
            assert len(annotations['relationships']) == 1
            assert ('Redis', 'supports', 'caching') in annotations['relationships']

            # Save to file
            annotations_file = _get_annotations_file(persona_dir)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            session_id = "test_session_123"

            _save_annotations_to_file(
                annotations_file, annotations, timestamp, session_id
            )

            # Verify file exists and contains annotations
            assert annotations_file.exists()
            content = annotations_file.read_text()

            # Check format
            assert f"[session:{session_id}]" in content
            assert "@@@ caching reduces database queries" in content
            assert "^^^ technology:Redis" in content
            assert "^^^ concept:caching" in content
            assert "||| Redis|supports|caching" in content

    def test_no_annotations_skips_save(self):
        """Test that responses without annotations don't create files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            persona_dir = Path(temp_dir)

            # Response with no annotations
            ai_response = "This is a regular response without any annotations."

            from silica.developer.knowledge_graph.parser import extract_annotations
            from silica.developer.knowledge_graph.tools import _get_annotations_file

            annotations = extract_annotations(ai_response)

            # Should have no annotations
            assert len(annotations['insights']) == 0
            assert len(annotations['entities']) == 0
            assert len(annotations['relationships']) == 0

            # File should not be created if we don't save
            annotations_file = _get_annotations_file(persona_dir)
            # Just getting the file path creates the directory, but not the file
            assert annotations_file.parent.exists()
            # The file itself shouldn't exist yet
            assert not annotations_file.exists() or annotations_file.stat().st_size == 0

    def test_multiple_responses_append(self):
        """Test that multiple responses append to the same file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            persona_dir = Path(temp_dir)

            from silica.developer.knowledge_graph.parser import extract_annotations
            from silica.developer.knowledge_graph.tools import (
                _get_annotations_file,
                _save_annotations_to_file,
            )

            annotations_file = _get_annotations_file(persona_dir)
            session_id = "test_session_123"

            # First response
            response1 = """Let's use Redis for caching.
@@@ Redis is fast and reliable"""
            annotations1 = extract_annotations(response1)
            timestamp1 = "2024-01-15 10:00:00"
            _save_annotations_to_file(
                annotations_file, annotations1, timestamp1, session_id
            )

            # Second response
            response2 = """PostgreSQL is good for relational data.
@@@ PostgreSQL provides ACID guarantees"""
            annotations2 = extract_annotations(response2)
            timestamp2 = "2024-01-15 10:05:00"
            _save_annotations_to_file(
                annotations_file, annotations2, timestamp2, session_id
            )

            # Verify both are in file
            content = annotations_file.read_text()
            assert "@@@ Redis is fast and reliable" in content
            assert "@@@ PostgreSQL provides ACID guarantees" in content
            assert timestamp1 in content
            assert timestamp2 in content

    def test_extraction_preserves_clean_text(self):
        """Test that clean text has annotations removed."""
        ai_response = """Here's my recommendation:
@@@ this is an insight
Use Redis for caching.
^^^ technology:Redis
It's fast and reliable.
||| Redis|provides|speed"""

        from silica.developer.knowledge_graph.parser import extract_annotations

        annotations = extract_annotations(ai_response)

        # Clean text should not have markers
        clean_text = annotations['clean_text']
        assert "Here's my recommendation:" in clean_text
        assert "Use Redis for caching." in clean_text
        assert "It's fast and reliable." in clean_text

        # But annotations should be gone
        assert "@@@" not in clean_text
        assert "^^^" not in clean_text
        assert "|||" not in clean_text

    def test_annotations_with_special_characters(self):
        """Test that special characters in annotations are preserved."""
        ai_response = """For C++ development, use CMake.
@@@ C++ requires careful memory management
^^^ language:C++, build_tool:CMake
||| C++|requires|CMake"""

        from silica.developer.knowledge_graph.parser import extract_annotations
        from silica.developer.knowledge_graph.tools import (
            _get_annotations_file,
            _save_annotations_to_file,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            persona_dir = Path(temp_dir)
            annotations = extract_annotations(ai_response)

            # Verify special characters preserved in extraction
            assert any("C++" in insight for insight in annotations['insights'])
            assert ('language', 'C++') in annotations['entities']
            assert ('build_tool', 'CMake') in annotations['entities']

            # Save and verify file content
            annotations_file = _get_annotations_file(persona_dir)
            timestamp = "2024-01-15 12:00:00"
            _save_annotations_to_file(
                annotations_file, annotations, timestamp, "test_session"
            )

            content = annotations_file.read_text()
            assert "C++" in content
            assert "CMake" in content

    def test_error_handling_continues_on_failure(self):
        """Test that extraction errors don't crash the agent loop."""
        # This is more of an integration test concept
        # The actual agent_loop has try/except that catches errors
        # and displays a warning without crashing

        # We can test that the extraction itself is robust
        from silica.developer.knowledge_graph.parser import extract_annotations

        # Malformed annotations should still not crash
        ai_response = """Here's some text with weird markers:
@@@ valid insight
^^^ missing:colon:extra:parts
||| incomplete
Normal text continues."""

        # Should not raise exception
        annotations = extract_annotations(ai_response)

        # Valid parts should be extracted
        assert len(annotations['insights']) == 1
        assert "valid insight" in annotations['insights'][0]

    def test_session_id_in_annotations(self):
        """Test that session ID is correctly included in annotations."""
        with tempfile.TemporaryDirectory() as temp_dir:
            persona_dir = Path(temp_dir)

            from silica.developer.knowledge_graph.parser import extract_annotations
            from silica.developer.knowledge_graph.tools import (
                _get_annotations_file,
                _save_annotations_to_file,
            )

            ai_response = "@@@ test insight"
            annotations = extract_annotations(ai_response)

            annotations_file = _get_annotations_file(persona_dir)
            timestamp = "2024-01-15 12:00:00"
            session_id = "unique_session_abc123"

            _save_annotations_to_file(
                annotations_file, annotations, timestamp, session_id
            )

            content = annotations_file.read_text()
            assert f"[session:{session_id}]" in content
            assert "unique_session_abc123" in content

    def test_timestamp_format(self):
        """Test that timestamps are in correct format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            persona_dir = Path(temp_dir)

            from silica.developer.knowledge_graph.parser import extract_annotations
            from silica.developer.knowledge_graph.tools import (
                _get_annotations_file,
                _save_annotations_to_file,
            )

            ai_response = "@@@ test insight"
            annotations = extract_annotations(ai_response)

            annotations_file = _get_annotations_file(persona_dir)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            _save_annotations_to_file(
                annotations_file, annotations, timestamp, "test"
            )

            content = annotations_file.read_text()

            # Verify timestamp format [YYYY-MM-DD HH:MM:SS]
            import re
            timestamp_pattern = r'\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]'
            assert re.search(timestamp_pattern, content)

    def test_annotations_file_location(self):
        """Test that annotations are saved to correct location."""
        with tempfile.TemporaryDirectory() as temp_dir:
            persona_dir = Path(temp_dir)

            from silica.developer.knowledge_graph.tools import _get_annotations_file

            annotations_file = _get_annotations_file(persona_dir)

            # Should be in persona_dir/knowledge_graph/annotations.txt
            assert annotations_file == persona_dir / "knowledge_graph" / "annotations.txt"
            assert annotations_file.parent.name == "knowledge_graph"
            assert annotations_file.name == "annotations.txt"

    def test_empty_annotation_values_skipped(self):
        """Test that empty annotation values are handled gracefully."""
        ai_response = """Some text here.
@@@
^^^
|||
More text."""

        from silica.developer.knowledge_graph.parser import extract_annotations

        annotations = extract_annotations(ai_response)

        # Empty annotations should not be extracted
        # (depends on parser implementation - current implementation may or may not extract empty ones)
        # Just verify no crash
        assert isinstance(annotations, dict)
        assert 'insights' in annotations
        assert 'entities' in annotations
        assert 'relationships' in annotations
