"""Test the knowledge graph annotation system."""

import json
import tempfile
from pathlib import Path
import pytest

from silica.developer.knowledge_graph import (
    parse_kg_annotations,
    KGAnnotationParser,
    validate_annotation,
    Entity,
    Relationship,
    Annotation,
    KnowledgeGraph,
    AnnotationStorage,
)


@pytest.fixture
def temp_storage_dir():
    """Create a temporary directory for storage testing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


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


class TestKGAnnotationParser:
    """Test the annotation parser."""

    def test_parse_insights(self):
        """Test parsing insights from @@@ markers."""
        text = """Some text here.
@@@ this is an insight
More text.
@@@ another insight
"""
        parser = KGAnnotationParser()
        annotation = parser.parse(text)

        assert len(annotation.insights) == 2
        assert "this is an insight" in annotation.insights
        assert "another insight" in annotation.insights

    def test_parse_entities(self):
        """Test parsing entities from ^^^ markers."""
        text = "Some text.\n^^^ concept:caching, technology:Redis, language:Python\n"
        parser = KGAnnotationParser()
        annotation = parser.parse(text)

        assert len(annotation.entities) == 3
        types = [e.type for e in annotation.entities]
        values = [e.value for e in annotation.entities]

        assert "concept" in types
        assert "technology" in types
        assert "language" in types
        assert "caching" in values
        assert "Redis" in values
        assert "Python" in values

    def test_parse_relationships(self):
        """Test parsing relationships from ||| markers."""
        text = "Some text.\n||| Redis|integrates_with|Python\n||| caching|improves|performance\n"
        parser = KGAnnotationParser()
        annotation = parser.parse(text)

        assert len(annotation.relationships) == 2

        rel1 = annotation.relationships[0]
        assert rel1.subject == "Redis"
        assert rel1.predicate == "integrates_with"
        assert rel1.object == "Python"

        rel2 = annotation.relationships[1]
        assert rel2.subject == "caching"
        assert rel2.predicate == "improves"
        assert rel2.object == "performance"

    def test_clean_text_removal(self):
        """Test that annotations are removed from clean text."""
        text = """Here is some text.
@@@ an insight
^^^ concept:test
||| a|b|c
More text here."""

        parser = KGAnnotationParser()
        annotation = parser.parse(text)

        assert "Here is some text." in annotation.clean_text
        assert "More text here." in annotation.clean_text
        assert "@@@" not in annotation.clean_text
        assert "^^^" not in annotation.clean_text
        assert "|||" not in annotation.clean_text

    def test_parse_complete_example(self, sample_annotated_text):
        """Test parsing complete annotated example."""
        result = parse_kg_annotations(sample_annotated_text)

        # Check insights
        assert len(result['insights']) == 2
        assert any("caching reduces database queries" in insight for insight in result['insights'])

        # Check entities
        assert len(result['entities']) >= 4
        entity_dict = {etype: value for etype, value in result['entities']}
        assert 'concept' in [e[0] for e in result['entities']]
        assert 'technology' in [e[0] for e in result['entities']]

        # Check relationships
        assert len(result['relationships']) >= 3
        assert ('caching', 'reduces_load_on', 'PostgreSQL') in result['relationships']
        assert ('Redis', 'integrates_with', 'Python') in result['relationships']

        # Check clean text
        assert "For your API" in result['text']
        assert "@@@" not in result['text']

    def test_malformed_entity(self):
        """Test handling of malformed entity (missing colon)."""
        text = "^^^ badentity, concept:good\n"
        parser = KGAnnotationParser()
        annotation = parser.parse(text)

        # Should only parse the valid entity
        assert len(annotation.entities) == 1
        assert annotation.entities[0].type == "concept"
        assert annotation.entities[0].value == "good"

    def test_malformed_relationship(self):
        """Test handling of malformed relationship (wrong number of parts)."""
        text = "||| only|two\n||| good|relationship|here\n"
        parser = KGAnnotationParser()
        annotation = parser.parse(text)

        # Should only parse the valid relationship
        assert len(annotation.relationships) == 1
        assert annotation.relationships[0].subject == "good"


class TestValidation:
    """Test annotation validation."""

    def test_valid_annotation(self, sample_annotated_text):
        """Test validation of valid annotation."""
        validation = validate_annotation(sample_annotated_text)

        assert validation['valid'] is True
        assert len(validation['errors']) == 0

    def test_malformed_entity_validation(self):
        """Test validation catches malformed entities."""
        text = "^^^ badentity\n"
        validation = validate_annotation(text)

        assert validation['valid'] is False
        assert len(validation['errors']) > 0
        assert any("missing colon" in err.lower() for err in validation['errors'])

    def test_malformed_relationship_validation(self):
        """Test validation catches malformed relationships."""
        text = "||| only|two\n"
        validation = validate_annotation(text)

        assert validation['valid'] is False
        assert len(validation['errors']) > 0
        assert any("3 parts" in err for err in validation['errors'])


class TestModels:
    """Test data models."""

    def test_entity_creation(self):
        """Test entity creation and normalization."""
        entity = Entity(type="Technology", value="  Redis  ")

        # Should normalize type to lowercase and strip value
        assert entity.type == "technology"
        assert entity.value == "Redis"

    def test_entity_equality(self):
        """Test entity equality."""
        e1 = Entity(type="tech", value="Redis")
        e2 = Entity(type="tech", value="Redis")
        e3 = Entity(type="tech", value="Python")

        assert e1 == e2
        assert e1 != e3

    def test_entity_hashable(self):
        """Test that entities can be used in sets."""
        e1 = Entity(type="tech", value="Redis")
        e2 = Entity(type="tech", value="Redis")
        e3 = Entity(type="tech", value="Python")

        entity_set = {e1, e2, e3}
        assert len(entity_set) == 2  # e1 and e2 are duplicates

    def test_entity_serialization(self):
        """Test entity serialization."""
        entity = Entity(type="tech", value="Redis", metadata={"count": 5})

        # To dict
        data = entity.to_dict()
        assert data['type'] == "tech"
        assert data['value'] == "Redis"
        assert data['metadata']['count'] == 5

        # From dict
        entity2 = Entity.from_dict(data)
        assert entity2.type == entity.type
        assert entity2.value == entity.value
        assert entity2.metadata == entity.metadata

    def test_relationship_creation(self):
        """Test relationship creation and normalization."""
        rel = Relationship(subject=" Redis ", predicate="USES", object=" Python ")

        # Should strip and normalize predicate
        assert rel.subject == "Redis"
        assert rel.predicate == "uses"
        assert rel.object == "Python"

    def test_relationship_serialization(self):
        """Test relationship serialization."""
        rel = Relationship(
            subject="Redis",
            predicate="uses",
            object="Python",
            metadata={"confidence": 0.9}
        )

        # To dict
        data = rel.to_dict()
        assert data['subject'] == "Redis"
        assert data['predicate'] == "uses"
        assert data['object'] == "Python"
        assert data['metadata']['confidence'] == 0.9

        # From dict
        rel2 = Relationship.from_dict(data)
        assert rel2.subject == rel.subject
        assert rel2.predicate == rel.predicate
        assert rel2.object == rel.object

    def test_annotation_serialization(self):
        """Test annotation serialization."""
        annotation = Annotation(
            insights=["test insight"],
            entities=[Entity(type="tech", value="Redis")],
            relationships=[Relationship(subject="a", predicate="b", object="c")],
            clean_text="test text",
            source="test.md"
        )

        # To dict
        data = annotation.to_dict()
        assert len(data['insights']) == 1
        assert len(data['entities']) == 1
        assert len(data['relationships']) == 1

        # From dict
        annotation2 = Annotation.from_dict(data)
        assert annotation2.insights == annotation.insights
        assert len(annotation2.entities) == len(annotation.entities)
        assert len(annotation2.relationships) == len(annotation.relationships)

    def test_knowledge_graph(self):
        """Test knowledge graph construction."""
        graph = KnowledgeGraph()

        # Add first annotation
        annotation1 = Annotation(
            entities=[
                Entity(type="tech", value="Redis"),
                Entity(type="language", value="Python")
            ],
            relationships=[
                Relationship(subject="Redis", predicate="uses", object="Python")
            ]
        )
        graph.add_annotation(annotation1)

        # Add second annotation with overlapping entities
        annotation2 = Annotation(
            entities=[
                Entity(type="tech", value="Redis"),  # Duplicate
                Entity(type="database", value="PostgreSQL")
            ],
            relationships=[
                Relationship(subject="Redis", predicate="caches", object="PostgreSQL")
            ]
        )
        graph.add_annotation(annotation2)

        # Should have 2 annotations
        assert len(graph.annotations) == 2

        # Should deduplicate entities (3 unique entities)
        assert len(graph.get_all_entities()) == 3

        # Should have 2 unique relationships
        assert len(graph.get_all_relationships()) == 2

        # Test queries
        tech_entities = graph.get_entities_by_type("tech")
        assert len(tech_entities) == 1
        assert tech_entities[0].value == "Redis"

        uses_rels = graph.get_relationships_by_predicate("uses")
        assert len(uses_rels) == 1

        redis_rels = graph.get_related_entities("Redis")
        assert len(redis_rels) == 2  # Redis appears in both relationships


class TestStorage:
    """Test annotation storage."""

    def test_storage_initialization(self, temp_storage_dir):
        """Test storage initialization."""
        storage = AnnotationStorage(base_dir=temp_storage_dir)

        assert storage.base_dir.exists()
        assert storage.annotations_dir.exists()
        # No more entities_dir or relationships_dir - using grep-based queries
        # No more index.json - dynamic queries only

    def test_save_and_load_annotation(self, temp_storage_dir, sample_annotated_text):
        """Test saving and loading annotations."""
        storage = AnnotationStorage(base_dir=temp_storage_dir)

        # Parse and save
        result = parse_kg_annotations(sample_annotated_text, source="test.md")
        annotation = result['annotation']
        annotation_id = storage.save_annotation(annotation)

        assert annotation_id is not None

        # Load back
        loaded = storage.load_annotation(annotation_id)
        assert loaded is not None
        assert len(loaded.insights) == len(annotation.insights)
        assert len(loaded.entities) == len(annotation.entities)
        assert len(loaded.relationships) == len(annotation.relationships)

    def test_entity_indexing(self, temp_storage_dir):
        """Test entity querying with ripgrep."""
        storage = AnnotationStorage(base_dir=temp_storage_dir)

        annotation = Annotation(
            entities=[
                Entity(type="tech", value="Redis"),
                Entity(type="language", value="Python")
            ]
        )
        storage.save_annotation(annotation)

        # Query entities (now using grep, not indexes)
        tech_entities = storage.query_entities(entity_type="tech")
        assert len(tech_entities) == 1
        assert tech_entities[0].value == "Redis"

    def test_relationship_indexing(self, temp_storage_dir):
        """Test relationship querying with ripgrep."""
        storage = AnnotationStorage(base_dir=temp_storage_dir)

        annotation = Annotation(
            relationships=[
                Relationship(subject="Redis", predicate="uses", object="Python")
            ]
        )
        storage.save_annotation(annotation)

        # Query relationships (now using grep, not indexes)
        uses_rels = storage.query_relationships(predicate="uses")
        assert len(uses_rels) == 1
        assert uses_rels[0].subject == "Redis"

    def test_statistics(self, temp_storage_dir, sample_annotated_text):
        """Test storage statistics."""
        storage = AnnotationStorage(base_dir=temp_storage_dir)

        # Save annotation
        result = parse_kg_annotations(sample_annotated_text)
        storage.save_annotation(result['annotation'])

        # Get stats
        stats = storage.get_statistics()
        assert stats['total_annotations'] == 1
        assert len(stats['entity_types']) > 0
        assert len(stats['relationship_predicates']) > 0

    def test_build_knowledge_graph(self, temp_storage_dir, sample_annotated_text):
        """Test building knowledge graph from storage."""
        storage = AnnotationStorage(base_dir=temp_storage_dir)

        # Save multiple annotations
        result1 = parse_kg_annotations(sample_annotated_text)
        storage.save_annotation(result1['annotation'])

        text2 = "^^^ tech:Docker\n||| Docker|uses|Python\n"
        result2 = parse_kg_annotations(text2)
        storage.save_annotation(result2['annotation'])

        # Build graph
        graph = storage.build_knowledge_graph()
        assert len(graph.annotations) == 2
        assert len(graph.get_all_entities()) > 0

    def test_export_import(self, temp_storage_dir, sample_annotated_text):
        """Test export and import functionality."""
        storage = AnnotationStorage(base_dir=temp_storage_dir)

        # Save annotation
        result = parse_kg_annotations(sample_annotated_text)
        storage.save_annotation(result['annotation'])

        # Export
        export_path = temp_storage_dir / "export.json"
        storage.export_to_json(export_path)
        assert export_path.exists()

        # Create new storage and import
        storage2 = AnnotationStorage(base_dir=temp_storage_dir / "import")
        count = storage2.import_from_json(export_path)
        assert count == 1

        # Verify imported data
        stats = storage2.get_statistics()
        assert stats['total_annotations'] == 1

    def test_query_with_filters(self, temp_storage_dir):
        """Test querying with various filters."""
        storage = AnnotationStorage(base_dir=temp_storage_dir)

        # Save annotations with different entities
        annotation = Annotation(
            entities=[
                Entity(type="tech", value="Redis"),
                Entity(type="tech", value="RabbitMQ"),
                Entity(type="language", value="Python")
            ],
            relationships=[
                Relationship(subject="Redis", predicate="uses", object="Python"),
                Relationship(subject="RabbitMQ", predicate="uses", object="Python")
            ]
        )
        storage.save_annotation(annotation)

        # Query by type
        tech_entities = storage.query_entities(entity_type="tech")
        assert len(tech_entities) == 2

        # Query by value pattern
        redis_entities = storage.query_entities(value_pattern="Redis")
        assert len(redis_entities) == 1
        assert redis_entities[0].value == "Redis"

        # Query relationships by predicate
        uses_rels = storage.query_relationships(predicate="uses")
        assert len(uses_rels) == 2

        # Query relationships by subject
        redis_rels = storage.query_relationships(subject="Redis")
        assert len(redis_rels) == 1


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_annotation(self):
        """Test parsing text with no annotations."""
        text = "Just plain text with no annotations."
        result = parse_kg_annotations(text)

        assert len(result['insights']) == 0
        assert len(result['entities']) == 0
        assert len(result['relationships']) == 0
        assert result['text'] == text.strip()

    def test_special_characters_in_values(self):
        """Test handling special characters in entity values."""
        text = "^^^ tech:C++, framework:ASP.NET\n"
        parser = KGAnnotationParser()
        annotation = parser.parse(text)

        values = [e.value for e in annotation.entities]
        assert "C++" in values
        assert "ASP.NET" in values

    def test_multiline_insight(self):
        """Test that insights are single line."""
        text = "@@@ this is a single line insight\n"
        parser = KGAnnotationParser()
        annotation = parser.parse(text)

        assert len(annotation.insights) == 1
        assert "this is a single line insight" in annotation.insights

    def test_whitespace_handling(self):
        """Test handling of whitespace in annotations."""
        text = "^^^  tech:Redis  ,  language:Python  \n"
        parser = KGAnnotationParser()
        annotation = parser.parse(text)

        # Should strip whitespace from types and values
        assert len(annotation.entities) == 2
        for entity in annotation.entities:
            assert entity.type.strip() == entity.type
            assert entity.value.strip() == entity.value
