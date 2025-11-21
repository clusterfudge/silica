"""
Examples demonstrating the Knowledge Graph Annotation System.

This module contains practical examples of how to use the knowledge graph
annotation system for various use cases.
"""

from silica.developer.knowledge_graph import (
    parse_kg_annotations,
    AnnotationStorage,
    KnowledgeGraph,
    KGAnnotationParser,
    validate_annotation,
)


def example_basic_parsing():
    """Example: Basic annotation parsing."""
    print("=" * 60)
    print("Example 1: Basic Annotation Parsing")
    print("=" * 60)

    text = """
For your API, you should implement caching to reduce database load.
@@@ caching reduces database queries and improves response times
^^^ concept:caching, technology:Redis, database:PostgreSQL
||| caching|reduces_load_on|PostgreSQL

Redis is a good choice here since you're already using Python.
^^^ language:Python
||| Redis|integrates_with|Python
"""

    result = parse_kg_annotations(text)

    print("\nInsights:")
    for insight in result['insights']:
        print(f"  • {insight}")

    print("\nEntities:")
    for entity_type, value in result['entities']:
        print(f"  • {entity_type}: {value}")

    print("\nRelationships:")
    for subject, predicate, obj in result['relationships']:
        print(f"  • {subject} → {predicate} → {obj}")

    print("\nClean Text:")
    print(f"  {result['text'][:100]}...")
    print()


def example_storage_operations():
    """Example: Storage and retrieval operations."""
    print("=" * 60)
    print("Example 2: Storage Operations")
    print("=" * 60)

    # Initialize storage
    storage = AnnotationStorage()

    # Create and save annotations
    texts = [
        """
Docker provides containerization for applications.
@@@ containers ensure consistent environments across dev and prod
^^^ technology:Docker, concept:containerization
||| Docker|provides|containerization
""",
        """
Kubernetes orchestrates Docker containers at scale.
@@@ Kubernetes handles automatic scaling and load balancing
^^^ technology:Kubernetes, technology:Docker
||| Kubernetes|orchestrates|Docker
||| Kubernetes|enables|auto_scaling
"""
    ]

    print("\nSaving annotations...")
    for i, text in enumerate(texts):
        result = parse_kg_annotations(text, source=f"example_{i}.md")
        annotation_id = storage.save_annotation(result['annotation'])
        print(f"  ✓ Saved annotation: {annotation_id}")

    # Query entities
    print("\nQuerying entities (type='technology'):")
    tech_entities = storage.query_entities(entity_type="technology")
    for entity in tech_entities:
        print(f"  • {entity.value}")

    # Query relationships
    print("\nQuerying relationships (predicate='orchestrates'):")
    orch_rels = storage.query_relationships(predicate="orchestrates")
    for rel in orch_rels:
        print(f"  • {rel.subject} → {rel.predicate} → {rel.object}")

    # Get statistics
    print("\nStorage Statistics:")
    stats = storage.get_statistics()
    print(f"  Total annotations: {stats['total_annotations']}")
    print(f"  Entity types: {list(stats['entity_types'].keys())}")
    print(f"  Relationship predicates: {list(stats['relationship_predicates'].keys())}")
    print()


def example_knowledge_graph():
    """Example: Building a knowledge graph."""
    print("=" * 60)
    print("Example 3: Knowledge Graph Construction")
    print("=" * 60)

    graph = KnowledgeGraph()

    # Parse multiple annotations
    texts = [
        """
@@@ FastAPI provides automatic API documentation
^^^ framework:FastAPI, language:Python
||| FastAPI|uses|Python
""",
        """
@@@ Redis can be used for caching and session storage
^^^ technology:Redis, concept:caching
||| Redis|enables|caching
""",
        """
@@@ FastAPI integrates well with Redis for caching
^^^ framework:FastAPI, technology:Redis
||| FastAPI|integrates_with|Redis
"""
    ]

    print("\nBuilding knowledge graph...")
    for text in texts:
        result = parse_kg_annotations(text)
        graph.add_annotation(result['annotation'])

    print(f"  ✓ Added {len(graph.annotations)} annotations")

    # Query the graph
    print("\nAll entities:")
    for entity in graph.get_all_entities():
        print(f"  • {entity.type}: {entity.value}")

    print("\nAll relationships:")
    for rel in graph.get_all_relationships():
        print(f"  • {rel.subject} → {rel.predicate} → {rel.object}")

    print("\nRelated to 'FastAPI':")
    related = graph.get_related_entities("FastAPI")
    for rel in related:
        print(f"  • {rel.subject} → {rel.predicate} → {rel.object}")

    print()


def example_validation():
    """Example: Validating annotations."""
    print("=" * 60)
    print("Example 4: Annotation Validation")
    print("=" * 60)

    # Valid annotation
    valid_text = """
@@@ this is valid
^^^ tech:Redis
||| a|b|c
"""

    print("\nValidating valid annotation:")
    validation = validate_annotation(valid_text)
    print(f"  Valid: {validation['valid']}")
    print(f"  Errors: {validation['errors']}")
    print(f"  Warnings: {validation['warnings']}")

    # Invalid annotation
    invalid_text = """
^^^ missing_colon_here
||| only|two
"""

    print("\nValidating invalid annotation:")
    validation = validate_annotation(invalid_text)
    print(f"  Valid: {validation['valid']}")
    print(f"  Errors: {validation['errors']}")
    print(f"  Warnings: {validation['warnings']}")

    print()


def example_export_import():
    """Example: Export and import knowledge graph."""
    print("=" * 60)
    print("Example 5: Export and Import")
    print("=" * 60)

    # Create storage and add data
    storage1 = AnnotationStorage()

    text = """
@@@ microservices enable independent scaling
^^^ pattern:microservices, technology:Docker
||| microservices|deployed_with|Docker
"""

    result = parse_kg_annotations(text, source="architecture.md")
    storage1.save_annotation(result['annotation'])

    # Export
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        export_path = Path(tmpdir) / "export.json"

        print(f"\nExporting to: {export_path}")
        storage1.export_to_json(export_path)
        print("  ✓ Exported")

        # Import to new storage
        storage2 = AnnotationStorage(base_dir=Path(tmpdir) / "import")

        print(f"\nImporting from: {export_path}")
        count = storage2.import_from_json(export_path)
        print(f"  ✓ Imported {count} annotations")

        # Verify
        stats = storage2.get_statistics()
        print(f"\nImported storage stats:")
        print(f"  Total annotations: {stats['total_annotations']}")
        print(f"  Entity types: {stats['entity_types']}")

    print()


def example_complex_scenario():
    """Example: Complex real-world scenario."""
    print("=" * 60)
    print("Example 6: Complex Real-World Scenario")
    print("=" * 60)

    # Simulating a technical discussion about building a web application
    discussion = """
For your web application, I recommend using FastAPI as the backend framework.
@@@ FastAPI provides automatic OpenAPI documentation and async support
^^^ framework:FastAPI, language:Python, pattern:REST API
||| FastAPI|supports|async
||| FastAPI|generates|OpenAPI_docs

FastAPI works well with SQLAlchemy for database operations.
@@@ SQLAlchemy is a mature ORM with good PostgreSQL support
^^^ framework:SQLAlchemy, database:PostgreSQL
||| FastAPI|integrates_with|SQLAlchemy
||| SQLAlchemy|supports|PostgreSQL

For the frontend, React with TypeScript is a solid choice.
@@@ TypeScript adds type safety to JavaScript development
^^^ framework:React, language:TypeScript, language:JavaScript
||| React|uses|TypeScript
||| TypeScript|adds_type_safety_to|JavaScript

Deploy using Docker containers orchestrated by Kubernetes.
@@@ containers ensure consistent environments and easy scaling
^^^ technology:Docker, technology:Kubernetes, concept:containerization
||| Docker|provides|containerization
||| Kubernetes|orchestrates|Docker
||| Kubernetes|enables|scaling

Use Redis for caching to improve API response times.
@@@ caching reduces database load and improves performance
^^^ technology:Redis, concept:caching
||| Redis|enables|caching
||| caching|reduces_load_on|PostgreSQL
||| Redis|improves|API_performance
"""

    storage = AnnotationStorage()
    result = parse_kg_annotations(discussion, source="webapp_design.md")
    annotation_id = storage.save_annotation(result['annotation'])

    print(f"\nSaved complex annotation: {annotation_id}")
    print(f"  Insights: {len(result['insights'])}")
    print(f"  Entities: {len(result['entities'])}")
    print(f"  Relationships: {len(result['relationships'])}")

    # Build and query the graph
    graph = storage.build_knowledge_graph()

    print("\nTechnology stack identified:")
    tech_entities = graph.get_entities_by_type("framework")
    tech_entities += graph.get_entities_by_type("technology")
    for entity in tech_entities:
        print(f"  • {entity.value}")

    print("\nIntegration relationships:")
    integration_rels = graph.get_relationships_by_predicate("integrates_with")
    for rel in integration_rels:
        print(f"  • {rel.subject} ↔ {rel.object}")

    print("\nComponents related to PostgreSQL:")
    pg_rels = graph.get_related_entities("PostgreSQL")
    for rel in pg_rels:
        print(f"  • {rel.subject} → {rel.predicate} → {rel.object}")

    print()


def run_all_examples():
    """Run all examples."""
    examples = [
        example_basic_parsing,
        example_storage_operations,
        example_knowledge_graph,
        example_validation,
        example_export_import,
        example_complex_scenario,
    ]

    for example in examples:
        try:
            example()
        except Exception as e:
            print(f"Error in {example.__name__}: {e}")
            import traceback
            traceback.print_exc()
        print("\n")


if __name__ == "__main__":
    run_all_examples()
