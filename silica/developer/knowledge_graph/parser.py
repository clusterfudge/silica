"""
Simple parser for knowledge graph annotations.

Extracts @@@, ^^^, and ||| markers using regex.
"""

import re


def extract_annotations(text: str) -> dict:
    """
    Extract annotations from text.

    Args:
        text: Text containing annotation markers

    Returns:
        Dict with 'insights', 'entities', and 'relationships' lists
    """
    # Extract insights
    insights = re.findall(r'^@@@ (.+)$', text, re.MULTILINE)

    # Extract entities (type:value pairs)
    entities = []
    for line in re.findall(r'^\^\^\^ (.+)$', text, re.MULTILINE):
        for pair in line.split(','):
            pair = pair.strip()
            if ':' in pair:
                entity_type, value = pair.split(':', 1)
                entities.append((entity_type.strip(), value.strip()))

    # Extract relationships (subject|predicate|object)
    relationships = []
    for line in re.findall(r'^\|\|\| (.+)$', text, re.MULTILINE):
        parts = line.split('|')
        if len(parts) == 3:
            relationships.append((
                parts[0].strip(),
                parts[1].strip(),
                parts[2].strip()
            ))

    # Clean text (remove annotations)
    clean_text = re.sub(r'^(@@@|\^\^\^|\|\|\|).+$\n?', '', text, flags=re.MULTILINE)

    return {
        'insights': insights,
        'entities': entities,
        'relationships': relationships,
        'clean_text': clean_text.strip()
    }
