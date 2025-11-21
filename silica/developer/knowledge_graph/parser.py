"""
Parser for knowledge graph annotations.

Extracts structured knowledge from annotated text using inline markers:
- @@@ insights
- ^^^ entities
- ||| relationships
"""

import re
from typing import Dict, List, Tuple, Optional
from .models import Annotation, Entity, Relationship


class KGAnnotationParser:
    """Parser for knowledge graph annotation markers."""

    # Regex patterns for each annotation type
    INSIGHT_PATTERN = r'^@@@ (.+)$'
    ENTITY_PATTERN = r'^\^\^\^ (.+)$'
    RELATIONSHIP_PATTERN = r'^\|\|\| (.+)$'

    # Combined pattern to remove all annotations
    ANNOTATION_PATTERN = r'^(@@@|\^\^\^|\|\|\|).+$\n?'

    def __init__(self):
        """Initialize parser with compiled regex patterns."""
        self._insight_regex = re.compile(self.INSIGHT_PATTERN, re.MULTILINE)
        self._entity_regex = re.compile(self.ENTITY_PATTERN, re.MULTILINE)
        self._relationship_regex = re.compile(self.RELATIONSHIP_PATTERN, re.MULTILINE)
        self._annotation_regex = re.compile(self.ANNOTATION_PATTERN, re.MULTILINE)

    def parse(self, text: str, source: Optional[str] = None,
              metadata: Optional[Dict] = None) -> Annotation:
        """
        Parse knowledge graph annotations from text.

        Args:
            text: Raw text with annotations
            source: Optional source identifier (file path, URL, etc.)
            metadata: Optional metadata to attach to the annotation

        Returns:
            Annotation object containing parsed data
        """
        insights = self._parse_insights(text)
        entities = self._parse_entities(text)
        relationships = self._parse_relationships(text)
        clean_text = self._remove_annotations(text)

        return Annotation(
            insights=insights,
            entities=entities,
            relationships=relationships,
            clean_text=clean_text,
            source=source,
            metadata=metadata or {}
        )

    def _parse_insights(self, text: str) -> List[str]:
        """
        Extract insights from @@@ markers.

        Args:
            text: Text to parse

        Returns:
            List of insight strings
        """
        return self._insight_regex.findall(text)

    def _parse_entities(self, text: str) -> List[Entity]:
        """
        Extract and parse entities from ^^^ markers.

        Format: ^^^ type:value, type:value, type:value

        Args:
            text: Text to parse

        Returns:
            List of Entity objects
        """
        entities = []

        for line in self._entity_regex.findall(text):
            # Split by comma to get individual type:value pairs
            for pair in line.split(','):
                pair = pair.strip()
                if not pair:
                    continue

                # Split by first colon only
                if ':' not in pair:
                    # Handle malformed entity (no type specified)
                    continue

                parts = pair.split(':', 1)
                if len(parts) == 2:
                    entity_type, entity_value = parts
                    entities.append(Entity(
                        type=entity_type.strip(),
                        value=entity_value.strip()
                    ))

        return entities

    def _parse_relationships(self, text: str) -> List[Relationship]:
        """
        Extract and parse relationships from ||| markers.

        Format: ||| subject|predicate|object

        Args:
            text: Text to parse

        Returns:
            List of Relationship objects
        """
        relationships = []

        for line in self._relationship_regex.findall(text):
            # Split by pipe to get triple components
            parts = line.split('|')

            if len(parts) != 3:
                # Handle malformed relationship (not exactly 3 components)
                continue

            subject, predicate, obj = parts
            relationships.append(Relationship(
                subject=subject.strip(),
                predicate=predicate.strip(),
                object=obj.strip()
            ))

        return relationships

    def _remove_annotations(self, text: str) -> str:
        """
        Remove all annotation markers from text.

        Args:
            text: Text with annotations

        Returns:
            Clean text without annotation lines
        """
        clean = self._annotation_regex.sub('', text)
        return clean.strip()

    def parse_batch(self, texts: List[str],
                   sources: Optional[List[str]] = None) -> List[Annotation]:
        """
        Parse multiple texts in batch.

        Args:
            texts: List of texts to parse
            sources: Optional list of source identifiers (same length as texts)

        Returns:
            List of Annotation objects
        """
        if sources is None:
            sources = [None] * len(texts)

        if len(sources) != len(texts):
            raise ValueError("sources must be same length as texts if provided")

        return [self.parse(text, source) for text, source in zip(texts, sources)]


def parse_kg_annotations(text: str, source: Optional[str] = None,
                        metadata: Optional[Dict] = None) -> Dict:
    """
    Parse knowledge graph annotations from model response.

    This is a convenience function that returns a dictionary format
    compatible with the specification examples.

    Args:
        text: Raw model response with annotations
        source: Optional source identifier
        metadata: Optional metadata

    Returns:
        Dictionary containing:
        - insights: List of insight strings
        - entities: List of (type, value) tuples
        - relationships: List of (subject, predicate, object) tuples
        - text: Clean text with annotations removed
        - annotation: Full Annotation object
    """
    parser = KGAnnotationParser()
    annotation = parser.parse(text, source, metadata)

    return {
        'insights': annotation.insights,
        'entities': [(e.type, e.value) for e in annotation.entities],
        'relationships': [
            (r.subject, r.predicate, r.object)
            for r in annotation.relationships
        ],
        'text': annotation.clean_text,
        'annotation': annotation
    }


def extract_annotations_from_file(file_path: str) -> Annotation:
    """
    Extract annotations from a file.

    Args:
        file_path: Path to file containing annotations

    Returns:
        Annotation object
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        text = f.read()

    parser = KGAnnotationParser()
    return parser.parse(text, source=file_path)


def validate_annotation(text: str) -> Dict[str, any]:
    """
    Validate annotation syntax without parsing.

    Args:
        text: Text to validate

    Returns:
        Dictionary with validation results:
        - valid: bool
        - errors: List of error messages
        - warnings: List of warning messages
    """
    errors = []
    warnings = []

    # Check for malformed entities (^^^ lines without colons)
    entity_lines = re.findall(r'^\^\^\^ (.+)$', text, re.MULTILINE)
    for line in entity_lines:
        for pair in line.split(','):
            pair = pair.strip()
            if pair and ':' not in pair:
                errors.append(f"Malformed entity (missing colon): {pair}")

    # Check for malformed relationships (||| lines without exactly 3 parts)
    rel_lines = re.findall(r'^\|\|\| (.+)$', text, re.MULTILINE)
    for line in rel_lines:
        parts = line.split('|')
        if len(parts) != 3:
            errors.append(f"Malformed relationship (need 3 parts): {line}")
        elif any(not p.strip() for p in parts):
            warnings.append(f"Relationship has empty component: {line}")

    # Check for empty insights
    insight_lines = re.findall(r'^@@@ (.+)$', text, re.MULTILINE)
    for line in insight_lines:
        if not line.strip():
            warnings.append("Empty insight found")

    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    }
