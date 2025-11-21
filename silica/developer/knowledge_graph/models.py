"""
Data models for knowledge graph annotations.
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum


class EntityType(str, Enum):
    """Common entity types (extensible)."""
    CONCEPT = "concept"
    TECHNOLOGY = "tech"
    LANGUAGE = "language"
    FRAMEWORK = "framework"
    DATABASE = "database"
    METHOD = "method"
    APPROACH = "approach"
    PROBLEM = "problem"
    FILE = "file"
    PERSON = "person"
    ORGANIZATION = "org"
    LIBRARY = "library"
    TOOL = "tool"
    PATTERN = "pattern"
    CUSTOM = "custom"


class RelationshipType(str, Enum):
    """Common relationship predicates (extensible)."""
    USES = "uses"
    IMPLEMENTS = "implements"
    REQUIRES = "requires"
    DEPENDS_ON = "depends_on"
    CAUSES = "causes"
    SOLVES = "solves"
    IMPROVES = "improves"
    FIXES = "fixes"
    INTEGRATES_WITH = "integrates_with"
    SUPPORTS = "supports"
    ENABLES = "enables"
    REDUCES_LOAD_ON = "reduces_load_on"
    OPTIMIZES = "optimizes"
    SCALES = "scales"
    CONFLICTS_WITH = "conflicts_with"
    TRADEOFF = "tradeoff"
    ALTERNATIVE_TO = "alternative_to"
    CONTAINS = "contains"
    PART_OF = "part_of"
    EXTENDS = "extends"
    CUSTOM = "custom"


@dataclass
class Entity:
    """Represents an entity in the knowledge graph."""
    type: str
    value: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate and normalize entity."""
        self.type = self.type.strip().lower()
        self.value = self.value.strip()

    def __hash__(self):
        """Make entity hashable for use in sets."""
        return hash((self.type, self.value))

    def __eq__(self, other):
        """Entities are equal if type and value match."""
        if not isinstance(other, Entity):
            return False
        return self.type == other.type and self.value == other.value

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'type': self.type,
            'value': self.value,
            'metadata': self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Entity':
        """Create entity from dictionary."""
        return cls(
            type=data['type'],
            value=data['value'],
            metadata=data.get('metadata', {})
        )

    def __repr__(self):
        return f"Entity({self.type}:{self.value})"


@dataclass
class Relationship:
    """Represents a relationship triple in the knowledge graph."""
    subject: str
    predicate: str
    object: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate and normalize relationship."""
        self.subject = self.subject.strip()
        self.predicate = self.predicate.strip().lower()
        self.object = self.object.strip()

    def __hash__(self):
        """Make relationship hashable for use in sets."""
        return hash((self.subject, self.predicate, self.object))

    def __eq__(self, other):
        """Relationships are equal if all three components match."""
        if not isinstance(other, Relationship):
            return False
        return (self.subject == other.subject and
                self.predicate == other.predicate and
                self.object == other.object)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'subject': self.subject,
            'predicate': self.predicate,
            'object': self.object,
            'metadata': self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Relationship':
        """Create relationship from dictionary."""
        return cls(
            subject=data['subject'],
            predicate=data['predicate'],
            object=data['object'],
            metadata=data.get('metadata', {})
        )

    def __repr__(self):
        return f"Relationship({self.subject}|{self.predicate}|{self.object})"


@dataclass
class Annotation:
    """Represents a complete annotation block with context."""
    insights: List[str] = field(default_factory=list)
    entities: List[Entity] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    clean_text: str = ""
    source: Optional[str] = None
    timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Set timestamp if not provided."""
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'insights': self.insights,
            'entities': [e.to_dict() for e in self.entities],
            'relationships': [r.to_dict() for r in self.relationships],
            'clean_text': self.clean_text,
            'source': self.source,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'metadata': self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Annotation':
        """Create annotation from dictionary."""
        timestamp = data.get('timestamp')
        if timestamp and isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)

        return cls(
            insights=data.get('insights', []),
            entities=[Entity.from_dict(e) for e in data.get('entities', [])],
            relationships=[Relationship.from_dict(r) for r in data.get('relationships', [])],
            clean_text=data.get('clean_text', ''),
            source=data.get('source'),
            timestamp=timestamp,
            metadata=data.get('metadata', {})
        )

    def is_empty(self) -> bool:
        """Check if annotation contains any data."""
        return not (self.insights or self.entities or self.relationships)

    def __repr__(self):
        return (f"Annotation(insights={len(self.insights)}, "
                f"entities={len(self.entities)}, "
                f"relationships={len(self.relationships)})")


@dataclass
class KnowledgeGraph:
    """Represents a complete knowledge graph from multiple annotations."""
    annotations: List[Annotation] = field(default_factory=list)
    _entity_index: Dict[tuple, Entity] = field(default_factory=dict, repr=False)
    _relationship_index: Dict[tuple, Relationship] = field(default_factory=dict, repr=False)

    def add_annotation(self, annotation: Annotation):
        """Add an annotation to the graph."""
        self.annotations.append(annotation)

        # Index entities
        for entity in annotation.entities:
            key = (entity.type, entity.value)
            if key not in self._entity_index:
                self._entity_index[key] = entity

        # Index relationships
        for rel in annotation.relationships:
            key = (rel.subject, rel.predicate, rel.object)
            if key not in self._relationship_index:
                self._relationship_index[key] = rel

    def get_all_entities(self) -> List[Entity]:
        """Get all unique entities in the graph."""
        return list(self._entity_index.values())

    def get_all_relationships(self) -> List[Relationship]:
        """Get all unique relationships in the graph."""
        return list(self._relationship_index.values())

    def get_entities_by_type(self, entity_type: str) -> List[Entity]:
        """Get all entities of a specific type."""
        return [e for e in self._entity_index.values() if e.type == entity_type]

    def get_relationships_by_predicate(self, predicate: str) -> List[Relationship]:
        """Get all relationships with a specific predicate."""
        return [r for r in self._relationship_index.values() if r.predicate == predicate]

    def find_entity(self, entity_type: str, value: str) -> Optional[Entity]:
        """Find a specific entity by type and value."""
        return self._entity_index.get((entity_type, value))

    def get_related_entities(self, entity_value: str) -> List[Relationship]:
        """Get all relationships involving an entity (as subject or object)."""
        return [r for r in self._relationship_index.values()
                if r.subject == entity_value or r.object == entity_value]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'annotations': [a.to_dict() for a in self.annotations],
            'entities': [e.to_dict() for e in self.get_all_entities()],
            'relationships': [r.to_dict() for r in self.get_all_relationships()],
            'stats': {
                'total_annotations': len(self.annotations),
                'total_entities': len(self._entity_index),
                'total_relationships': len(self._relationship_index)
            }
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'KnowledgeGraph':
        """Create knowledge graph from dictionary."""
        graph = cls()
        for annotation_data in data.get('annotations', []):
            annotation = Annotation.from_dict(annotation_data)
            graph.add_annotation(annotation)
        return graph

    def __repr__(self):
        return (f"KnowledgeGraph(annotations={len(self.annotations)}, "
                f"entities={len(self._entity_index)}, "
                f"relationships={len(self._relationship_index)})")
