#!/usr/bin/env python3
"""Tests for CLI argument preservation in session management."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode
from silica.developer.tools.sessions import (
    _reconstruct_command_from_list,
    get_session_data,
)


class TestSessionCliArgs(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for test files
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_dir = Path(self.temp_dir.name)

    def tearDown(self):
        # Clean up the temporary directory
        self.temp_dir.cleanup()

    def test_cli_args_stored_in_context(self):
        """Test that CLI arguments are properly stored in AgentContext."""
        # Mock dependencies
        mock_sandbox = MagicMock()
        mock_ui = MagicMock()
        mock_memory = MagicMock()

        # Test CLI arguments
        test_cli_args = [
            "hdev",
            "--model",
            "sonnet",
            "--dwr",
            "--persona",
            "coding-agent",
        ]

        # Create context with CLI args
        context = AgentContext(
            session_id="test-session",
            parent_session_id=None,
            model_spec={
                "title": "sonnet",
                "pricing": {"input": 1, "output": 1},
                "cache_pricing": {"read": 0, "write": 0},
                "max_tokens": 1000,
                "context_window": 100000,
            },
            sandbox=mock_sandbox,
            user_interface=mock_ui,
            usage=[],
            memory_manager=mock_memory,
            cli_args=test_cli_args,
        )

        # Verify CLI args are stored
        self.assertEqual(context.cli_args, test_cli_args)

    def test_cli_args_preserved_in_flush(self):
        """Test that CLI arguments are saved in session metadata during flush."""
        # Mock dependencies
        mock_sandbox = MagicMock()
        mock_ui = MagicMock()
        mock_memory = MagicMock()

        # Test CLI arguments
        test_cli_args = [
            "hdev",
            "--model",
            "sonnet",
            "--dwr",
            "--persona",
            "coding-agent",
        ]

        # Create context with CLI args
        context = AgentContext(
            session_id="test-session",
            parent_session_id=None,
            model_spec={
                "title": "sonnet",
                "pricing": {"input": 1, "output": 1},
                "cache_pricing": {"read": 0, "write": 0},
                "max_tokens": 1000,
                "context_window": 100000,
            },
            sandbox=mock_sandbox,
            user_interface=mock_ui,
            usage=[],
            memory_manager=mock_memory,
            cli_args=test_cli_args,
        )

        # Add some chat history
        test_history = [{"role": "user", "content": "Hello"}]
        context._chat_history = test_history

        # Mock the flush to use our temp directory
        with patch("silica.developer.context.Path.home") as mock_home:
            mock_home.return_value = Path(self.temp_dir.name)

            # Flush the context
            context.flush(test_history)

            # Check that the file was created with CLI args
            session_file = (
                self.history_dir / ".hdev" / "history" / "test-session" / "root.json"
            )
            self.assertTrue(session_file.exists())

            # Read and verify the content
            with open(session_file, "r") as f:
                session_data = json.load(f)

            # Verify CLI args are in metadata
            self.assertIn("cli_args", session_data["metadata"])
            self.assertEqual(session_data["metadata"]["cli_args"], test_cli_args)

    def test_reconstruct_command_from_list(self):
        """Test that CLI commands are properly reconstructed from stored arguments."""
        # Test basic command reconstruction
        original_args = ["hdev", "--model", "sonnet", "--dwr"]
        reconstructed = _reconstruct_command_from_list(original_args)
        expected = ["hdev", "--model", "sonnet", "--dwr"]
        self.assertEqual(reconstructed, expected)

        # Test filtering out session-specific arguments
        original_args = [
            "hdev",
            "--model",
            "sonnet",
            "--session-id",
            "abc123",
            "--prompt",
            "Hello",
        ]
        reconstructed = _reconstruct_command_from_list(original_args)
        expected = ["hdev", "--model", "sonnet"]
        self.assertEqual(reconstructed, expected)

        # Test with persona and sandbox mode
        original_args = [
            "hdev",
            "--model",
            "sonnet",
            "--persona",
            "coding-agent",
            "--sandbox-mode",
            "allow_all",
        ]
        reconstructed = _reconstruct_command_from_list(original_args)
        expected = [
            "hdev",
            "--model",
            "sonnet",
            "--persona",
            "coding-agent",
            "--sandbox-mode",
            "allow_all",
        ]
        self.assertEqual(reconstructed, expected)

        # Test with positional arguments
        original_args = ["hdev", "--model", "sonnet", "path1", "path2"]
        reconstructed = _reconstruct_command_from_list(original_args)
        expected = ["hdev", "--model", "sonnet", "path1", "path2"]
        self.assertEqual(reconstructed, expected)

    def test_agent_context_create_with_cli_args(self):
        """Test that AgentContext.create properly handles CLI arguments."""
        # Mock dependencies
        mock_ui = MagicMock()

        test_cli_args = [
            "hdev",
            "--model",
            "sonnet",
            "--dwr",
            "--persona",
            "coding-agent",
        ]
        test_model_spec = {
            "title": "sonnet",
            "pricing": {"input": 1, "output": 1},
            "cache_pricing": {"read": 0, "write": 0},
            "max_tokens": 1000,
            "context_window": 100000,
        }

        # Create context using the static method
        context = AgentContext.create(
            model_spec=test_model_spec,
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=mock_ui,
            cli_args=test_cli_args,
        )

        # Verify CLI args are stored
        self.assertEqual(context.cli_args, test_cli_args)

    @patch("silica.developer.tools.sessions.get_history_dir")
    def test_session_data_includes_cli_args(self, mock_get_history_dir):
        """Test that session data properly includes CLI args when loaded."""
        # Setup
        mock_get_history_dir.return_value = self.history_dir

        # Create session directory and data with CLI args
        session_id = "test-session"
        session_dir = self.history_dir / session_id
        session_dir.mkdir(parents=True)

        test_cli_args = [
            "hdev",
            "--model",
            "sonnet",
            "--dwr",
            "--persona",
            "coding-agent",
        ]

        root_file = session_dir / "root.json"
        with open(root_file, "w") as f:
            json.dump(
                {
                    "session_id": session_id,
                    "model_spec": {"title": "sonnet"},
                    "messages": [{"role": "user", "content": "Hello"}],
                    "metadata": {
                        "created_at": "2025-05-01T12:00:00Z",
                        "last_updated": "2025-05-01T12:30:00Z",
                        "root_dir": "/path/to/project",
                        "cli_args": test_cli_args,
                    },
                },
                f,
            )

        # Load session data
        session_data = get_session_data(session_id)

        # Verify CLI args are included
        self.assertIsNotNone(session_data)
        self.assertIn("metadata", session_data)
        self.assertIn("cli_args", session_data["metadata"])
        self.assertEqual(session_data["metadata"]["cli_args"], test_cli_args)


if __name__ == "__main__":
    unittest.main()
