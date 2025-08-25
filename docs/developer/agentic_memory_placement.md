# Agentic Memory Placement

## Overview

The memory system now supports intelligent, AI-powered placement of memory entries. Instead of manually specifying where to store information, you can let an AI agent analyze your content and determine the optimal location within your memory hierarchy.

## How It Works

When you call `write_memory_entry` without specifying a path, the system:

1. **Analyzes your content** to understand its topic and purpose
2. **Examines the current memory tree** structure to identify relevant existing categories
3. **Searches for similar content** to determine if this should update an existing entry or create a new one
4. **Makes an intelligent placement decision** considering:
   - Semantic similarity to existing entries
   - Logical hierarchical organization
   - Consistency with existing naming patterns
   - Whether content should be merged with existing entries

## Usage Examples

### Automatic Placement
```python
# Let the agent decide where to place this content
await write_memory_entry(context, """
# React Component Library

A collection of reusable React components:
- Button variants
- Modal dialogs
- Form inputs with validation
""")

# Output: Memory entry created successfully at `projects/frontend/react_components`
# Placement Reasoning: This content about React components fits well under 
# projects/frontend since it's web-related technology...
```

### Manual Placement (Backward Compatible)
```python
# Explicitly specify where to place the content
await write_memory_entry(context, "Content here", path="specific/location")
```

## Agent Decision Process

The placement agent has access to these tools:
- `get_memory_tree`: Examine the current memory structure
- `read_memory_entry`: Check existing entries for similarity
- `search_memory`: Find related content across all memory

The agent follows this decision framework:

1. **Content Analysis**: What is this content about? What category does it belong to?
2. **Similarity Check**: Is there existing content that's very similar?
3. **Organization Assessment**: Where in the hierarchy would this fit best?
4. **Action Decision**: Should this CREATE a new entry or UPDATE an existing one?

## Decision Format

The agent returns decisions in this structured format:
```
DECISION: [CREATE|UPDATE]
PATH: [the/memory/path]
REASONING: [brief explanation of the decision]
```

## Error Handling

If the AI agent encounters any issues:
- Content is automatically placed at `misc/auto_placed`
- Error details are included in the reasoning
- The operation continues gracefully

## Benefits

- **Reduced Cognitive Load**: No need to think about hierarchical organization
- **Consistent Organization**: AI maintains consistent categorization patterns
- **Intelligent Updates**: Automatically identifies when to update vs. create new entries
- **Learning System**: The AI learns from your existing memory organization
- **Backward Compatible**: Existing workflows continue to work unchanged

## Configuration

The agentic placement uses the "smart" model (Claude Sonnet) by default for optimal reasoning about content organization. The system is designed to be cost-effective while providing high-quality placement decisions.

## Future Enhancements

Potential future improvements include:
- Learning from user corrections to placement decisions
- Batch organization of multiple related entries
- Automatic reorganization suggestions based on usage patterns
- Integration with external knowledge bases for enhanced categorization