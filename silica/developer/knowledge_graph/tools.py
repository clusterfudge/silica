"""
Agent tools for knowledge graph operations.

Simple append-based storage with ripgrep queries.
"""

from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional
import subprocess
import shutil

from silica.developer.context import AgentContext
from silica.developer.tools.framework import tool

from .parser import extract_annotations


def _get_annotations_file(persona_dir: Path) -> Path:
    """Get the annotations file path for a persona."""
    kg_dir = persona_dir / "knowledge_graph"
    kg_dir.mkdir(parents=True, exist_ok=True)
    return kg_dir / "annotations.txt"


def _has_ripgrep() -> bool:
    """Check if ripgrep is available."""
    return shutil.which("rg") is not None


def _save_annotations_to_file(
    annotations_file: Path, annotations: dict, timestamp: str, session_id: str
) -> int:
    """Save annotations to file with timestamp and session ID.

    Args:
        annotations_file: Path to annotations file
        annotations: Dict with 'insights', 'entities', 'relationships' keys
        timestamp: Timestamp string (YYYY-MM-DD HH:MM:SS)
        session_id: Session ID

    Returns:
        Total number of annotations saved
    """
    lines = []

    # Add insights
    for insight in annotations['insights']:
        lines.append(f"[{timestamp}][session:{session_id}] @@@ {insight}")

    # Add entities
    for entity_type, value in annotations['entities']:
        lines.append(f"[{timestamp}][session:{session_id}] ^^^ {entity_type}:{value}")

    # Add relationships
    for subj, pred, obj in annotations['relationships']:
        lines.append(f"[{timestamp}][session:{session_id}] ||| {subj}|{pred}|{obj}")

    if lines:
        with open(annotations_file, 'a', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')

    return len(lines)


# NOTE: These are utility functions for testing and backwards compatibility.
# Annotations are now automatically extracted from agent responses in the agent loop.

def parse_annotations_util(text: str, source: Optional[str] = None) -> str:
    """Parse knowledge graph annotations from text (utility function).

    NOTE: Annotations are now automatically extracted from agent responses.
    This function is only kept for manual testing.

    Extracts @@@ insights, ^^^ topics, and ||| relationships.

    Args:
        text: Text containing annotations
        source: Optional source identifier

    Returns:
        Summary of extracted annotations
    """
    result = extract_annotations(text)

    lines = []
    lines.append("=== Parsed Annotations ===\n")
    lines.append(f"Insights: {len(result['insights'])}")
    lines.append(f"Topics: {len(result['entities'])}")
    lines.append(f"Relationships: {len(result['relationships'])}\n")

    if result['insights']:
        lines.append("--- Insights ---")
        for insight in result['insights']:
            lines.append(f"  • {insight}")
        lines.append("")

    if result['entities']:
        lines.append("--- Topics ---")
        for entity_type, value in result['entities']:
            lines.append(f"  • {entity_type}: {value}")
        lines.append("")

    if result['relationships']:
        lines.append("--- Relationships ---")
        for subj, pred, obj in result['relationships']:
            lines.append(f"  • {subj} → {pred} → {obj}")

    return "\n".join(lines)


def save_annotations_util(
    persona_dir: Path, text: str, session_id: str, source: Optional[str] = None
) -> str:
    """Save annotations to the knowledge graph (utility function).

    NOTE: Annotations are now automatically extracted from agent responses.
    This function is only kept for manual testing.

    Extracts annotations and appends them to the annotations file with timestamp and session ID.

    Args:
        persona_dir: Path to persona directory
        text: Text containing annotations
        session_id: Session ID
        source: Optional source identifier

    Returns:
        Confirmation message
    """
    result = extract_annotations(text)

    annotations_file = _get_annotations_file(persona_dir)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total = _save_annotations_to_file(annotations_file, result, timestamp, session_id)
    return f"✓ Saved {total} annotations ({len(result['insights'])} insights, {len(result['entities'])} topics, {len(result['relationships'])} relationships)"


@tool
def query_knowledge_graph(
    context: "AgentContext",
    entity_type: Optional[str] = None,
    entity_value: Optional[str] = None,
    relationship_predicate: Optional[str] = None
) -> str:
    """Query the knowledge graph using ripgrep.

    Args:
        entity_type: Filter by topic type (e.g., "technology", "concept")
        entity_value: Search for topic value (e.g., "Redis")
        relationship_predicate: Filter by relationship predicate (e.g., "uses")

    Returns:
        Matching annotations
    """
    persona_dir = context.history_base_dir or Path.home() / ".silica" / "personas" / "default"
    annotations_file = _get_annotations_file(persona_dir)

    if not annotations_file.exists():
        return "No annotations yet. Use save_annotations() to add some."

    results = []

    # Query entities
    if entity_type or entity_value:
        if entity_type:
            pattern = f"\\^\\^\\^ {entity_type}:"
        else:
            pattern = f"\\^\\^\\^ .*{entity_value}"

        if _has_ripgrep():
            result = subprocess.run(
                ['rg', pattern, str(annotations_file)],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                results.append("=== Topics ===")
                for line in result.stdout.strip().split('\n'):
                    if line:
                        results.append(f"  {line}")
        else:
            # Fallback to Python
            with open(annotations_file, 'r') as f:
                matches = [line.strip() for line in f if '^^^' in line and (
                    (entity_type and f"^^^ {entity_type}:" in line) or
                    (entity_value and entity_value in line)
                )]
                if matches:
                    results.append("=== Topics ===")
                    results.extend(f"  {m}" for m in matches)

    # Query relationships
    if relationship_predicate:
        pattern = f"\\|\\|\\| [^|]+\\|{relationship_predicate}\\|"

        if _has_ripgrep():
            result = subprocess.run(
                ['rg', pattern, str(annotations_file)],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                if results:
                    results.append("")
                results.append("=== Relationships ===")
                for line in result.stdout.strip().split('\n'):
                    if line:
                        results.append(f"  {line}")
        else:
            # Fallback
            with open(annotations_file, 'r') as f:
                matches = [line.strip() for line in f if '|||' in line and f"|{relationship_predicate}|" in line]
                if matches:
                    if results:
                        results.append("")
                    results.append("=== Relationships ===")
                    results.extend(f"  {m}" for m in matches)

    if not results:
        return "No matching annotations found."

    return "\n".join(results)


@tool
def get_recent_topics(context: "AgentContext", days: int = 7) -> str:
    """Get topics discussed in recent conversations.

    Args:
        days: Number of days to look back

    Returns:
        Recent topics grouped by type
    """
    persona_dir = context.history_base_dir or Path.home() / ".silica" / "personas" / "default"
    annotations_file = _get_annotations_file(persona_dir)

    if not annotations_file.exists():
        return "No annotations yet."

    # Calculate date range
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    # Read file and filter by date
    topics_by_type = {}

    with open(annotations_file, 'r') as f:
        for line in f:
            if '^^^' not in line:
                continue

            # Parse date from line: [2024-01-15 12:00:00]
            if line.startswith('['):
                date_str = line[1:11]  # YYYY-MM-DD
                try:
                    line_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    if line_date < start_date or line_date > end_date:
                        continue
                except ValueError:
                    continue

            # Extract topic
            if '^^^' in line:
                topic_part = line.split('^^^')[1].strip()
                if ':' in topic_part:
                    topic_type, value = topic_part.split(':', 1)
                    topic_type = topic_type.strip()
                    value = value.strip()

                    if topic_type not in topics_by_type:
                        topics_by_type[topic_type] = set()
                    topics_by_type[topic_type].add(value)

    if not topics_by_type:
        return f"No topics found in the last {days} day(s)"

    lines = []
    lines.append(f"=== Topics ({start_date} to {end_date}) ===\n")

    for topic_type in sorted(topics_by_type.keys()):
        lines.append(f"--- {topic_type.title()} ---")
        for value in sorted(topics_by_type[topic_type]):
            lines.append(f"  • {value}")
        lines.append("")

    return "\n".join(lines)


@tool
def query_by_date(context: "AgentContext", start_date: str, end_date: Optional[str] = None) -> str:
    """Query annotations by date range.

    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD), defaults to today

    Returns:
        Annotations from the date range
    """
    persona_dir = context.history_base_dir or Path.home() / ".silica" / "personas" / "default"
    annotations_file = _get_annotations_file(persona_dir)

    if not annotations_file.exists():
        return "No annotations yet."

    try:
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else date.today()
    except ValueError as e:
        return f"✗ Error: Invalid date format. Use YYYY-MM-DD. {str(e)}"

    # Use ripgrep with date pattern if available
    if _has_ripgrep():
        # Build pattern for date range (simple approach)
        results = []
        with open(annotations_file, 'r') as f:
            for line in f:
                if line.startswith('['):
                    date_str = line[1:11]
                    try:
                        line_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        if start <= line_date <= end:
                            results.append(line.rstrip())
                    except ValueError:
                        continue

        if not results:
            return f"No annotations found between {start} and {end}"

        return f"=== Annotations ({start} to {end}) ===\n\n" + "\n".join(results)
    else:
        # Fallback
        results = []
        with open(annotations_file, 'r') as f:
            for line in f:
                if line.startswith('['):
                    date_str = line[1:11]
                    try:
                        line_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        if start <= line_date <= end:
                            results.append(line.rstrip())
                    except ValueError:
                        continue

        if not results:
            return f"No annotations found between {start} and {end}"

        return f"=== Annotations ({start} to {end}) ===\n\n" + "\n".join(results)


@tool
def get_kg_statistics(context: "AgentContext") -> str:
    """Get knowledge graph statistics.

    Returns:
        Summary of annotations
    """
    persona_dir = context.history_base_dir or Path.home() / ".silica" / "personas" / "default"
    annotations_file = _get_annotations_file(persona_dir)

    if not annotations_file.exists():
        return "No annotations yet."

    insights_count = 0
    topics_count = 0
    relationships_count = 0

    with open(annotations_file, 'r') as f:
        for line in f:
            if '@@@' in line:
                insights_count += 1
            elif '^^^' in line:
                topics_count += 1
            elif '|||' in line:
                relationships_count += 1

    lines = []
    lines.append("=== Knowledge Graph Statistics ===\n")
    lines.append(f"Storage: {annotations_file}")
    lines.append(f"Total insights: {insights_count}")
    lines.append(f"Total topics: {topics_count}")
    lines.append(f"Total relationships: {relationships_count}")

    return "\n".join(lines)
