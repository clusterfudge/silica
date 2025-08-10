"""Tests for GitHub comment tools module.

This module contains unit tests for the GitHub comment interaction tools.
We use mocking to test the interaction with the GitHub CLI.
"""

import json
import unittest
from unittest.mock import patch, MagicMock

from silica.developer.context import AgentContext
from silica.developer.tools.github_comments import (
    _run_gh_command,
    _format_markdown_comments,
    github_list_pr_comments,
    github_get_comment,
    github_add_pr_comment,
    github_list_new_comments,
)


class MockContext(AgentContext):
    """Mock AgentContext for testing."""

    def __init__(self):
        pass


class TestGitHubCommentUtils(unittest.TestCase):
    """Test GitHub comment utility functions."""

    @patch("subprocess.run")
    def test_run_gh_command_success(self, mock_run):
        """Test _run_gh_command when command succeeds."""
        # Set up the mock
        mock_process = MagicMock()
        mock_process.stdout = "success output"
        mock_process.returncode = 0
        mock_run.return_value = mock_process

        # Call the function
        result = _run_gh_command(["test", "command"])

        # Verify the results
        mock_run.assert_called_once_with(
            ["gh", "test", "command"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["data"], "success output")

    @patch("subprocess.run")
    def test_run_gh_command_failure(self, mock_run):
        """Test _run_gh_command when command fails."""
        # Set up the mock to raise an exception
        from subprocess import CalledProcessError

        # Create a CalledProcessError and set stdout/stderr attributes directly
        error = CalledProcessError(1, ["gh", "test"])
        error.stdout = "error output"
        error.stderr = "error message"
        mock_run.side_effect = error

        # Call the function
        result = _run_gh_command(["test"])

        # Verify the results
        self.assertFalse(result["success"])
        self.assertEqual(result["data"], "error output")
        self.assertIn("error message", result["error"])

    def test_format_markdown_comments(self):
        """Test the _format_markdown_comments helper function."""
        # Sample comment data
        comments = [
            {
                "user": {"login": "user1"},
                "created_at": "2023-04-01T12:34:56Z",
                "body": "This is a test comment",
                "path": "test.py",
                "line": 10,
            },
            {
                "user": {"login": "user2"},
                "created_at": "2023-04-02T12:34:56Z",
                "body": "This is a reply",
                "path": "test.py",
                "line": 20,
                "in_reply_to_id": 123456,
            },
        ]

        # Format as inline comments
        markdown = _format_markdown_comments(comments, "Inline", show_details=True)

        # Check the results
        self.assertIn("## Inline Comments (2)", markdown)
        self.assertIn("### user1 on", markdown)
        self.assertIn("### user2 on", markdown)
        self.assertIn("**File:** test.py, Line: 10", markdown)
        self.assertIn("This is a test comment", markdown)
        self.assertIn("(Reply to an earlier comment)", markdown)

        # Test without details
        markdown = _format_markdown_comments(comments, "Inline", show_details=False)
        self.assertNotIn("**File:**", markdown)
        self.assertNotIn("(Reply to an earlier comment)", markdown)

        # Test with empty comments
        empty_markdown = _format_markdown_comments([], "Inline")
        self.assertEqual(empty_markdown, "")


class TestGitHubCommentTools(unittest.TestCase):
    """Test GitHub comment tools that interact with the API."""

    def setUp(self):
        """Set up test fixtures."""
        self.context = MockContext()
        self.pr_number = 123

        # Create a patch for _run_gh_command
        self.run_cmd_patcher = patch(
            "silica.developer.tools.github_comments._run_gh_command"
        )
        self.mock_run_cmd = self.run_cmd_patcher.start()

        # Default response for PR verification
        self.mock_run_cmd.return_value = {
            "success": True,
            "data": json.dumps({"number": self.pr_number, "headRefOid": "abc123"}),
        }

    def tearDown(self):
        """Tear down test fixtures."""
        self.run_cmd_patcher.stop()

    def test_github_list_pr_comments_all(self):
        """Test listing all types of PR comments."""

        # Set up mocks for different comment types
        def mock_command_side_effect(args):
            if "pulls/123/comments" in str(args):
                return {
                    "success": True,
                    "data": json.dumps(
                        [{"user": {"login": "user1"}, "body": "inline comment"}]
                    ),
                }
            elif "issues/123/comments" in str(args):
                return {
                    "success": True,
                    "data": json.dumps(
                        [{"user": {"login": "user2"}, "body": "conversation comment"}]
                    ),
                }
            elif "pulls/123/reviews" in str(args):
                return {
                    "success": True,
                    "data": json.dumps(
                        [{"user": {"login": "user3"}, "body": "review comment"}]
                    ),
                }
            return {"success": True, "data": json.dumps({"number": 123})}

        self.mock_run_cmd.side_effect = mock_command_side_effect

        # Call the function
        result = github_list_pr_comments(self.context, self.pr_number)

        # Verify the result contains all comment types
        self.assertIn("# Comments for Pull Request #123", result)
        self.assertIn("inline comment", result)
        self.assertIn("conversation comment", result)
        self.assertIn("review comment", result)
        self.assertIn("Total comments: 3", result)

    def test_github_list_pr_comments_filtered(self):
        """Test listing only inline comments."""

        # Set up mocks for inline comments only
        def mock_command_side_effect(args):
            if "pulls/123/comments" in str(args):
                return {
                    "success": True,
                    "data": json.dumps(
                        [{"user": {"login": "user1"}, "body": "inline comment"}]
                    ),
                }
            return {"success": True, "data": json.dumps({"number": 123})}

        self.mock_run_cmd.side_effect = mock_command_side_effect

        # Call the function with type=inline
        result = github_list_pr_comments(self.context, self.pr_number, type="inline")

        # Verify only inline comments are included
        self.assertIn("inline comment", result)
        self.assertNotIn("## Conversation Comments", result)
        self.assertNotIn("## Review Comments", result)

    def test_github_list_pr_comments_no_comments(self):
        """Test listing PR comments when there are none."""

        # Mock empty responses
        def mock_command_side_effect(args):
            if any(x in str(args) for x in ["comments", "reviews"]):
                return {"success": True, "data": json.dumps([])}
            return {"success": True, "data": json.dumps({"number": 123})}

        self.mock_run_cmd.side_effect = mock_command_side_effect

        # Call the function
        result = github_list_pr_comments(self.context, self.pr_number)

        # Verify the message when no comments found
        self.assertIn("No comments found on this pull request", result)

    def test_github_get_comment(self):
        """Test getting a specific PR comment."""
        # Mock comment data
        comment_data = {
            "id": 456,
            "user": {"login": "testuser"},
            "created_at": "2023-04-01T12:34:56Z",
            "updated_at": "2023-04-01T12:45:00Z",
            "body": "Test comment body",
            "path": "file.py",
            "line": 42,
            "html_url": "https://github.com/test/repo/pull/123#comment-456",
        }

        self.mock_run_cmd.return_value = {
            "success": True,
            "data": json.dumps(comment_data),
        }

        # Call the function
        result = github_get_comment(self.context, "456", comment_type="pr")

        # Verify the result
        self.assertIn("# Pull Request Comment (ID: 456)", result)
        self.assertIn("**Author**: testuser", result)
        self.assertIn("**File**: file.py", result)
        self.assertIn("**Line**: 42", result)
        self.assertIn("Test comment body", result)

    def test_github_add_pr_comment_conversation(self):
        """Test adding a conversation comment to a PR."""
        # Mock successful comment creation
        comment_data = {
            "id": 456,
            "html_url": "https://github.com/test/repo/pull/123#issuecomment-456",
        }

        self.mock_run_cmd.return_value = {
            "success": True,
            "data": json.dumps(comment_data),
        }

        # Call the function to add a regular PR comment
        result = github_add_pr_comment(
            self.context, self.pr_number, body="This is a test comment"
        )

        # Verify the result
        self.assertIn("Comment added successfully", result)
        self.assertIn("456", result)  # Comment ID

        # Verify the correct API was called
        args = self.mock_run_cmd.call_args[0][0]
        self.assertIn("issues/123/comments", str(args))

    def test_github_add_pr_comment_inline(self):
        """Test adding an inline comment to a PR."""
        # Mock successful comment creation
        comment_data = {
            "id": 789,
            "html_url": "https://github.com/test/repo/pull/123#discussion_r789",
        }

        self.mock_run_cmd.return_value = {
            "success": True,
            "data": json.dumps(comment_data),
        }

        # Call the function to add an inline comment
        result = github_add_pr_comment(
            self.context,
            self.pr_number,
            body="This is an inline comment",
            path="file.py",
            line=42,
            commit_id="abc123",
        )

        # Verify the result
        self.assertIn("Comment added successfully", result)
        self.assertIn("789", result)  # Comment ID

        # Verify the correct API was called
        args = self.mock_run_cmd.call_args[0][0]
        self.assertIn("pulls/123/comments", str(args))
        self.assertIn("line=42", str(args))

    def test_github_list_new_comments(self):
        """Test listing new comments since a specific date."""
        # Mock responses for different comment types
        since_date = "2023-04-01T00:00:00Z"

        def mock_command_side_effect(args):
            if "pulls/123/comments?since=" in str(args):
                return {
                    "success": True,
                    "data": json.dumps(
                        [
                            {
                                "user": {"login": "user1"},
                                "created_at": "2023-04-02T12:34:56Z",
                                "body": "new inline comment",
                            }
                        ]
                    ),
                }
            elif "issues/123/comments?since=" in str(args):
                return {
                    "success": True,
                    "data": json.dumps([]),
                }  # No new conversation comments
            elif "pulls/123/reviews?since=" in str(args):
                return {"success": True, "data": json.dumps([])}  # No new reviews
            return {"success": True, "data": json.dumps({"number": 123})}

        self.mock_run_cmd.side_effect = mock_command_side_effect

        # Call the function
        result = github_list_new_comments(
            self.context, self.pr_number, since=since_date
        )

        # Verify the result
        self.assertIn(
            f"# New Comments on PR #{self.pr_number} since {since_date}", result
        )
        self.assertIn("new inline comment", result)
        self.assertIn("Total new comments: 1", result)

        # Test with invalid date format
        result = github_list_new_comments(
            self.context, self.pr_number, since="invalid-date"
        )
        self.assertIn("Error: 'since' must be in ISO 8601 format", result)


if __name__ == "__main__":
    unittest.main()
