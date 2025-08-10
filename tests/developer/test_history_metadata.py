import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from silica.developer.context import AgentContext
from silica.developer.sandbox import SandboxMode
from silica.developer.user_interface import UserInterface


class TestHistoryMetadata(unittest.TestCase):
    def setUp(self):
        # Create a temporary directory for history files
        self.temp_dir = tempfile.TemporaryDirectory()
        self.history_dir = Path(self.temp_dir.name)

        # Create model_spec
        self.model_spec = {
            "title": "test-model",
            "pricing": {"input": 1.0, "output": 1.0},
            "cache_pricing": {"write": 1.0, "read": 0.1},
            "max_tokens": 1000,
            "context_window": 2000,
        }

        # Create a mock user interface
        self.user_interface = MagicMock(spec=UserInterface)
        self.user_interface.permission_callback = MagicMock(return_value=True)
        self.user_interface.permission_rendering_callback = MagicMock(return_value=True)

        # Create agent context
        self.agent_context = AgentContext.create(
            model_spec=self.model_spec,
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[os.getcwd()],
            user_interface=self.user_interface,
        )

        # Mock chat history
        self.chat_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]

    def tearDown(self):
        # Cleanup the temporary directory
        self.temp_dir.cleanup()

    @patch("pathlib.Path.home")
    def test_flush_adds_metadata(self, mock_home):
        # Setup mock home to point to our temp directory
        mock_home.return_value = self.history_dir

        # Flush the conversation
        self.agent_context.flush(self.chat_history)

        # Get the path to the saved history file
        history_file = (
            self.history_dir
            / ".hdev"
            / "history"
            / self.agent_context.session_id
            / "root.json"
        )

        # Check if the file exists
        self.assertTrue(history_file.exists())

        # Load the file
        with open(history_file, "r") as f:
            data = json.load(f)

        # Verify metadata fields exist
        self.assertIn("metadata", data)
        self.assertIn("created_at", data["metadata"])
        self.assertIn("last_updated", data["metadata"])
        self.assertIn("root_dir", data["metadata"])

        # Verify created_at and last_updated are valid ISO format dates
        try:
            created_at = datetime.fromisoformat(data["metadata"]["created_at"])
            last_updated = datetime.fromisoformat(data["metadata"]["last_updated"])
            self.assertIsNotNone(created_at)
            self.assertIsNotNone(last_updated)
        except ValueError:
            self.fail("Dates are not in valid ISO format")

        # Verify root_dir is a string and not empty
        self.assertIsInstance(data["metadata"]["root_dir"], str)
        self.assertTrue(len(data["metadata"]["root_dir"]) > 0)

    @patch("pathlib.Path.home")
    def test_update_preserves_created_at(self, mock_home):
        # Setup mock home to point to our temp directory
        mock_home.return_value = self.history_dir

        # Flush the conversation first time
        self.agent_context.flush(self.chat_history)

        # Get the path to the saved history file
        history_file = (
            self.history_dir
            / ".hdev"
            / "history"
            / self.agent_context.session_id
            / "root.json"
        )

        # Load the file to get original created_at
        with open(history_file, "r") as f:
            original_data = json.load(f)
        original_created_at = original_data["metadata"]["created_at"]

        # Wait a moment to ensure timestamps would be different
        import time

        time.sleep(0.1)

        # Update chat history and flush again
        updated_chat_history = self.chat_history.copy()
        updated_chat_history.append({"role": "user", "content": "How are you?"})
        self.agent_context.flush(updated_chat_history)

        # Load the file again
        with open(history_file, "r") as f:
            updated_data = json.load(f)

        # Verify created_at is preserved but last_updated is changed
        self.assertEqual(updated_data["metadata"]["created_at"], original_created_at)
        self.assertNotEqual(
            updated_data["metadata"]["last_updated"], original_created_at
        )


if __name__ == "__main__":
    unittest.main()
