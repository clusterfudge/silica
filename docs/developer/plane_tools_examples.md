# Plane.so API Tools Examples

This document provides examples of how to use the Plane.so API integration tools in your agent interactions.

## Prerequisites

Before using these tools, you need to set up your Plane.so API key in one of two ways:

1. Create a file at `~/.plane-secret` containing your API key
2. Set the environment variable `PLANE_API_KEY`

You can get your API key from the Plane.so dashboard.

## Example Usage

Here are examples of how to use the Plane.so tools:

### Listing Workspaces

```
@tool list_plane_workspaces
```

This will return a list of all workspaces you have access to, including their names, slugs, and IDs.

### Listing Projects in a Workspace

```
@tool list_plane_projects workspace_slug="your-workspace-slug"
```

This will return all projects in the specified workspace.

### Getting Project Details

```
@tool get_plane_project_details workspace_slug="your-workspace-slug" project_id="project-id"
```

### Listing Issues in a Project

```
@tool list_plane_issues workspace_slug="your-workspace-slug" project_id="project-id"
```

To filter by state:

```
@tool list_plane_issues workspace_slug="your-workspace-slug" project_id="project-id" state_id="state-id"
```

### Getting Issue Details

```
@tool get_plane_issue_details workspace_slug="your-workspace-slug" project_id="project-id" issue_id="issue-id"
```

### Creating a New Issue

```
@tool create_plane_issue workspace_slug="your-workspace-slug" project_id="project-id" name="Issue Title" description="Issue description" priority="high"
```

### Updating an Issue

```
@tool update_plane_issue workspace_slug="your-workspace-slug" project_id="project-id" issue_id="issue-id" name="Updated Title" state_id="new-state-id"
```

### Adding a Comment to an Issue

```
@tool add_plane_issue_comment workspace_slug="your-workspace-slug" project_id="project-id" issue_id="issue-id" comment_text="This is a comment"
```

### Creating Links Between Issues

```
@tool create_plane_issue_link workspace_slug="your-workspace-slug" project_id="project-id" issue_id="issue-id" linked_issue_id="another-issue-id" relation="blocks"
```

Valid relation types: "blocks", "is_blocked_by", "relates_to", "duplicates", "is_duplicated_by"

### Creating Subtasks

```
@tool create_plane_subtask workspace_slug="your-workspace-slug" project_id="project-id" parent_issue_id="parent-issue-id" name="Subtask Title" description="Subtask description"
```

### Listing States/Statuses

```
@tool list_plane_states workspace_slug="your-workspace-slug" project_id="project-id"
```

### Listing Workspace Members

```
@tool list_plane_members workspace_slug="your-workspace-slug"
```

## Workflow Examples

### Complete Issue Management Workflow

1. List workspaces to get the workspace slug:
   ```
   @tool list_plane_workspaces
   ```

2. List projects in the workspace:
   ```
   @tool list_plane_projects workspace_slug="your-workspace"
   ```

3. List states in the project to get state IDs:
   ```
   @tool list_plane_states workspace_slug="your-workspace" project_id="your-project"
   ```

4. Create a new issue:
   ```
   @tool create_plane_issue workspace_slug="your-workspace" project_id="your-project" name="Implement feature X" description="We need to implement feature X to improve user experience" priority="high"
   ```

5. List members to find assignee IDs:
   ```
   @tool list_plane_members workspace_slug="your-workspace"
   ```

6. Update the issue to assign it:
   ```
   @tool update_plane_issue workspace_slug="your-workspace" project_id="your-project" issue_id="issue-id" assignee_id="user-id"
   ```

7. Create subtasks:
   ```
   @tool create_plane_subtask workspace_slug="your-workspace" project_id="your-project" parent_issue_id="issue-id" name="Research alternatives" priority="medium"
   ```

8. Add a comment with progress updates:
   ```
   @tool add_plane_issue_comment workspace_slug="your-workspace" project_id="your-project" issue_id="issue-id" comment_text="I've started researching options for this feature. Will update with findings tomorrow."
   ```

9. Update issue status when work progresses:
   ```
   @tool update_plane_issue workspace_slug="your-workspace" project_id="your-project" issue_id="issue-id" state_id="in-progress-state-id"
   ```