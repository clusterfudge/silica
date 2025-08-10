import subprocess
import os
import shutil
from anthropic import Anthropic


def get_git_diff():
    try:
        # This command captures all changes, including new files
        return subprocess.check_output(
            ["git", "diff", "--staged", "--no-color"]
        ).decode("utf-8")
    except subprocess.CalledProcessError:
        return "Error: Unable to get git diff. Are you in a git repository?"


def generate_commit_message(diff):
    anthropic = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    system_message = """You are a helpful assistant that generates commit messages based on git diffs. 
    # Commit and PR Tagging System

This document outlines a simple tagging system for commit messages and pull requests. Tags should be placed in square brackets at the beginning of the title.

## Primary Tags (Change Type)

| Tag | Description |
|-----|-------------|
| `[FIX]` | Bug fixes |
| `[FEAT]` | New features |
| `[REFACTOR]` | Code restructuring without changing functionality |
| `[DOCS]` | Documentation updates |
| `[TEST]` | Adding or modifying tests |
| `[STYLE]` | Formatting, white-space, styling changes |
| `[PERF]` | Performance improvements |
| `[CHORE]` | Build process, dependency updates, config changes |

## Secondary Tags (Optional)

These can be combined with primary tags as needed:

| Tag | Description |
|-----|-------------|
| `[WIP]` | Work in progress |
| `[BREAKING]` | Breaking changes that require attention |
| `[HOTFIX]` | Urgent fixes for production issues |
| `[SECURITY]` | Security-related changes |

## Examples

```
[FEAT] Add user authentication
[FIX][SECURITY] Patch SQL injection vulnerability 
[REFACTOR][PERF] Optimize database queries
[DOCS] Update API documentation
[TEST] Add unit tests for payment processor
[CHORE] Update dependencies to latest versions
[STYLE] Fix indentation in controller files
[WIP][FEAT] Implement shopping cart functionality
[BREAKING][REFACTOR] Redesign public API endpoints
```

## Usage Guidelines

- Always use a primary tag
- Add secondary tags when applicable
- Keep the remainder of the title concise but descriptive
- Use present tense, imperative mood for consistency (e.g., "Add" not "Added")
- If multiple primary tags apply, choose the most significant one

    
    Please use the following template for the commit message:

    ```
    [TAG] A brief, one-line summary of the changes

    Detailed Changes:
    - [List the main changes, one per line]

    Impact: [Briefly describe the potential impact of these changes]

    Additional Notes: [Any other relevant information, if necessary]
    
    Related Issues: [for each related issue slug, include a link [<slug>](https://go/issues/<slug>) ]
    ```
    """

    user_message = f"Here's the git diff:\n\n{diff}\n\nPlease generate a commit message based on this diff."

    try:
        response = anthropic.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=500,
            temperature=0.7,
            system=system_message,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        return f"Error: Unable to generate commit message. {str(e)}"


def commit_changes(message):
    try:
        subprocess.run(["git", "commit", "-m", message], check=True)
        return "Changes committed successfully."
    except subprocess.CalledProcessError:
        return (
            "Error: Unable to commit changes. Make sure you have staged your changes."
        )


def run_pre_commit_hooks():
    # Check if pre-commit is available in PATH
    if not shutil.which("pre-commit"):
        return None  # pre-commit is not installed

    try:
        subprocess.run(["pre-commit", "run", "--all-files"], check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def run_commit():
    diff = get_git_diff()
    if diff.startswith("Error"):
        return diff

    if not diff:
        return "Error: No changes staged for commit. Please stage your changes first."

    pre_commit_result = run_pre_commit_hooks()
    if pre_commit_result is False:
        return "Error: Pre-commit hooks failed. Please fix the issues and try again."
    elif pre_commit_result is True:
        print("Pre-commit hooks ran successfully.")
    elif pre_commit_result is None:
        print("Note: pre-commit is not installed. Skipping pre-commit hooks.")

    commit_message = generate_commit_message(diff)
    if commit_message.startswith("Error"):
        return commit_message

    result = commit_changes(commit_message)
    return f"{result}\n\nCommit message:\n{commit_message}"


if __name__ == "__main__":
    print(run_commit())
