# Persona Tools

Persona tools allow the AI model to inspect and modify its own persona definition, enabling self-improvement and adaptation based on user preferences.

## Overview

The model can now:
- Read its current persona instructions
- Update its persona to change behavior
- See exactly what it's editing through XML markup

All persona changes take effect immediately without requiring a restart.

## The Two Tools

### `read_persona()`

Read the content of the current persona file.

**Parameters:**
- None - always reads the current persona

**Example:**
```
read_persona()
```

**Returns:**
```
Persona: coding_agent
Path: /Users/you/.silica/personas/coding_agent/persona.md

# Autonomous Software Engineering Agent Instructions
...
```

### `write_persona(content)`

Write or update the current persona file.

**Parameters:**
- `content` (required): New persona content in markdown format

**Features:**
- Creates automatic timestamped backup before writing
- Validates content (not empty, max 100KB)
- Logs edit to `persona.log.jsonl`
- Changes take effect on next API call

**Example:**
```
write_persona(content="""
# Concise Coding Agent

## Core Principles
- Be extremely concise
- Show code, don't explain unless asked
- Make small, atomic commits
""")
```

**Returns:**
```
Successfully writed persona: coding_agent
File: /Users/you/.silica/personas/coding_agent/persona.md
Length: 123 characters
Backup: persona.backup.20250107_123456.md

The updated persona will take effect on the next system prompt render.
```

## Persona Markup

Persona content is wrapped in XML tags in the system prompt so the model knows what it's editing:

```
<persona name="coding_agent">
# Autonomous Software Engineering Agent Instructions

## Core Principles
...
</persona>
```

This makes it crystal clear which part of the system prompt is the persona.

## How It Works

### Startup
1. You start with `hdev --persona coding_agent`
2. If `~/.silica/personas/coding_agent/persona.md` exists, it's used
3. Otherwise, the built-in template for `coding_agent` is used
4. The persona is wrapped in `<persona>` tags in the system prompt

### Runtime Updates
1. Model calls `write_persona(content="...")`
2. Tool creates timestamped backup of old file
3. Writes new content to `persona.md`
4. Logs edit to `persona.log.jsonl`
5. Next API call reads fresh content from disk
6. Changes take effect immediately

### Priority Order
1. **First**: `persona.md` from disk (if exists)
2. **Second**: Built-in persona passed at startup
3. **Third**: Default system prompt

## Safety Features

### Automatic Backups
Every write creates a timestamped backup:
```
~/.silica/personas/my_persona/
  persona.md
  persona.backup.20250107_123456.md
  persona.backup.20250107_134512.md
```

### Edit Logging
All edits are logged to `persona.log.jsonl`:
```json
{"timestamp": "2025-01-07T12:34:56.789Z", "action": "create", "persona_name": "my_persona", "content_length": 1234}
{"timestamp": "2025-01-07T13:45:12.345Z", "action": "write", "persona_name": "my_persona", "content_length": 1567, "backup_path": "persona.backup.20250107_123456.md"}
```

### Content Validation
- Content cannot be empty
- Maximum size: 100KB
- Must be valid UTF-8 text

## Use Cases

### 1. Self-Refinement
The model notices it's being too verbose:
```
write_persona(content="""
# Concise Assistant

Be extremely concise. Avoid unnecessary explanations.
""")
```

### 2. User Adaptation
User says "always use bullet points":
```
write_persona(content="""
# Current persona content...

## Additional Guidelines
- Always format responses as bullet points
- Use clear, scannable structure
""")
```

### 3. Task-Specific Behavior
Switching to a specific mode:
```
write_persona(content="""
# Code Review Mode

When reviewing code:
- Focus on correctness and security
- Check for edge cases
- Suggest performance improvements
""")
```

### 4. Learning from Mistakes
Model realizes it made an error in approach:
```
write_persona(content="""
# Updated Guidelines

Previous approach was flawed. New rule:
- Always check X before doing Y
- Never assume Z without verification
""")
```

## File Structure

```
~/.silica/personas/
  my_persona/
    persona.md              # Current persona content
    persona.log.jsonl       # Edit history
    persona.backup.*.md     # Timestamped backups
    memory/                 # Persona-specific memory
```

## Best Practices

1. **Read before writing**: Always read the current persona first to understand what you're modifying
2. **Preserve structure**: Keep similar structure and formatting
3. **Be specific**: Clear, actionable instructions work best
4. **Document changes**: In the log, not the persona itself
5. **Test incrementally**: Make small changes and verify behavior

## Limitations

- Maximum file size: 100KB
- No automatic version control (use backups)
- Changes don't apply to current conversation (only next API call)
- No merge conflict resolution for concurrent edits
- Backups accumulate (manual cleanup needed)

## Future Enhancements

Potential future features (not yet implemented):
- `restore_persona_backup(backup_name)` tool
- Visual diff between versions
- Merge tool for combining persona aspects
- Automatic cleanup of old backups
- Version tagging and annotations
