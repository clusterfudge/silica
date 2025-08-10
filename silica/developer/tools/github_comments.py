"""GitHub comment interaction tools.

This module provides tools for interacting with GitHub comments, particularly
focused on inline comments from pull requests. It's designed to provide a simple
interface for polling comments rather than requiring webhooks.
"""

import json
import subprocess
from typing import Optional, Dict, Any, List, Union
from datetime import datetime

from silica.developer.context import AgentContext
from .framework import tool


def _run_gh_command(args: List[str]) -> Dict[str, Any]:
    """
    Run a GitHub CLI command and return the result.

    Args:
        args: List of command arguments

    Returns:
        Dictionary containing command results with 'success', 'data', and optional 'error' keys
    """
    try:
        result = subprocess.run(
            ["gh"] + args,
            capture_output=True,
            text=True,
            check=True,
        )
        return {"success": True, "data": result.stdout}
    except subprocess.CalledProcessError as e:
        return {
            "success": False,
            "error": f"Error: {e.stderr if e.stderr else str(e)}",
            "data": e.stdout if e.stdout else "",
        }


def _format_markdown_comments(
    comments: List[Dict[str, Any]], comment_type: str, show_details: bool = True
) -> str:
    """Format comment data as markdown.

    Args:
        comments: List of comment data from GitHub API
        comment_type: Type of comment (e.g., "Inline", "Conversation")
        show_details: Whether to show detailed information

    Returns:
        Formatted markdown string
    """
    if not comments:
        return ""

    output = f"## {comment_type} Comments ({len(comments)})\n\n"

    for comment in comments:
        user = comment.get("user", {}).get("login", "Unknown")
        created_at = comment.get("created_at", "Unknown date")

        # Try to parse and format the date
        try:
            date_obj = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            created_at = date_obj.strftime("%Y-%m-%d %H:%M:%S UTC")
        except (ValueError, TypeError):
            pass  # Keep original string if parsing fails

        # Add comment header with user and timestamp
        output += f"### {user} on {created_at}\n\n"

        # Add location details for inline comments
        if comment_type == "Inline" and show_details:
            path = comment.get("path", "Unknown file")
            comment.get("position")
            line = comment.get("line", comment.get("original_line"))

            if line:
                output += f"**File:** {path}, Line: {line}\n\n"
            else:
                output += f"**File:** {path}\n\n"

        # Add the comment body
        output += f"{comment.get('body', '')}\n\n"

        # Show if this comment is in a reply thread
        if comment.get("in_reply_to_id") and show_details:
            output += "(Reply to an earlier comment)\n\n"

    return output


@tool
def github_list_pr_comments(
    context: "AgentContext",
    pr_number: Union[int, str],
    type: Optional[str] = "all",
    repo: Optional[str] = None,
    show_details: bool = True,
) -> str:
    """List all comments for a specific pull request.

    This function retrieves comments of different types from a pull request.

    Args:
        pr_number: The pull request number
        type: Comment type to retrieve: "all", "inline", "conversation", or "review"
        repo: Repository in format [HOST/]OWNER/REPO (current repo used if not specified)
        show_details: Whether to show detailed information like file paths and lines
    """
    # Normalize the type parameter
    comment_type = type.lower() if type else "all"
    valid_types = ["all", "inline", "conversation", "review"]

    if comment_type not in valid_types:
        return f"Error: 'type' must be one of {valid_types}"

    # Build repo argument
    repo_arg = []
    if repo:
        repo_arg = ["--repo", repo]

    # Verify the PR exists
    pr_verify_cmd = ["pr", "view", str(pr_number), "--json", "number"] + repo_arg
    pr_result = _run_gh_command(pr_verify_cmd)

    if not pr_result["success"]:
        return pr_result["error"]

    output = f"# Comments for Pull Request #{pr_number}\n\n"

    # Get inline code comments (review comments)
    inline_comments = []
    if comment_type in ["all", "inline"]:
        inline_cmd = [
            "api",
            f"repos/:owner/:repo/pulls/{pr_number}/comments",
            "--jq",
            ".",
        ] + repo_arg
        inline_result = _run_gh_command(inline_cmd)

        if inline_result["success"]:
            try:
                inline_comments = json.loads(inline_result["data"])
                output += _format_markdown_comments(
                    inline_comments, "Inline", show_details
                )
            except json.JSONDecodeError:
                output += "Error parsing inline comments data\n\n"

    # Get PR conversation comments (issue comments)
    issue_comments = []
    if comment_type in ["all", "conversation"]:
        issue_cmd = [
            "api",
            f"repos/:owner/:repo/issues/{pr_number}/comments",
            "--jq",
            ".",
        ] + repo_arg
        issue_result = _run_gh_command(issue_cmd)

        if issue_result["success"]:
            try:
                issue_comments = json.loads(issue_result["data"])
                output += _format_markdown_comments(
                    issue_comments, "Conversation", show_details
                )
            except json.JSONDecodeError:
                output += "Error parsing conversation comments data\n\n"

    # Get review comments
    review_comments = []
    if comment_type in ["all", "review"]:
        review_cmd = [
            "api",
            f"repos/:owner/:repo/pulls/{pr_number}/reviews",
            "--jq",
            ".",
        ] + repo_arg
        review_result = _run_gh_command(review_cmd)

        if review_result["success"]:
            try:
                reviews = json.loads(review_result["data"])

                # Filter reviews to only include those with non-empty bodies
                review_comments = [
                    {**review, "body": review.get("body", "")}
                    for review in reviews
                    if review.get("body") and review["body"].strip()
                ]

                output += _format_markdown_comments(
                    review_comments, "Review", show_details
                )
            except json.JSONDecodeError:
                output += "Error parsing review comments data\n\n"

    # Check if we found any comments
    total_comments = len(inline_comments) + len(issue_comments) + len(review_comments)
    if total_comments == 0:
        output += "No comments found on this pull request."
    else:
        output += f"Total comments: {total_comments}"

    return output


@tool
def github_get_comment(
    context: "AgentContext",
    comment_id: str,
    comment_type: Optional[str] = "pr",
    repo: Optional[str] = None,
) -> str:
    """Get detailed information about a specific GitHub comment.

    Args:
        comment_id: The ID of the comment
        comment_type: Type of comment: "pr" (pull request), "issue", or "review"
        repo: Repository in format [HOST/]OWNER/REPO (current repo used if not specified)
    """
    # Build repo argument
    repo_arg = []
    if repo:
        repo_arg = ["--repo", repo]

    # Determine the API endpoint based on comment type
    if comment_type == "pr":
        endpoint = f"repos/:owner/:repo/pulls/comments/{comment_id}"
        comment_desc = "Pull Request Comment"
    elif comment_type == "issue":
        endpoint = f"repos/:owner/:repo/issues/comments/{comment_id}"
        comment_desc = "Issue Comment"
    elif comment_type == "review":
        endpoint = f"repos/:owner/:repo/pulls/reviews/{comment_id}"
        comment_desc = "Review Comment"
    else:
        return "Error: comment_type must be one of: pr, issue, review"

    # Get the comment data
    cmd = ["api", endpoint, "--jq", "."] + repo_arg
    result = _run_gh_command(cmd)

    if not result["success"]:
        return result["error"]

    try:
        comment = json.loads(result["data"])

        # Format the comment data
        output = f"# {comment_desc} (ID: {comment_id})\n\n"

        # User info
        user = comment.get("user", {}).get("login", "Unknown")
        output += f"**Author**: {user}\n"

        # Created and updated times
        created_at = comment.get("created_at", "Unknown")
        updated_at = comment.get("updated_at")
        output += f"**Created**: {created_at}\n"
        if updated_at and updated_at != created_at:
            output += f"**Updated**: {updated_at}\n"

        # For PR comments, show file and line info
        if comment_type == "pr":
            path = comment.get("path")
            line = comment.get("line")
            comment.get("position")
            original_line = comment.get("original_line")

            if path:
                output += f"**File**: {path}\n"
            if line or original_line:
                line_display = line or original_line
                output += f"**Line**: {line_display}\n"

            # Show if this is a reply
            in_reply_to = comment.get("in_reply_to_id")
            if in_reply_to:
                output += f"**Reply to**: Comment {in_reply_to}\n"

        # For review comments, show the state
        if comment_type == "review":
            state = comment.get("state", "Unknown")
            output += f"**State**: {state}\n"

        # Add URL if available
        html_url = comment.get("html_url")
        if html_url:
            output += f"**URL**: {html_url}\n"

        # Add the comment body
        output += f"\n## Comment Body\n\n{comment.get('body', '')}\n"

        return output
    except json.JSONDecodeError:
        return f"Error parsing comment data. Raw response:\n\n{result['data']}"


@tool
def github_add_pr_comment(
    context: "AgentContext",
    pr_number: Union[int, str],
    body: str,
    commit_id: Optional[str] = None,
    path: Optional[str] = None,
    line: Optional[int] = None,
    reply_to: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    """Add a comment to a pull request.

    This function can add both conversation comments and inline code comments.

    Args:
        pr_number: The pull request number
        body: The comment text
        commit_id: The commit SHA to comment on (required for inline comments)
        path: File path to comment on (required for inline comments)
        line: Line number to comment on (required for inline comments)
        reply_to: ID of comment to reply to (for inline comments)
        repo: Repository in format [HOST/]OWNER/REPO
    """
    # Build repo argument
    repo_arg = []
    if repo:
        repo_arg = ["--repo", repo]

    # Check if this is an inline comment or a regular PR comment
    is_inline = path is not None or line is not None or commit_id is not None

    # Verify the PR exists
    pr_verify_cmd = [
        "pr",
        "view",
        str(pr_number),
        "--json",
        "number,headRefOid",
    ] + repo_arg
    pr_result = _run_gh_command(pr_verify_cmd)

    if not pr_result["success"]:
        return pr_result["error"]

    try:
        pr_data = json.loads(pr_result["data"])
    except json.JSONDecodeError:
        return f"Error parsing PR data: {pr_result['data']}"

    # If we need a commit ID but don't have one, use the HEAD commit
    if is_inline and not commit_id:
        commit_id = pr_data.get("headRefOid")
        if not commit_id:
            return "Error: commit_id is required for inline comments and couldn't be determined automatically."

    # For inline comments, we need path and line
    if is_inline:
        if not path:
            return "Error: path is required for inline comments"
        if not line:
            return "Error: line is required for inline comments"

        # Create an inline comment
        comment_data = {
            "body": body,
            "commit_id": commit_id,
            "path": path,
            "line": line,
        }

        # If this is a reply to another comment
        if reply_to:
            comment_data["in_reply_to"] = reply_to

        cmd = [
            "api",
            f"repos/:owner/:repo/pulls/{pr_number}/comments",
            "--method",
            "POST",
            "--field",
            f"body={body}",
            "--field",
            f"commit_id={commit_id}",
            "--field",
            f"path={path}",
            "--field",
            f"line={line}",
        ]

        if reply_to:
            cmd.extend(["--field", f"in_reply_to={reply_to}"])

        cmd.extend(repo_arg)
    else:
        # Create a regular PR conversation comment
        cmd = [
            "api",
            f"repos/:owner/:repo/issues/{pr_number}/comments",
            "--method",
            "POST",
            "--field",
            f"body={body}",
        ]
        cmd.extend(repo_arg)

    result = _run_gh_command(cmd)

    if not result["success"]:
        return result["error"]

    try:
        comment = json.loads(result["data"])
        comment_id = comment.get("id")
        comment_url = comment.get("html_url")

        output = "Comment added successfully!\n\n"
        output += f"**Comment ID**: {comment_id}\n"

        if comment_url:
            output += f"**URL**: {comment_url}\n"

        return output
    except json.JSONDecodeError:
        # If we can't parse the response, assume it worked if we got a successful result
        if result["success"]:
            return "Comment added successfully!"
        return f"Error adding comment: {result['data']}"


@tool
def github_list_new_comments(
    context: "AgentContext",
    pr_number: Union[int, str],
    since: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    """List new comments on a pull request since a specific date.

    Args:
        pr_number: The pull request number
        since: ISO 8601 format date (e.g., "2023-04-01T00:00:00Z") to filter comments
        repo: Repository in format [HOST/]OWNER/REPO
    """
    # Build repo argument
    repo_arg = []
    if repo:
        repo_arg = ["--repo", repo]

    # Verify the PR exists
    pr_verify_cmd = ["pr", "view", str(pr_number), "--json", "number"] + repo_arg
    pr_result = _run_gh_command(pr_verify_cmd)

    if not pr_result["success"]:
        return pr_result["error"]

    # If no 'since' date is provided, use the last 24 hours
    since_param = ""
    if since:
        # Validate date format
        try:
            datetime.fromisoformat(since.replace("Z", "+00:00"))
            since_param = f"?since={since}"
        except ValueError:
            return "Error: 'since' must be in ISO 8601 format (e.g., '2023-04-01T00:00:00Z')"

    # Get all types of comments
    output = f"# New Comments on PR #{pr_number} "
    if since:
        output += f"since {since}\n\n"
    else:
        output += "(most recent)\n\n"

    # Track total comments found
    total_comments = 0

    # Get inline code comments
    inline_cmd = [
        "api",
        f"repos/:owner/:repo/pulls/{pr_number}/comments{since_param}",
        "--jq",
        ".",
    ] + repo_arg
    inline_result = _run_gh_command(inline_cmd)

    if inline_result["success"]:
        try:
            inline_comments = json.loads(inline_result["data"])
            total_comments += len(inline_comments)
            output += _format_markdown_comments(inline_comments, "Inline")
        except json.JSONDecodeError:
            output += "Error parsing inline comments data\n\n"

    # Get PR conversation comments
    issue_cmd = [
        "api",
        f"repos/:owner/:repo/issues/{pr_number}/comments{since_param}",
        "--jq",
        ".",
    ] + repo_arg
    issue_result = _run_gh_command(issue_cmd)

    if issue_result["success"]:
        try:
            issue_comments = json.loads(issue_result["data"])
            total_comments += len(issue_comments)
            output += _format_markdown_comments(issue_comments, "Conversation")
        except json.JSONDecodeError:
            output += "Error parsing conversation comments data\n\n"

    # Get review comments
    review_cmd = [
        "api",
        f"repos/:owner/:repo/pulls/{pr_number}/reviews{since_param}",
        "--jq",
        ".",
    ] + repo_arg
    review_result = _run_gh_command(review_cmd)

    if review_result["success"]:
        try:
            reviews = json.loads(review_result["data"])

            # Filter reviews to only include those with non-empty bodies
            review_comments = [
                {**review, "body": review.get("body", "")}
                for review in reviews
                if review.get("body") and review["body"].strip()
            ]

            total_comments += len(review_comments)
            output += _format_markdown_comments(review_comments, "Review")
        except json.JSONDecodeError:
            output += "Error parsing review comments data\n\n"

    # If no comments were found
    if total_comments == 0:
        output += "No new comments found in the specified timeframe."
    else:
        output += f"Total new comments: {total_comments}"

    return output


# List of tools to be exported
GITHUB_COMMENT_TOOLS = [
    github_list_pr_comments,
    github_get_comment,
    github_add_pr_comment,
    github_list_new_comments,
]
