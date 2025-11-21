"""
Knowledge Graph Annotation System

A lightweight, inline annotation system for coding agents to extract structured
knowledge from conversational responses using minimally invasive text markers.
"""

from .parser import extract_annotations

__all__ = [
    'extract_annotations',
]

__version__ = '0.1.0'
