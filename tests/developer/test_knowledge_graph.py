"""Test the knowledge graph annotation system."""

import tempfile
from pathlib import Path
from datetime import datetime, date, timedelta
import pytest

from silica.developer.knowledge_graph import extract_annotations
from silica.developer.knowledge_graph.tools import (
    _get_annotations_file,
    _save_annotations_to_file,
)


@pytest.fixture
def sample_annotated_text():
    """Sample text with annotations."""
    return """For your API, you should implement caching to reduce database load.
@@@ caching reduces database queries and improves response times
^^^ concept:caching, technology:Redis, database:PostgreSQL
||| caching|reduces_load_on|PostgreSQL

Redis is a good choice here since you're already using Python.
^^^ language:Python
||| Redis|integrates_with|Python

The main consideration is memory usage versus hit rate.
@@@ balance memory allocation with cache hit rate for optimal performance
||| memory_usage|tradeoff|hit_rate
"""


class TestAnnotationParser:
    """Test the annotation parser."""

    def test_parse_insights(self):
        """Test parsing insights from @@@ markers."""
        text = """Some text here.
@@@ this is an insight
More text.
@@@ another insight
"""
        result = extract_annotations(text)

        assert len(result['insights']) == 2
        assert "this is an insight" in result['insights']
        assert "another insight" in result['insights']

    def test_parse_entities(self):
        """Test parsing entities from ^^^ markers."""
        text = "Some text.\n^^^ concept:caching, technology:Redis, language:Python\n"
        result = extract_annotations(text)

        assert len(result['entities']) == 3
        types = [e[0] for e in result['entities']]
        values = [e[1] for e in result['entities']]

        assert "concept" in types
        assert "technology" in types
        assert "language" in types
        assert "caching" in values
        assert "Redis" in values
        assert "Python" in values

    def test_parse_relationships(self):
        """Test parsing relationships from ||| markers."""
        text = "Some text.\n||| Redis|integrates_with|Python\n||| caching|improves|performance\n"
        result = extract_annotations(text)

        assert len(result['relationships']) == 2

        assert ("Redis", "integrates_with", "Python") in result['relationships']
        assert ("caching", "improves", "performance") in result['relationships']

    def test_clean_text_removal(self):
        """Test that annotations are removed from clean text."""
        text = """Here is some text.
@@@ an insight
^^^ concept:test
||| a|b|c
More text here."""

        result = extract_annotations(text)

        assert "Here is some text." in result['clean_text']
        assert "More text here." in result['clean_text']
        assert "@@@" not in result['clean_text']
        assert "^^^" not in result['clean_text']
        assert "|||" not in result['clean_text']

    def test_parse_complete_example(self, sample_annotated_text):
        """Test parsing complete annotated example."""
        result = extract_annotations(sample_annotated_text)

        # Check insights
        assert len(result['insights']) == 2
        assert any("caching reduces database queries" in insight for insight in result['insights'])

        # Check entities
        assert len(result['entities']) >= 4
        assert ('concept', 'caching') in result['entities']
        assert ('technology', 'Redis') in result['entities']

        # Check relationships
        assert len(result['relationships']) >= 3
        assert ('caching', 'reduces_load_on', 'PostgreSQL') in result['relationships']
        assert ('Redis', 'integrates_with', 'Python') in result['relationships']

        # Check clean text
        assert "For your API" in result['clean_text']
        assert "@@@" not in result['clean_text']

    def test_malformed_entity(self):
        """Test handling of malformed entity (missing colon)."""
        text = "^^^ badentity, concept:good\n"
        result = extract_annotations(text)

        # Should only parse the valid entity
        assert len(result['entities']) == 1
        assert result['entities'][0] == ('concept', 'good')

    def test_malformed_relationship(self):
        """Test handling of malformed relationship (wrong number of parts)."""
        text = "||| only|two\n||| good|relationship|here\n"
        result = extract_annotations(text)

        # Should only parse the valid relationship
        assert len(result['relationships']) == 1
        assert result['relationships'][0] == ('good', 'relationship', 'here')

    def test_empty_annotation(self):
        """Test parsing text with no annotations."""
        text = "Just plain text with no annotations."
        result = extract_annotations(text)

        assert len(result['insights']) == 0
        assert len(result['entities']) == 0
        assert len(result['relationships']) == 0
        assert result['clean_text'] == text.strip()

    def test_special_characters_in_values(self):
        """Test handling special characters in entity values."""
        text = "^^^ tech:C++, framework:ASP.NET\n"
        result = extract_annotations(text)

        values = [e[1] for e in result['entities']]
        assert "C++" in values
        assert "ASP.NET" in values

    def test_whitespace_handling(self):
        """Test handling of whitespace in annotations."""
        text = "^^^  tech:Redis  ,  language:Python  \n"
        result = extract_annotations(text)

        # Should strip whitespace from types and values
        assert len(result['entities']) == 2
        for entity_type, value in result['entities']:
            assert entity_type.strip() == entity_type
            assert value.strip() == value


class TestStorageFormat:
    """Test the plain text storage format."""

    def test_annotations_file_path(self):
        """Test that annotations file path is correct."""
        with tempfile.TemporaryDirectory() as temp_dir:
            persona_dir = Path(temp_dir)
            annotations_file = _get_annotations_file(persona_dir)

            assert annotations_file == persona_dir / "knowledge_graph" / "annotations.txt"
            # Directory should be created
            assert annotations_file.parent.exists()

    def test_timestamp_format(self):
        """Test timestamp formatting."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Should be in YYYY-MM-DD HH:MM:SS format
        assert len(timestamp) == 19
        assert timestamp[4] == '-'
        assert timestamp[7] == '-'
        assert timestamp[10] == ' '
        assert timestamp[13] == ':'
        assert timestamp[16] == ':'

    def test_metadata_prefix_format(self):
        """Test the metadata prefix format."""
        timestamp = "2024-01-15 12:00:00"
        session_id = "test123"
        insight = "test insight"

        line = f"[{timestamp}][session:{session_id}] @@@ {insight}"

        # Should start with timestamp
        assert line.startswith("[2024-01-15 12:00:00]")
        # Should include session ID
        assert "[session:test123]" in line
        # Should include annotation marker
        assert " @@@ " in line
        # Should include content
        assert line.endswith("test insight")

    def test_parse_date_from_line(self):
        """Test extracting date from annotated line."""
        line = "[2024-01-15 12:00:00][session:abc] @@@ test"

        # Extract date (first 10 chars after '[')
        date_str = line[1:11]
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()

        assert parsed_date == date(2024, 1, 15)

    def test_parse_session_from_line(self):
        """Test extracting session ID from annotated line."""
        line = "[2024-01-15 12:00:00][session:abc123] @@@ test"

        # Extract session ID
        session_part = line.split('[session:')[1].split(']')[0]

        assert session_part == "abc123"


class TestAnnotationTypes:
    """Test different annotation types."""

    def test_insight_format(self):
        """Test insight line format."""
        timestamp = "2024-01-15 12:00:00"
        session_id = "test"
        insight = "this is an insight"

        line = f"[{timestamp}][session:{session_id}] @@@ {insight}"

        assert "@@@ this is an insight" in line

    def test_entity_format(self):
        """Test entity line format."""
        timestamp = "2024-01-15 12:00:00"
        session_id = "test"
        entity_type = "technology"
        value = "Redis"

        line = f"[{timestamp}][session:{session_id}] ^^^ {entity_type}:{value}"

        assert "^^^ technology:Redis" in line

    def test_relationship_format(self):
        """Test relationship line format."""
        timestamp = "2024-01-15 12:00:00"
        session_id = "test"
        subj = "Redis"
        pred = "uses"
        obj = "Python"

        line = f"[{timestamp}][session:{session_id}] ||| {subj}|{pred}|{obj}"

        assert "||| Redis|uses|Python" in line


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_multiline_insight_not_supported(self):
        """Test that insights are single line."""
        text = "@@@ this is a single line insight\n"
        result = extract_annotations(text)

        assert len(result['insights']) == 1
        assert "this is a single line insight" in result['insights']

    def test_multiple_entities_per_line(self):
        """Test multiple entities on one line."""
        text = "^^^ tech:Redis, tech:Docker, language:Python\n"
        result = extract_annotations(text)

        assert len(result['entities']) == 3

    def test_empty_lines_ignored(self):
        """Test that empty lines don't cause issues."""
        text = """

@@@ insight


^^^ tech:Redis


||| a|b|c

"""
        result = extract_annotations(text)

        assert len(result['insights']) == 1
        assert len(result['entities']) == 1
        assert len(result['relationships']) == 1

    def test_markers_in_regular_text(self):
        """Test that markers in regular text aren't extracted."""
        text = "This text mentions @@@ but not at line start\nAnd ^^^ in the middle\nAnd ||| here too"
        result = extract_annotations(text)

        # Should not extract these since they're not at line start
        assert len(result['insights']) == 0
        assert len(result['entities']) == 0
        assert len(result['relationships']) == 0
