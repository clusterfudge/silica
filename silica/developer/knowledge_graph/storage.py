"""
Storage layer for knowledge graph annotations.

Integrates with silica's memory system to persist annotations, entities,
and relationships in a queryable format.
"""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any, Set
from datetime import datetime

from .models import Annotation, Entity, Relationship, KnowledgeGraph


class AnnotationStorage:
    """
    Storage manager for knowledge graph annotations.

    Stores annotations in a hierarchical structure compatible with
    silica's memory system, namespaced by persona.
    """

    def __init__(self, base_dir: Optional[Path] = None, persona_dir: Optional[Path] = None):
        """
        Initialize the annotation storage.

        Args:
            base_dir: Base directory for storage (deprecated, use persona_dir instead)
            persona_dir: Persona directory (defaults to ~/.silica/personas/default)
        """
        if base_dir is not None:
            # Support legacy base_dir for backwards compatibility
            self.base_dir = base_dir
        elif persona_dir is not None:
            self.base_dir = persona_dir / "knowledge_graph"
        else:
            # Default to ~/.silica/personas/default/knowledge_graph
            self.base_dir = Path.home() / ".silica" / "personas" / "default" / "knowledge_graph"

        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Subdirectories for different data types
        self.annotations_dir = self.base_dir / "annotations"
        self.entities_dir = self.base_dir / "entities"
        self.relationships_dir = self.base_dir / "relationships"

        # Create subdirectories
        self.annotations_dir.mkdir(exist_ok=True)
        self.entities_dir.mkdir(exist_ok=True)
        self.relationships_dir.mkdir(exist_ok=True)

        # Create index file if it doesn't exist
        self._ensure_index()

    def _ensure_index(self):
        """Ensure the index file exists."""
        index_path = self.base_dir / "index.json"
        if not index_path.exists():
            with open(index_path, 'w') as f:
                json.dump({
                    'created': datetime.utcnow().isoformat(),
                    'annotations': [],
                    'entity_types': {},
                    'relationship_predicates': {}
                }, f, indent=2)

    def _load_index(self) -> Dict[str, Any]:
        """Load the index file."""
        index_path = self.base_dir / "index.json"
        with open(index_path, 'r') as f:
            return json.load(f)

    def _save_index(self, index: Dict[str, Any]):
        """Save the index file."""
        index_path = self.base_dir / "index.json"
        with open(index_path, 'w') as f:
            json.dump(index, f, indent=2)

    def save_annotation(self, annotation: Annotation,
                       annotation_id: Optional[str] = None) -> str:
        """
        Save an annotation to storage.

        Args:
            annotation: Annotation to save
            annotation_id: Optional ID (defaults to timestamp-based ID)

        Returns:
            The annotation ID
        """
        if annotation_id is None:
            timestamp = annotation.timestamp or datetime.utcnow()
            annotation_id = timestamp.strftime("%Y%m%d_%H%M%S_%f")

        # Save annotation file
        annotation_path = self.annotations_dir / f"{annotation_id}.json"
        with open(annotation_path, 'w') as f:
            json.dump(annotation.to_dict(), f, indent=2)

        # Update index
        index = self._load_index()

        # Add to annotation list if not already there
        if annotation_id not in index['annotations']:
            index['annotations'].append(annotation_id)

        # Update entity type counts
        for entity in annotation.entities:
            if entity.type not in index['entity_types']:
                index['entity_types'][entity.type] = 0
            index['entity_types'][entity.type] += 1

        # Update relationship predicate counts
        for rel in annotation.relationships:
            if rel.predicate not in index['relationship_predicates']:
                index['relationship_predicates'][rel.predicate] = 0
            index['relationship_predicates'][rel.predicate] += 1

        self._save_index(index)

        # Index entities and relationships
        self._index_entities(annotation, annotation_id)
        self._index_relationships(annotation, annotation_id)

        return annotation_id

    def _index_entities(self, annotation: Annotation, annotation_id: str):
        """Create entity index entries."""
        for entity in annotation.entities:
            # Create entity type directory if needed
            entity_type_dir = self.entities_dir / entity.type
            entity_type_dir.mkdir(exist_ok=True)

            # Create or update entity file
            entity_file = entity_type_dir / f"{self._sanitize_filename(entity.value)}.json"

            if entity_file.exists():
                with open(entity_file, 'r') as f:
                    entity_data = json.load(f)
            else:
                entity_data = {
                    'type': entity.type,
                    'value': entity.value,
                    'annotations': [],
                    'first_seen': datetime.utcnow().isoformat()
                }

            # Add annotation reference
            if annotation_id not in entity_data['annotations']:
                entity_data['annotations'].append(annotation_id)
            entity_data['last_seen'] = datetime.utcnow().isoformat()

            with open(entity_file, 'w') as f:
                json.dump(entity_data, f, indent=2)

    def _index_relationships(self, annotation: Annotation, annotation_id: str):
        """Create relationship index entries."""
        for rel in annotation.relationships:
            # Create relationship predicate directory if needed
            rel_predicate_dir = self.relationships_dir / rel.predicate
            rel_predicate_dir.mkdir(exist_ok=True)

            # Create or update relationship file
            rel_filename = f"{self._sanitize_filename(rel.subject)}_{self._sanitize_filename(rel.object)}.json"
            rel_file = rel_predicate_dir / rel_filename

            if rel_file.exists():
                with open(rel_file, 'r') as f:
                    rel_data = json.load(f)
            else:
                rel_data = {
                    'subject': rel.subject,
                    'predicate': rel.predicate,
                    'object': rel.object,
                    'annotations': [],
                    'first_seen': datetime.utcnow().isoformat()
                }

            # Add annotation reference
            if annotation_id not in rel_data['annotations']:
                rel_data['annotations'].append(annotation_id)
            rel_data['last_seen'] = datetime.utcnow().isoformat()

            with open(rel_file, 'w') as f:
                json.dump(rel_data, f, indent=2)

    def load_annotation(self, annotation_id: str) -> Optional[Annotation]:
        """
        Load an annotation by ID.

        Args:
            annotation_id: Annotation ID to load

        Returns:
            Annotation object or None if not found
        """
        annotation_path = self.annotations_dir / f"{annotation_id}.json"
        if not annotation_path.exists():
            return None

        with open(annotation_path, 'r') as f:
            data = json.load(f)

        return Annotation.from_dict(data)

    def load_all_annotations(self) -> List[Annotation]:
        """
        Load all annotations from storage.

        Returns:
            List of all Annotation objects
        """
        index = self._load_index()
        annotations = []

        for annotation_id in index['annotations']:
            annotation = self.load_annotation(annotation_id)
            if annotation:
                annotations.append(annotation)

        return annotations

    def build_knowledge_graph(self) -> KnowledgeGraph:
        """
        Build a complete knowledge graph from all stored annotations.

        Returns:
            KnowledgeGraph object containing all annotations
        """
        graph = KnowledgeGraph()
        for annotation in self.load_all_annotations():
            graph.add_annotation(annotation)
        return graph

    def query_entities(self, entity_type: Optional[str] = None,
                      value_pattern: Optional[str] = None) -> List[Entity]:
        """
        Query entities by type and/or value pattern.

        Args:
            entity_type: Filter by entity type (None for all types)
            value_pattern: Filter by value substring (None for all values)

        Returns:
            List of matching Entity objects
        """
        entities = []

        if entity_type:
            entity_type_dir = self.entities_dir / entity_type
            if entity_type_dir.exists():
                search_dirs = [entity_type_dir]
            else:
                return []
        else:
            search_dirs = [d for d in self.entities_dir.iterdir() if d.is_dir()]

        for entity_dir in search_dirs:
            for entity_file in entity_dir.glob("*.json"):
                with open(entity_file, 'r') as f:
                    entity_data = json.load(f)

                # Filter by value pattern
                if value_pattern and value_pattern.lower() not in entity_data['value'].lower():
                    continue

                entities.append(Entity(
                    type=entity_data['type'],
                    value=entity_data['value'],
                    metadata={
                        'annotations': entity_data.get('annotations', []),
                        'first_seen': entity_data.get('first_seen'),
                        'last_seen': entity_data.get('last_seen')
                    }
                ))

        return entities

    def query_relationships(self, subject: Optional[str] = None,
                          predicate: Optional[str] = None,
                          obj: Optional[str] = None) -> List[Relationship]:
        """
        Query relationships by subject, predicate, and/or object.

        Args:
            subject: Filter by subject (None for any)
            predicate: Filter by predicate (None for any)
            obj: Filter by object (None for any)

        Returns:
            List of matching Relationship objects
        """
        relationships = []

        if predicate:
            rel_predicate_dir = self.relationships_dir / predicate
            if rel_predicate_dir.exists():
                search_dirs = [rel_predicate_dir]
            else:
                return []
        else:
            search_dirs = [d for d in self.relationships_dir.iterdir() if d.is_dir()]

        for rel_dir in search_dirs:
            for rel_file in rel_dir.glob("*.json"):
                with open(rel_file, 'r') as f:
                    rel_data = json.load(f)

                # Filter by subject and object
                if subject and rel_data['subject'] != subject:
                    continue
                if obj and rel_data['object'] != obj:
                    continue

                relationships.append(Relationship(
                    subject=rel_data['subject'],
                    predicate=rel_data['predicate'],
                    object=rel_data['object'],
                    metadata={
                        'annotations': rel_data.get('annotations', []),
                        'first_seen': rel_data.get('first_seen'),
                        'last_seen': rel_data.get('last_seen')
                    }
                ))

        return relationships

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dictionary with statistics about stored data
        """
        index = self._load_index()

        return {
            'total_annotations': len(index['annotations']),
            'entity_types': index['entity_types'],
            'relationship_predicates': index['relationship_predicates'],
            'created': index.get('created'),
            'storage_path': str(self.base_dir)
        }

    def export_to_json(self, output_path: Path) -> None:
        """
        Export the entire knowledge graph to a JSON file.

        Args:
            output_path: Path to output JSON file
        """
        graph = self.build_knowledge_graph()
        with open(output_path, 'w') as f:
            json.dump(graph.to_dict(), f, indent=2)

    def import_from_json(self, input_path: Path) -> int:
        """
        Import annotations from a JSON file.

        Args:
            input_path: Path to input JSON file

        Returns:
            Number of annotations imported
        """
        with open(input_path, 'r') as f:
            data = json.load(f)

        graph = KnowledgeGraph.from_dict(data)
        count = 0

        for annotation in graph.annotations:
            self.save_annotation(annotation)
            count += 1

        return count

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """
        Sanitize a string for use as a filename.

        Args:
            name: String to sanitize

        Returns:
            Sanitized filename-safe string
        """
        # Replace problematic characters
        sanitized = name.replace('/', '_').replace('\\', '_')
        sanitized = sanitized.replace(':', '_').replace('*', '_')
        sanitized = sanitized.replace('?', '_').replace('"', '_')
        sanitized = sanitized.replace('<', '_').replace('>', '_')
        sanitized = sanitized.replace('|', '_').replace(' ', '_')

        # Limit length
        if len(sanitized) > 200:
            sanitized = sanitized[:200]

        return sanitized
