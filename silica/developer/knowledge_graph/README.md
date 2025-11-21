# Knowledge Graph Annotation System

A lightweight, inline annotation system for coding agents to extract structured knowledge from conversational responses. The system uses minimally invasive text markers to capture insights, entities, and relationships without disrupting readability.

## Overview

The Knowledge Graph Annotation System allows AI agents (like those using silica) to extract and store structured knowledge from their own responses using simple inline markers. This enables:

- **Knowledge accumulation** across conversations
- **Relationship tracking** between concepts and technologies
- **Insight preservation** for future reference
- **Queryable knowledge base** that grows over time

## Design Goals

- **Minimal tokens**: Compact syntax to reduce API costs
- **Human readable**: Annotations blend naturally into conversation
- **No IDs required**: Direct references without indirection
- **Inline placement**: Context preserved by proximity to relevant text
- **Unambiguous markers**: Symbols that don't conflict with code syntax

## Annotation Format

### Syntax

```markdown
@@@ insight text here
^^^ type:value, type:value, type:value
||| subject|predicate|object
```

### Markers

| Marker | Purpose | Format |
|--------|---------|--------|
| `@@@` | Key insights and learnings | Free-form text |
| `^^^` | Entity type:value pairs | Comma-separated list |
| `\|\|\|` | Relationship tuples | Pipe-delimited triple |

### Rules

- Each annotation appears on its own line
- Place annotations near relevant context in the response
- Not every response requires annotations
- Choose types and predicates that best capture meaning

## Example Annotated Response

```markdown
For your API, you should implement caching to reduce database load.
@@@ caching reduces database queries and improves response times
^^^ concept:caching, technology:Redis, database:PostgreSQL
||| caching|reduces_load_on|PostgreSQL

Redis is a good choice here since you're already using Python.
^^^ language:Python
||| Redis|integrates_with|Python

The main consideration is memory usage versus hit rate.
@@@ balance memory allocation with cache hit rate for optimal performance
||| memory_usage|tradeoff|hit_rate
```

## Entity Types

These are suggested types - choose appropriate types based on context:

- `concept`: Abstract ideas, patterns, principles
- `tech`/`technology`: Tools, libraries, platforms
- `language`: Programming languages
- `framework`: Software frameworks
- `database`: Database systems
- `method`/`approach`: Techniques or methodologies
- `problem`: Issues or challenges
- `file`: Specific files or documents
- `person`: People or roles
- `org`/`organization`: Companies or teams

## Relationship Predicates

These are suggested predicates - choose appropriate predicates based on context:

- `uses`, `implements`, `requires`, `depends_on`
- `causes`, `solves`, `improves`, `fixes`
- `integrates_with`, `supports`, `enables`
- `reduces_load_on`, `optimizes`, `scales`
- `conflicts_with`, `tradeoff`, `alternative_to`
- `contains`, `part_of`, `extends`

## Integration with Silica

The knowledge graph system is integrated into silica as a set of agent tools. AI agents can use these tools to work with annotations:

### Available Agent Tools

#### `parse_annotations(text, source=None)`

Parse knowledge graph annotations from text.

```python
parse_annotations(
    text="""Your response with annotations...""",
    source="conversation_2024_01.md"
)
```

#### `save_annotations(text, source=None)`

Parse and save annotations to persistent storage.

```python
save_annotations(
    text="""Your response with annotations...""",
    source="api_discussion.md"
)
```

#### `query_knowledge_graph(entity_type=None, entity_value=None, relationship_predicate=None)`

Query the stored knowledge graph.

```python
# Find all technology entities
query_knowledge_graph(entity_type="technology")

# Search for entities containing "Redis"
query_knowledge_graph(entity_value="Redis")

# Find all "uses" relationships
query_knowledge_graph(relationship_predicate="uses")
```

#### `get_kg_statistics()`

Get statistics about the knowledge graph.

```python
get_kg_statistics()
# Returns: annotations count, entity types distribution, etc.
```

#### `validate_kg_annotations(text)`

Validate annotation syntax without saving.

```python
validate_kg_annotations(text="""
@@@ test insight
^^^ concept:test
||| a|b|c
""")
```

#### `export_knowledge_graph(output_path)`

Export entire knowledge graph to JSON.

```python
export_knowledge_graph(output_path="/tmp/knowledge_graph.json")
```

#### `import_knowledge_graph(input_path)`

Import annotations from JSON file.

```python
import_knowledge_graph(input_path="/tmp/knowledge_graph.json")
```

#### `find_related_entities(entity_value)`

Find all relationships involving an entity.

```python
find_related_entities(entity_value="Redis")
# Returns all relationships where Redis is subject or object
```

## Python API

You can also use the knowledge graph system programmatically:

### Basic Usage

```python
from silica.developer.knowledge_graph import (
    parse_kg_annotations,
    AnnotationStorage,
    KnowledgeGraph
)

# Parse annotations
text = """
Your response here...
@@@ important insight
^^^ tech:Redis, language:Python
||| Redis|uses|Python
"""

result = parse_kg_annotations(text)
print(result['insights'])       # List of insights
print(result['entities'])       # List of (type, value) tuples
print(result['relationships'])  # List of (subject, predicate, object) tuples
print(result['text'])           # Clean text without annotations
```

### Storage Operations

```python
from silica.developer.knowledge_graph import AnnotationStorage

# Initialize storage
storage = AnnotationStorage()

# Save an annotation
annotation = result['annotation']
annotation_id = storage.save_annotation(annotation)

# Load an annotation
loaded = storage.load_annotation(annotation_id)

# Query entities
tech_entities = storage.query_entities(entity_type="technology")

# Query relationships
uses_rels = storage.query_relationships(predicate="uses")

# Get statistics
stats = storage.get_statistics()

# Build complete knowledge graph
graph = storage.build_knowledge_graph()
```

### Knowledge Graph Operations

```python
from silica.developer.knowledge_graph import KnowledgeGraph

graph = KnowledgeGraph()

# Add annotations
graph.add_annotation(annotation1)
graph.add_annotation(annotation2)

# Query
all_entities = graph.get_all_entities()
tech_entities = graph.get_entities_by_type("technology")
uses_rels = graph.get_relationships_by_predicate("uses")
redis_rels = graph.get_related_entities("Redis")

# Export/Import
data = graph.to_dict()
graph2 = KnowledgeGraph.from_dict(data)
```

## Storage Structure

Annotations are stored in a hierarchical structure at `~/.hdev/knowledge_graph/`:

```
~/.hdev/knowledge_graph/
├── index.json                           # Master index
├── annotations/                         # Annotation files
│   ├── 20240115_120000_000000.json
│   └── 20240115_130000_000000.json
├── entities/                            # Entity index
│   ├── technology/
│   │   ├── Redis.json
│   │   └── Docker.json
│   └── language/
│       └── Python.json
└── relationships/                       # Relationship index
    ├── uses/
    │   └── Redis_Python.json
    └── integrates_with/
        └── Docker_Python.json
```

## When to Use Annotations

### Annotate When:

- Explaining technical concepts with key insights
- Making recommendations or architectural decisions
- Discussing performance considerations or tradeoffs
- Describing integration patterns
- Teaching best practices or methodologies

### Don't Annotate When:

- Simple acknowledgments or clarifications
- Pure conversational responses
- Requesting more information
- No substantive technical content present

## Best Practices

1. **Be selective**: Only annotate meaningful knowledge
2. **Stay contextual**: Place annotations near relevant text
3. **Use clear language**: Entity values and predicates should be self-explanatory
4. **Avoid redundancy**: Don't repeat obvious information
5. **Think graph-first**: Consider how entities will connect across conversations

## Examples

### Example 1: API Design Discussion

```markdown
For a scalable REST API, consider using FastAPI with Redis for caching.
@@@ FastAPI provides automatic API documentation and async support
^^^ framework:FastAPI, technology:Redis, pattern:REST API
||| FastAPI|supports|async
||| Redis|improves|API performance

Redis can cache expensive database queries significantly reducing latency.
@@@ caching database queries reduces response time from seconds to milliseconds
||| Redis|reduces_load_on|database
```

### Example 2: Architecture Decision

```markdown
I recommend a microservices architecture using Docker and Kubernetes.
@@@ microservices enable independent scaling and deployment
^^^ pattern:microservices, technology:Docker, technology:Kubernetes
||| microservices|deployed_with|Docker
||| Kubernetes|orchestrates|microservices

Each service can be scaled independently based on load.
||| microservices|enables|independent_scaling
```

### Example 3: Problem-Solution Pattern

```markdown
The N+1 query problem is common in ORMs like SQLAlchemy.
@@@ N+1 queries cause performance degradation by executing one query per item
^^^ problem:N+1 queries, framework:SQLAlchemy
||| SQLAlchemy|susceptible_to|N+1 queries

Use eager loading with joinedload() to solve this.
@@@ eager loading fetches related data in a single query
^^^ method:eager loading, function:joinedload
||| eager_loading|solves|N+1 queries
||| SQLAlchemy|implements|eager_loading
```

## Testing

Run the test suite:

```bash
pytest tests/developer/test_knowledge_graph.py -v
```

The test suite includes 30+ tests covering:
- Annotation parsing
- Validation
- Data models
- Storage operations
- Query functionality
- Edge cases

## Future Enhancements

Potential future additions:

- **Confidence scores**: Optional confidence indicators for uncertain annotations
- **Context IDs**: Link annotations to specific code blocks or sections
- **Temporal markers**: Track when insights become outdated
- **Source attribution**: Reference specific documents or conversations
- **Graph visualization**: Generate visual representations of the knowledge graph
- **Semantic search**: Find related entities and insights using embeddings
- **Auto-annotation**: Automatically suggest annotations based on content

## License

This is part of the silica project. See the main project LICENSE for details.
