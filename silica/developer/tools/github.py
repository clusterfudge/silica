import json
import subprocess
from typing import Optional, Dict, Any, List, Union

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


def _format_as_markdown(data: Dict[str, Any], title: str = "") -> str:
    """
    Format API response as markdown for better readability.

    Args:
        data: Data to format
        title: Optional title for the markdown content

    Returns:
        Formatted markdown string
    """
    md = ""
    if title:
        md += f"# {title}\n\n"

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                md += f"### {key}\n\n"
                md += f"```json\n{json.dumps(value, indent=2)}\n```\n\n"
            else:
                md += f"**{key}**: {value}\n\n"
    elif isinstance(data, list):
        md += f"```json\n{json.dumps(data, indent=2)}\n```\n\n"
    else:
        md += f"{data}\n\n"

    return md


@tool
def github_list_prs(
    context: "AgentContext",
    state: Optional[str] = None,
    base: Optional[str] = None,
    limit: Optional[int] = 10,
    repo: Optional[str] = None,
) -> str:
    """List pull requests in a GitHub repository.

    Args:
        state: State of PRs to list (open, closed, merged, all)
        base: Filter by base branch name
        limit: Maximum number of PRs to list
        repo: Repository in format [HOST/]OWNER/REPO (current repo used if not specified)
    """
    cmd = [
        "pr",
        "list",
        "--json",
        "number,title,author,createdAt,updatedAt,state,reviewDecision,url",
    ]

    if state:
        cmd.extend(["--state", state])

    if base:
        cmd.extend(["--base", base])

    if limit and limit > 0:
        cmd.extend(["--limit", str(limit)])

    if repo:
        cmd.extend(["--repo", repo])

    result = _run_gh_command(cmd)

    if not result["success"]:
        return result["error"]

    try:
        prs = json.loads(result["data"])
        if not prs:
            return "No pull requests found."

        output = "## Pull Requests\n\n"
        for pr in prs:
            output += f"- **#{pr['number']}**: [{pr['title']}]({pr['url']}) by {pr['author']['login']}\n"
            output += f"  - Created: {pr['createdAt']}, Updated: {pr['updatedAt']}\n"
            output += f"  - State: {pr['state']}, Review: {pr.get('reviewDecision', 'None')}\n\n"

        return output
    except json.JSONDecodeError:
        return f"Error parsing JSON response:\n{result['data']}"


@tool
def github_view_pr(
    context: "AgentContext",
    number: str,
    comments: bool = True,
    repo: Optional[str] = None,
) -> str:
    """View details of a pull request including its comments.

    Args:
        number: PR number or URL
        comments: Whether to include comments
        repo: Repository in format [HOST/]OWNER/REPO (current repo used if not specified)
    """
    cmd = [
        "pr",
        "view",
        number,
        "--json",
        "number,title,author,body,state,createdAt,updatedAt,url,baseRefName,headRefName,files,reviews",
    ]

    if repo:
        cmd.extend(["--repo", repo])

    result = _run_gh_command(cmd)

    if not result["success"]:
        return result["error"]

    try:
        pr = json.loads(result["data"])

        output = f"# Pull Request #{pr['number']}: {pr['title']}\n\n"
        output += f"**Author**: {pr['author']['login']}\n"
        output += f"**State**: {pr['state']}\n"
        output += f"**Created**: {pr['createdAt']}\n"
        output += f"**Updated**: {pr['updatedAt']}\n"
        output += f"**URL**: {pr['url']}\n"
        output += f"**Base branch**: {pr['baseRefName']}\n"
        output += f"**Head branch**: {pr['headRefName']}\n\n"

        output += f"## Description\n\n{pr['body']}\n\n"

        if comments:
            # Get comments including review comments and file-specific comments
            pr_comments_result = _run_gh_command(
                [
                    "api",
                    f"repos/:owner/:repo/pulls/{pr['number']}/comments",
                    "--jq",
                    ".",
                ]
            )

            issue_comments_result = _run_gh_command(
                [
                    "api",
                    f"repos/:owner/:repo/issues/{pr['number']}/comments",
                    "--jq",
                    ".",
                ]
            )

            output += "## Review Comments\n\n"

            # Process PR reviews
            if pr.get("reviews") and len(pr["reviews"]) > 0:
                for review in pr["reviews"]:
                    if review.get("body"):
                        output += f"### Review by {review['author']['login']} on {review['submittedAt']}\n\n"
                        output += f"**State**: {review['state']}\n\n"
                        output += f"{review['body']}\n\n"

            # Process inline PR comments
            if pr_comments_result["success"]:
                try:
                    inline_comments = json.loads(pr_comments_result["data"])
                    if inline_comments and len(inline_comments) > 0:
                        output += "### Inline Comments\n\n"
                        for comment in inline_comments:
                            output += f"**{comment['user']['login']}** on {comment['path']} at line {comment.get('line', comment.get('original_line', 'N/A'))}:\n\n"
                            output += f"{comment['body']}\n\n"
                            if comment.get("in_reply_to_id"):
                                output += "(Reply to a previous comment)\n\n"
                except json.JSONDecodeError:
                    output += "Error parsing inline comments data\n\n"

            # Process issue comments
            if issue_comments_result["success"]:
                try:
                    issues_comments = json.loads(issue_comments_result["data"])
                    if issues_comments and len(issues_comments) > 0:
                        output += "### Issue Comments\n\n"
                        for comment in issues_comments:
                            output += f"**{comment['user']['login']}** on {comment['created_at']}:\n\n"
                            output += f"{comment['body']}\n\n"
                except json.JSONDecodeError:
                    output += "Error parsing issue comments data\n\n"

        # Show changed files
        if pr.get("files") and len(pr["files"]) > 0:
            output += "## Changed Files\n\n"
            for file in pr["files"]:
                output += f"- {file['path']} (changes: +{file.get('additions', 0)}/-{file.get('deletions', 0)})\n"

        return output
    except json.JSONDecodeError:
        return f"Error parsing JSON response:\n{result['data']}"


@tool
def github_list_issues(
    context: "AgentContext",
    state: Optional[str] = None,
    label: Optional[str] = None,
    limit: Optional[int] = 10,
    repo: Optional[str] = None,
) -> str:
    """List issues in a GitHub repository.

    Args:
        state: State of issues to list (open, closed, all)
        label: Filter by label
        limit: Maximum number of issues to list
        repo: Repository in format [HOST/]OWNER/REPO (current repo used if not specified)
    """
    cmd = [
        "issue",
        "list",
        "--json",
        "number,title,author,createdAt,updatedAt,state,labels,url",
    ]

    if state:
        cmd.extend(["--state", state])

    if label:
        cmd.extend(["--label", label])

    if limit and limit > 0:
        cmd.extend(["--limit", str(limit)])

    if repo:
        cmd.extend(["--repo", repo])

    result = _run_gh_command(cmd)

    if not result["success"]:
        return result["error"]

    try:
        issues = json.loads(result["data"])
        if not issues:
            return "No issues found."

        output = "## Issues\n\n"
        for issue in issues:
            output += f"- **#{issue['number']}**: [{issue['title']}]({issue['url']}) by {issue['author']['login']}\n"
            output += (
                f"  - Created: {issue['createdAt']}, Updated: {issue['updatedAt']}\n"
            )
            output += f"  - State: {issue['state']}\n"

            if issue.get("labels") and len(issue["labels"]) > 0:
                labels = [label["name"] for label in issue["labels"]]
                output += f"  - Labels: {', '.join(labels)}\n"

            output += "\n"

        return output
    except json.JSONDecodeError:
        return f"Error parsing JSON response:\n{result['data']}"


@tool
def github_view_issue(
    context: "AgentContext",
    number: str,
    comments: bool = True,
    repo: Optional[str] = None,
) -> str:
    """View details of a GitHub issue including its comments.

    Args:
        number: Issue number or URL
        comments: Whether to include comments
        repo: Repository in format [HOST/]OWNER/REPO (current repo used if not specified)
    """
    cmd = [
        "issue",
        "view",
        number,
        "--json",
        "number,title,author,body,state,createdAt,updatedAt,url,labels,assignees",
    ]

    if repo:
        cmd.extend(["--repo", repo])

    result = _run_gh_command(cmd)

    if not result["success"]:
        return result["error"]

    try:
        issue = json.loads(result["data"])

        output = f"# Issue #{issue['number']}: {issue['title']}\n\n"
        output += f"**Author**: {issue['author']['login']}\n"
        output += f"**State**: {issue['state']}\n"
        output += f"**Created**: {issue['createdAt']}\n"
        output += f"**Updated**: {issue['updatedAt']}\n"
        output += f"**URL**: {issue['url']}\n\n"

        if issue.get("labels") and len(issue["labels"]) > 0:
            labels = [label["name"] for label in issue["labels"]]
            output += f"**Labels**: {', '.join(labels)}\n\n"

        if issue.get("assignees") and len(issue["assignees"]) > 0:
            assignees = [assignee["login"] for assignee in issue["assignees"]]
            output += f"**Assignees**: {', '.join(assignees)}\n\n"

        output += f"## Description\n\n{issue['body']}\n\n"

        if comments:
            comments_result = _run_gh_command(
                [
                    "api",
                    f"repos/:owner/:repo/issues/{issue['number']}/comments",
                    "--jq",
                    ".",
                ]
            )

            if comments_result["success"]:
                try:
                    issue_comments = json.loads(comments_result["data"])
                    if issue_comments and len(issue_comments) > 0:
                        output += "## Comments\n\n"
                        for comment in issue_comments:
                            output += f"### {comment['user']['login']} on {comment['created_at']}\n\n"
                            output += f"{comment['body']}\n\n"
                except json.JSONDecodeError:
                    output += "Error parsing comments data\n\n"

        return output
    except json.JSONDecodeError:
        return f"Error parsing JSON response:\n{result['data']}"


@tool
def github_api(
    context: "AgentContext",
    endpoint: str,
    method: Optional[str] = None,
    fields: Optional[Union[Dict[str, Any], str]] = None,
    jq_filter: Optional[str] = None,
    repo: Optional[str] = None,
) -> str:
    """Make a generic GitHub API request.

    Args:
        endpoint: GitHub API endpoint (e.g., 'repos/{owner}/{repo}/issues')
        method: HTTP method (GET, POST, PATCH, DELETE, etc.)
        fields: Dictionary of field values to include in the request (can be a JSON string or dict)
        jq_filter: JQ expression to filter the response
        repo: Repository in format [HOST/]OWNER/REPO to replace {owner}/{repo} in endpoint
    """
    cmd = ["api"]

    # Process the endpoint
    if endpoint.startswith("/"):
        endpoint = endpoint[1:]
    cmd.append(endpoint)

    # Add method if specified
    if method:
        cmd.extend(["--method", method])

    # Add repository if specified
    if repo:
        cmd.extend(["--repo", repo])

    # Add JQ filter if specified
    if jq_filter:
        cmd.extend(["--jq", jq_filter])

    # Process fields parameter - handle both dict and string inputs
    if fields:
        # Convert fields to dictionary if it's a string (attempt JSON parsing)
        fields_dict = None
        if isinstance(fields, dict):
            fields_dict = fields
        elif isinstance(fields, str):
            try:
                fields_dict = json.loads(fields)
                if not isinstance(fields_dict, dict):
                    return "Error: 'fields' must be a dictionary or a JSON string representing a dictionary"
            except json.JSONDecodeError:
                return "Error: Unable to parse 'fields' as JSON. Please provide a valid JSON string or dictionary."
        else:
            return f"Error: 'fields' must be a dictionary or JSON string, not {type(fields).__name__}"

        # Add each field to the command
        for key, value in fields_dict.items():
            if isinstance(value, (dict, list)):
                val_str = json.dumps(value)
            else:
                val_str = str(value)
            cmd.extend(["--field", f"{key}={val_str}"])

    result = _run_gh_command(cmd)

    if not result["success"]:
        return result["error"]

    # Try to parse as JSON for better formatting
    try:
        data = json.loads(result["data"])
        return _format_as_markdown(data, title=f"GitHub API: {endpoint}")
    except json.JSONDecodeError:
        # If not valid JSON, return as is
        return result["data"]


# GitHub Pull Request Comments (Specific functionality)
@tool
def github_pr_comments(
    context: "AgentContext",
    number: str,
    repo: Optional[str] = None,
) -> str:
    """Get all comments on a pull request, including inline code comments.

    Args:
        number: PR number or URL
        repo: Repository in format [HOST/]OWNER/REPO (current repo used if not specified)
    """
    # Build the base command
    repo_arg = []
    if repo:
        repo_arg = ["--repo", repo]

    # Get PR details first to ensure it exists
    cmd = ["pr", "view", number, "--json", "number,url"] + repo_arg
    pr_result = _run_gh_command(cmd)

    if not pr_result["success"]:
        return pr_result["error"]

    try:
        pr = json.loads(pr_result["data"])
        pr_number = pr["number"]

        # Get comments from three sources:
        # 1. PR review comments (inline code comments)
        inline_cmd = [
            "api",
            f"repos/:owner/:repo/pulls/{pr_number}/comments",
            "--jq",
            ".",
        ] + repo_arg
        inline_result = _run_gh_command(inline_cmd)

        # 2. Issue comments (top-level PR comments)
        issue_cmd = [
            "api",
            f"repos/:owner/:repo/issues/{pr_number}/comments",
            "--jq",
            ".",
        ] + repo_arg
        issue_result = _run_gh_command(issue_cmd)

        # 3. PR reviews (overall review comments)
        reviews_cmd = [
            "api",
            f"repos/:owner/:repo/pulls/{pr_number}/reviews",
            "--jq",
            ".",
        ] + repo_arg
        reviews_result = _run_gh_command(reviews_cmd)

        output = f"# Comments on PR #{pr_number}\n\n"

        # Process inline comments
        if inline_result["success"]:
            try:
                inline_comments = json.loads(inline_result["data"])
                if inline_comments and len(inline_comments) > 0:
                    output += "## Inline Code Comments\n\n"

                    # Group comments by file path
                    file_comments = {}
                    for comment in inline_comments:
                        path = comment.get("path", "Unknown file")
                        if path not in file_comments:
                            file_comments[path] = []
                        file_comments[path].append(comment)

                    # Display comments by file
                    for file_path, comments in file_comments.items():
                        output += f"### {file_path}\n\n"
                        for comment in comments:
                            location = f"line {comment.get('line', comment.get('original_line', 'N/A'))}"
                            output += f"**{comment['user']['login']}** on {comment['created_at']} at {location}:\n\n"
                            output += f"{comment['body']}\n\n"

                            # Show whether it's a reply
                            if comment.get("in_reply_to_id"):
                                output += "(Reply to a previous comment)\n\n"
            except json.JSONDecodeError:
                output += "Error parsing inline comments data\n\n"

        # Process issue comments
        if issue_result["success"]:
            try:
                issue_comments = json.loads(issue_result["data"])
                if issue_comments and len(issue_comments) > 0:
                    output += "## PR Conversation Comments\n\n"
                    for comment in issue_comments:
                        output += f"### {comment['user']['login']} on {comment['created_at']}\n\n"
                        output += f"{comment['body']}\n\n"
            except json.JSONDecodeError:
                output += "Error parsing PR conversation comments data\n\n"

        # Process review comments
        if reviews_result["success"]:
            try:
                reviews = json.loads(reviews_result["data"])
                if reviews and len(reviews) > 0:
                    output += "## PR Reviews\n\n"
                    for review in reviews:
                        if review.get("body") and review["body"].strip():
                            output += f"### {review['user']['login']} on {review['submitted_at']} - {review['state']}\n\n"
                            output += f"{review['body']}\n\n"
            except json.JSONDecodeError:
                output += "Error parsing PR reviews data\n\n"

        # If no comments found
        if "##" not in output:
            output += "No comments found on this PR."

        return output

    except json.JSONDecodeError:
        return f"Error parsing PR data:\n{pr_result['data']}"


# GitHub Actions
@tool
def github_workflow_runs(
    context: "AgentContext",
    workflow: Optional[str] = None,
    branch: Optional[str] = None,
    status: Optional[str] = None,
    limit: Optional[int] = 5,
    repo: Optional[str] = None,
) -> str:
    """List GitHub workflow runs.

    Args:
        workflow: Filter by workflow name or ID
        branch: Filter by branch name
        status: Filter by status (e.g., completed, success, failure)
        limit: Maximum number of runs to list
        repo: Repository in format [HOST/]OWNER/REPO (current repo used if not specified)
    """
    cmd = ["api", "repos/:owner/:repo/actions/runs"]
    query_params = []

    if workflow:
        query_params.append(f"workflow_id={workflow}")

    if branch:
        query_params.append(f"branch={branch}")

    if status:
        query_params.append(f"status={status}")

    if limit and limit > 0:
        query_params.append(f"per_page={limit}")

    if query_params:
        cmd.append("?" + "&".join(query_params))

    if repo:
        cmd.extend(["--repo", repo])

    result = _run_gh_command(cmd)

    if not result["success"]:
        return result["error"]

    try:
        data = json.loads(result["data"])

        if not data.get("workflow_runs") or len(data["workflow_runs"]) == 0:
            return "No workflow runs found matching the criteria."

        output = "# GitHub Actions Workflow Runs\n\n"

        for run in data["workflow_runs"]:
            output += f"## {run['name']} (#{run['run_number']})\n\n"
            output += f"**Status**: {run['status']} - {run.get('conclusion', 'N/A')}\n"
            output += f"**Branch**: {run['head_branch']}\n"
            output += f"**Commit**: {run['head_sha'][:7]}\n"
            output += f"**Started**: {run['created_at']}\n"
            output += f"**URL**: {run['html_url']}\n\n"

        return output
    except json.JSONDecodeError:
        return f"Error parsing JSON response:\n{result['data']}"


GITHUB_TOOLS = [
    github_list_prs,
    github_view_pr,
    github_list_issues,
    github_view_issue,
    github_api,
    github_pr_comments,
    github_workflow_runs,
]
