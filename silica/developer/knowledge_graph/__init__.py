"""
Knowledge Graph Annotation System

A lightweight, inline annotation system for coding agents to extract structured
knowledge from conversational responses using minimally invasive text markers.
"""

from .models import Annotation, Entity, Relationship, KnowledgeGraph
from .parser import parse_kg_annotations, KGAnnotationParser, validate_annotation
from .storage import AnnotationStorage

__all__ = [
    'Annotation',
    'Entity',
    'Relationship',
    'KnowledgeGraph',
    'parse_kg_annotations',
    'KGAnnotationParser',
    'validate_annotation',
    'AnnotationStorage',
]

__version__ = '0.1.0'
