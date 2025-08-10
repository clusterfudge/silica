# GitHub Comment Tools

This document describes the GitHub comment interaction tools, which allow you to work with GitHub pull request comments, conversation comments, and review comments without requiring webhooks.

## Overview

The GitHub comment tools provide a way to interact with GitHub comments through polling rather than webhooks. This makes it suitable for environments where setting up webhook listeners isn't possible or desired.

These tools are built on top of the GitHub CLI (`gh`) and use the GitHub API through the CLI to interact with comments.

## Available Tools

### github_list_pr_comments

Lists all comments for a specific pull request, with options to filter by comment type.

```python
github_list_pr_comments(
    context: "AgentContext",
    pr_number: Union[int, str],
    type: Optional[str] = "all",  # "all", "inline", "conversation", or "review"
    repo: Optional[str] = None,
    show_details: bool = True,
) -> str
```

Example usage:
```
Show me all comments on PR #123
```

### github_get_comment

Gets detailed information about a specific GitHub comment by its ID.

```python
github_get_comment(
    context: "AgentContext",
    comment_id: str,
    comment_type: Optional[str] = "pr",  # "pr", "issue", or "review"
    repo: Optional[str] = None,
) -> str
```

Example usage:
```
Get details for comment ID 456789012
```

### github_add_pr_comment

Adds a new comment to a pull request, either as a conversation comment or an inline code comment.

```python
github_add_pr_comment(
    context: "AgentContext",
    pr_number: Union[int, str],
    body: str,
    commit_id: Optional[str] = None,  # Required for inline comments
    path: Optional[str] = None,  # Required for inline comments
    line: Optional[int] = None,  # Required for inline comments
    reply_to: Optional[str] = None,  # Optional, for replying to inline comments
    repo: Optional[str] = None,
) -> str
```

Example usage:
```
Add a comment to PR #123 saying "This looks good to me!"
```

For an inline comment:
```
Add an inline comment to PR #123 on file "src/main.py" at line 42 saying "Consider using a more descriptive variable name here"
```

### github_list_new_comments

Lists new comments on a pull request since a specific date.

```python
github_list_new_comments(
    context: "AgentContext",
    pr_number: Union[int, str],
    since: Optional[str] = None,  # ISO 8601 format date
    repo: Optional[str] = None,
) -> str
```

Example usage:
```
Show me new comments on PR #123 since 2023-04-01T00:00:00Z
```

## Implementation Details

The tools use the GitHub CLI's API functionality to make requests to the GitHub API. This approach leverages the authentication already set up for the GitHub CLI.

For inline comments, the tools interact with three different API endpoints:
1. Pull request review comments (inline code comments)
2. Issue comments (conversation comments)
3. Review comments (overall PR reviews)

## Design Principles

The tools were designed following principles from Kent Beck's "Tidy First":

1. **Single Responsibility**: Each function has a clear, well-defined purpose.
2. **Modularity**: The code is organized into helper functions and public tools.
3. **Testability**: Functions are designed to be easily testable, with proper mocking.
4. **Clean interfaces**: Tool functions have consistent parameter names and documentation.
5. **Semantic grouping**: Related functionality is grouped together.

## Testing

The GitHub comment tools include comprehensive tests that verify:

1. The behavior of helper functions
2. The proper handling of API responses
3. Error cases and edge conditions
4. Parameter validation

Tests use mocking to simulate the GitHub CLI responses.