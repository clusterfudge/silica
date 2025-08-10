# Issue Tracking Integration

This document describes the integration with Plane.so for issue tracking in the Heare Developer CLI.

## Overview

The issue tracking integration allows users to:

1. Configure workspaces and API keys
2. Link projects to workspaces
3. Browse issues within those projects
4. View and add issues to conversations

## Configuration

### Configuration File

Issue tracking configuration is stored in `~/.config/hdev/issues.yml` with the following structure:

```yaml
workspaces:
  workspace-slug: <api-key>
  another-workspace-slug: <api-key>
projects:
  project-name:  # This is a project/repo name
    _id: 31e940e2-5f71-4f04-8fdb-e44567e891d6  # This is discovered from the API
    name: Project Display Name  # Optional display name, defaults to project/repo name
    workspace: workspace-slug
  another-project:
    _id: 82c2fe0d-9ade-4fca-ac65-a4b396c7049d
    name: Another Project
    workspace: another-workspace-slug
```

### Initializing Configuration

You can initialize issue tracking in two ways:

1. Using the slash command: `/config issues`
2. Using the CLI command: `heare-developer config issues`

The configuration process will:

1. Prompt you to add a workspace if none exists
2. Let you select a workspace
3. Present a list of projects from the selected workspace
4. Allow you to select an existing project or create a new one
5. Update the configuration file

## Using Issue Tracking

### Browsing Issues

To browse issues:

1. Using the slash command: `/issues` or `/i`
2. Using the CLI command: `heare-developer issues`

This will:

1. Let you select a project
2. Show a list of issues in that project
3. Display the full details of the selected issue
4. Give you the option to add the issue to the current conversation

## Implementation Details

### Slash Commands

The issue tracking feature provides these slash commands:

- `/config issues` - Initialize or update issue tracking configuration
- `/issues` or `/i` - Browse issues in configured projects

### Code Structure

The implementation is divided into several files:

1. `heare/developer/tools/issues.py` - Core API functions for Plane.so
2. `heare/developer/tools/issues_cli.py` - CLI interface for issue tracking

The implementation uses:

- `inquirer` for interactive selection menus
- `yaml` for configuration file handling
- Plane.so REST API for data retrieval

## Security Considerations

- API keys are stored in the configuration file, which is not encrypted
- Users should ensure their `~/.config/hdev` directory has appropriate permissions
- The implementation does not store session tokens, only API keys