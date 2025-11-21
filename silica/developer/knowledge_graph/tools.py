"""
Agent tools for knowledge graph operations.

These tools allow AI agents to interact with the knowledge graph annotation system.
"""

import json
from pathlib import Path
from typing import Optional

from silica.developer.context import AgentContext
from silica.developer.tools.framework import tool

from .parser import parse_kg_annotations, KGAnnotationParser, validate_annotation
from .storage import AnnotationStorage
from .models import KnowledgeGraph


@tool
def parse_annotations(context: "AgentContext", text: str, source: Optional[str] = None) -> str:
    """Parse knowledge graph annotations from text.

    This tool extracts structured knowledge from annotated text using inline markers:
    - @@@ insights (key learnings and takeaways)
    - ^^^ entities (type:value pairs, comma-separated)
    - ||| relationships (subject|predicate|object triples)

    Args:
        text: Text containing knowledge graph annotations
        source: Optional source identifier (e.g., file path, URL)

    Returns:
        Formatted summary of parsed annotations including:
        - Number of insights, entities, and relationships found
        - List of all extracted data
        - Clean text with annotations removed
    """
    result = parse_kg_annotations(text, source)

    # Format output
    lines = []
    lines.append("=== Parsed Knowledge Graph Annotations ===\n")

    # Summary
    lines.append(f"Insights: {len(result['insights'])}")
    lines.append(f"Entities: {len(result['entities'])}")
    lines.append(f"Relationships: {len(result['relationships'])}\n")

    # Details
    if result['insights']:
        lines.append("--- Insights ---")
        for insight in result['insights']:
            lines.append(f"  • {insight}")
        lines.append("")

    if result['entities']:
        lines.append("--- Entities ---")
        for entity_type, value in result['entities']:
            lines.append(f"  • {entity_type}: {value}")
        lines.append("")

    if result['relationships']:
        lines.append("--- Relationships ---")
        for subject, predicate, obj in result['relationships']:
            lines.append(f"  • {subject} → {predicate} → {obj}")
        lines.append("")

    lines.append("--- Clean Text ---")
    lines.append(result['text'])

    return "\n".join(lines)


@tool
def save_annotations(context: "AgentContext", text: str, source: Optional[str] = None) -> str:
    """Parse and save knowledge graph annotations to storage.

    Extracts annotations from text and persists them to the knowledge graph storage
    system for later querying and analysis.

    Args:
        text: Text containing knowledge graph annotations
        source: Optional source identifier (e.g., file path, URL)

    Returns:
        Confirmation message with annotation ID and statistics
    """
    # Initialize storage
    storage = AnnotationStorage()

    # Parse annotations
    result = parse_kg_annotations(text, source)
    annotation = result['annotation']

    # Save to storage
    annotation_id = storage.save_annotation(annotation)

    # Format output
    lines = []
    lines.append(f"✓ Saved annotation: {annotation_id}")
    lines.append(f"  Source: {source or 'unknown'}")
    lines.append(f"  Insights: {len(annotation.insights)}")
    lines.append(f"  Entities: {len(annotation.entities)}")
    lines.append(f"  Relationships: {len(annotation.relationships)}")

    return "\n".join(lines)


@tool
def query_knowledge_graph(
    context: "AgentContext",
    entity_type: Optional[str] = None,
    entity_value: Optional[str] = None,
    relationship_predicate: Optional[str] = None
) -> str:
    """Query the knowledge graph for entities and relationships.

    Search the stored knowledge graph annotations by entity type, value, or
    relationship predicate.

    Args:
        entity_type: Filter entities by type (e.g., "concept", "technology", "language")
        entity_value: Search for entities containing this value (substring match)
        relationship_predicate: Filter relationships by predicate (e.g., "uses", "implements")

    Returns:
        Formatted list of matching entities and/or relationships

    Examples:
        - query_knowledge_graph(entity_type="technology") → all technology entities
        - query_knowledge_graph(entity_value="Redis") → entities containing "Redis"
        - query_knowledge_graph(relationship_predicate="uses") → all "uses" relationships
    """
    storage = AnnotationStorage()
    lines = []

    # Query entities if type or value specified
    if entity_type or entity_value:
        entities = storage.query_entities(entity_type, entity_value)

        lines.append("=== Entities ===")
        if entities:
            for entity in entities:
                annotations_count = len(entity.metadata.get('annotations', []))
                lines.append(f"  • {entity.type}: {entity.value} ({annotations_count} annotations)")
        else:
            lines.append("  No matching entities found.")
        lines.append("")

    # Query relationships if predicate specified
    if relationship_predicate:
        relationships = storage.query_relationships(predicate=relationship_predicate)

        lines.append("=== Relationships ===")
        if relationships:
            for rel in relationships:
                annotations_count = len(rel.metadata.get('annotations', []))
                lines.append(f"  • {rel.subject} → {rel.predicate} → {rel.object} ({annotations_count} annotations)")
        else:
            lines.append("  No matching relationships found.")
        lines.append("")

    if not lines:
        return "Please specify at least one query parameter (entity_type, entity_value, or relationship_predicate)"

    return "\n".join(lines)


@tool
def get_kg_statistics(context: "AgentContext") -> str:
    """Get statistics about the stored knowledge graph.

    Returns summary information about the knowledge graph including:
    - Total number of annotations
    - Entity type distribution
    - Relationship predicate distribution
    - Storage location

    Returns:
        Formatted statistics report
    """
    storage = AnnotationStorage()
    stats = storage.get_statistics()

    lines = []
    lines.append("=== Knowledge Graph Statistics ===\n")

    lines.append(f"Total Annotations: {stats['total_annotations']}")
    lines.append(f"Storage Location: {stats['storage_path']}")
    if stats.get('created'):
        lines.append(f"Created: {stats['created']}")
    lines.append("")

    # Entity types
    lines.append("--- Entity Types ---")
    if stats['entity_types']:
        for entity_type, count in sorted(stats['entity_types'].items(), key=lambda x: -x[1]):
            lines.append(f"  • {entity_type}: {count}")
    else:
        lines.append("  No entities yet.")
    lines.append("")

    # Relationship predicates
    lines.append("--- Relationship Predicates ---")
    if stats['relationship_predicates']:
        for predicate, count in sorted(stats['relationship_predicates'].items(), key=lambda x: -x[1]):
            lines.append(f"  • {predicate}: {count}")
    else:
        lines.append("  No relationships yet.")

    return "\n".join(lines)


@tool
def validate_kg_annotations(context: "AgentContext", text: str) -> str:
    """Validate knowledge graph annotation syntax.

    Checks annotation syntax for errors and warnings without saving.
    Useful for debugging annotation formatting.

    Args:
        text: Text to validate

    Returns:
        Validation report with errors and warnings
    """
    validation = validate_annotation(text)

    lines = []
    lines.append("=== Annotation Validation ===\n")

    if validation['valid']:
        lines.append("✓ Valid annotation syntax")
    else:
        lines.append("✗ Invalid annotation syntax")

    if validation['errors']:
        lines.append("\n--- Errors ---")
        for error in validation['errors']:
            lines.append(f"  ✗ {error}")

    if validation['warnings']:
        lines.append("\n--- Warnings ---")
        for warning in validation['warnings']:
            lines.append(f"  ⚠ {warning}")

    if not validation['errors'] and not validation['warnings']:
        lines.append("\nNo errors or warnings found.")

    return "\n".join(lines)


@tool
def export_knowledge_graph(context: "AgentContext", output_path: str) -> str:
    """Export the entire knowledge graph to a JSON file.

    Creates a complete export of all annotations, entities, and relationships
    in JSON format for backup or analysis.

    Args:
        output_path: Path where the JSON file should be saved

    Returns:
        Confirmation message with export statistics
    """
    storage = AnnotationStorage()
    output_file = Path(output_path)

    # Export to JSON
    storage.export_to_json(output_file)

    # Get statistics
    stats = storage.get_statistics()

    lines = []
    lines.append(f"✓ Knowledge graph exported to: {output_path}")
    lines.append(f"  Total annotations: {stats['total_annotations']}")
    lines.append(f"  Entity types: {len(stats['entity_types'])}")
    lines.append(f"  Relationship predicates: {len(stats['relationship_predicates'])}")

    return "\n".join(lines)


@tool
def import_knowledge_graph(context: "AgentContext", input_path: str) -> str:
    """Import annotations from a JSON file.

    Loads annotations from a previously exported JSON file and adds them
    to the knowledge graph storage.

    Args:
        input_path: Path to the JSON file to import

    Returns:
        Confirmation message with import statistics
    """
    storage = AnnotationStorage()
    input_file = Path(input_path)

    if not input_file.exists():
        return f"✗ Error: File not found: {input_path}"

    # Import from JSON
    count = storage.import_from_json(input_file)

    return f"✓ Imported {count} annotations from: {input_path}"


@tool
def find_related_entities(context: "AgentContext", entity_value: str) -> str:
    """Find all relationships involving a specific entity.

    Searches for all relationships where the given entity appears as either
    the subject or object.

    Args:
        entity_value: The entity value to search for

    Returns:
        List of all relationships involving this entity
    """
    storage = AnnotationStorage()
    graph = storage.build_knowledge_graph()

    related = graph.get_related_entities(entity_value)

    lines = []
    lines.append(f"=== Relationships for '{entity_value}' ===\n")

    if related:
        for rel in related:
            annotations_count = len(rel.metadata.get('annotations', []))
            lines.append(f"  • {rel.subject} → {rel.predicate} → {rel.object} ({annotations_count} annotations)")
    else:
        lines.append(f"  No relationships found for '{entity_value}'")

    return "\n".join(lines)
