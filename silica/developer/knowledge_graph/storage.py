"""
Storage layer for knowledge graph annotations.

Uses a simple file-based storage with ripgrep for dynamic queries.
No indexes - just annotations in timestamped JSON files.
"""

import json
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta

from .models import Annotation, Entity, Relationship, KnowledgeGraph


class AnnotationStorage:
    """
    Storage manager for knowledge graph annotations.

    Stores annotations as timestamped JSON files and uses ripgrep
    for dynamic queries. No separate indexes maintained.
    """

    def __init__(self, base_dir: Optional[Path] = None, persona_dir: Optional[Path] = None):
        """
        Initialize the annotation storage.

        Args:
            base_dir: Base directory for storage (deprecated, use persona_dir instead)
            persona_dir: Persona directory (defaults to ~/.silica/personas/default)
        """
        if base_dir is not None:
            # Support legacy base_dir for backwards compatibility (tests)
            self.base_dir = base_dir
        elif persona_dir is not None:
            self.base_dir = persona_dir / "knowledge_graph"
        else:
            # Default to ~/.silica/personas/default/knowledge_graph
            self.base_dir = Path.home() / ".silica" / "personas" / "default" / "knowledge_graph"

        self.base_dir.mkdir(parents=True, exist_ok=True)

        # Only annotations directory - no indexes
        self.annotations_dir = self.base_dir / "annotations"
        self.annotations_dir.mkdir(exist_ok=True)

    def _has_ripgrep(self) -> bool:
        """Check if ripgrep is available."""
        return shutil.which("rg") is not None

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

        return annotation_id

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
        annotations = []
        for annotation_file in sorted(self.annotations_dir.glob("*.json")):
            try:
                with open(annotation_file, 'r') as f:
                    data = json.load(f)
                annotations.append(Annotation.from_dict(data))
            except (json.JSONDecodeError, KeyError):
                # Skip malformed files
                continue

        return annotations

    def query_entities(self, entity_type: Optional[str] = None,
                      value_pattern: Optional[str] = None) -> List[Entity]:
        """
        Query entities by type and/or value pattern using ripgrep.

        Args:
            entity_type: Filter by entity type (None for all types)
            value_pattern: Filter by value substring (None for all values)

        Returns:
            List of matching Entity objects
        """
        if not self._has_ripgrep():
            # Fallback to loading all and filtering
            return self._query_entities_fallback(entity_type, value_pattern)

        # Build ripgrep pattern
        patterns = []
        if entity_type:
            patterns.append(f'"type":\\s*"{entity_type}"')
        if value_pattern:
            patterns.append(f'"value":\\s*"[^"]*{value_pattern}[^"]*"')

        if not patterns:
            # No filters - load all entities
            all_annotations = self.load_all_annotations()
            entities_dict = {}
            for annotation in all_annotations:
                for entity in annotation.entities:
                    key = (entity.type, entity.value)
                    entities_dict[key] = entity
            return list(entities_dict.values())

        # Use ripgrep to find matching files
        matching_files = set()
        for pattern in patterns:
            try:
                result = subprocess.run(
                    ['rg', '-l', pattern, str(self.annotations_dir), '--type', 'json'],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    matching_files.update(result.stdout.strip().split('\n'))
            except Exception:
                # Fallback on error
                return self._query_entities_fallback(entity_type, value_pattern)

        # Load annotations from matching files and extract entities
        entities_dict = {}
        for file_path in matching_files:
            if not file_path:
                continue
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                annotation = Annotation.from_dict(data)
                for entity in annotation.entities:
                    # Apply filters
                    if entity_type and entity.type != entity_type:
                        continue
                    if value_pattern and value_pattern.lower() not in entity.value.lower():
                        continue
                    key = (entity.type, entity.value)
                    entities_dict[key] = entity
            except (json.JSONDecodeError, KeyError):
                continue

        return list(entities_dict.values())

    def _query_entities_fallback(self, entity_type: Optional[str] = None,
                                 value_pattern: Optional[str] = None) -> List[Entity]:
        """Fallback query without ripgrep."""
        all_annotations = self.load_all_annotations()
        entities_dict = {}

        for annotation in all_annotations:
            for entity in annotation.entities:
                if entity_type and entity.type != entity_type:
                    continue
                if value_pattern and value_pattern.lower() not in entity.value.lower():
                    continue
                key = (entity.type, entity.value)
                entities_dict[key] = entity

        return list(entities_dict.values())

    def query_relationships(self, subject: Optional[str] = None,
                          predicate: Optional[str] = None,
                          obj: Optional[str] = None) -> List[Relationship]:
        """
        Query relationships by subject, predicate, and/or object using ripgrep.

        Args:
            subject: Filter by subject (None for any)
            predicate: Filter by predicate (None for any)
            obj: Filter by object (None for any)

        Returns:
            List of matching Relationship objects
        """
        if not self._has_ripgrep():
            return self._query_relationships_fallback(subject, predicate, obj)

        # Build ripgrep pattern
        patterns = []
        if subject:
            patterns.append(f'"subject":\\s*"{subject}"')
        if predicate:
            patterns.append(f'"predicate":\\s*"{predicate}"')
        if obj:
            patterns.append(f'"object":\\s*"{obj}"')

        if not patterns:
            # No filters - load all relationships
            all_annotations = self.load_all_annotations()
            relationships_dict = {}
            for annotation in all_annotations:
                for rel in annotation.relationships:
                    key = (rel.subject, rel.predicate, rel.object)
                    relationships_dict[key] = rel
            return list(relationships_dict.values())

        # Use ripgrep to find matching files
        matching_files = set()
        for pattern in patterns:
            try:
                result = subprocess.run(
                    ['rg', '-l', pattern, str(self.annotations_dir), '--type', 'json'],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    matching_files.update(result.stdout.strip().split('\n'))
            except Exception:
                return self._query_relationships_fallback(subject, predicate, obj)

        # Load annotations and extract relationships
        relationships_dict = {}
        for file_path in matching_files:
            if not file_path:
                continue
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                annotation = Annotation.from_dict(data)
                for rel in annotation.relationships:
                    # Apply filters
                    if subject and rel.subject != subject:
                        continue
                    if predicate and rel.predicate != predicate:
                        continue
                    if obj and rel.object != obj:
                        continue
                    key = (rel.subject, rel.predicate, rel.object)
                    relationships_dict[key] = rel
            except (json.JSONDecodeError, KeyError):
                continue

        return list(relationships_dict.values())

    def _query_relationships_fallback(self, subject: Optional[str] = None,
                                     predicate: Optional[str] = None,
                                     obj: Optional[str] = None) -> List[Relationship]:
        """Fallback query without ripgrep."""
        all_annotations = self.load_all_annotations()
        relationships_dict = {}

        for annotation in all_annotations:
            for rel in annotation.relationships:
                if subject and rel.subject != subject:
                    continue
                if predicate and rel.predicate != predicate:
                    continue
                if obj and rel.object != obj:
                    continue
                key = (rel.subject, rel.predicate, rel.object)
                relationships_dict[key] = rel

        return list(relationships_dict.values())

    def query_by_date_range(self, start_date: Optional[date] = None,
                           end_date: Optional[date] = None) -> List[Annotation]:
        """
        Query annotations within a date range.

        Uses filename patterns (YYYYMMDD_HHMMSS_ffffff.json) for efficient filtering.

        Args:
            start_date: Start date (inclusive, None for no lower bound)
            end_date: End date (inclusive, None for no upper bound)

        Returns:
            List of Annotation objects within the date range
        """
        annotations = []

        # Get all annotation files
        for annotation_file in sorted(self.annotations_dir.glob("*.json")):
            # Parse date from filename: YYYYMMDD_HHMMSS_ffffff.json
            try:
                filename = annotation_file.stem
                date_str = filename[:8]  # YYYYMMDD
                file_date = datetime.strptime(date_str, "%Y%m%d").date()

                # Check date range
                if start_date and file_date < start_date:
                    continue
                if end_date and file_date > end_date:
                    continue

                # Load annotation
                with open(annotation_file, 'r') as f:
                    data = json.load(f)
                annotations.append(Annotation.from_dict(data))
            except (ValueError, json.JSONDecodeError, KeyError):
                continue

        return annotations

    def get_recent_annotations(self, days: int = 7) -> List[Annotation]:
        """
        Get annotations from the last N days.

        Args:
            days: Number of days to look back

        Returns:
            List of recent Annotation objects
        """
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        return self.query_by_date_range(start_date, end_date)

    def get_recent_topics(self, days: int = 7) -> List[Entity]:
        """
        Get topics discussed in the last N days.

        Args:
            days: Number of days to look back

        Returns:
            List of unique Entity objects from recent annotations
        """
        recent_annotations = self.get_recent_annotations(days)
        entities_dict = {}

        for annotation in recent_annotations:
            for entity in annotation.entities:
                key = (entity.type, entity.value)
                entities_dict[key] = entity

        return list(entities_dict.values())

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

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get storage statistics.

        Returns:
            Dictionary with statistics about stored data
        """
        all_annotations = self.load_all_annotations()

        # Count entity types
        entity_types = {}
        for annotation in all_annotations:
            for entity in annotation.entities:
                entity_types[entity.type] = entity_types.get(entity.type, 0) + 1

        # Count relationship predicates
        relationship_predicates = {}
        for annotation in all_annotations:
            for rel in annotation.relationships:
                relationship_predicates[rel.predicate] = relationship_predicates.get(rel.predicate, 0) + 1

        return {
            'total_annotations': len(all_annotations),
            'entity_types': entity_types,
            'relationship_predicates': relationship_predicates,
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
