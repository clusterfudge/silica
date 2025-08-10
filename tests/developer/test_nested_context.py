import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from silica.developer.context import AgentContext
from silica.developer.memory import MemoryManager


class JsonSerializableMock:
    """A mock object that can be JSON serialized"""

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class TestNestedContextFlush(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.home_dir_patch = patch("pathlib.Path.home")
        self.mock_home = self.home_dir_patch.start()
        self.mock_home.return_value = Path(self.temp_dir.name)

        # Create a mock memory manager
        self.mock_memory_manager = MagicMock(spec=MemoryManager)

        # Create a mock sandbox
        self.mock_sandbox = JsonSerializableMock(
            check_permissions=lambda *args: True,
            read_file=lambda path: f"Content of {path}",
            write_file=lambda path, content: None,
            get_directory_listing=lambda path, recursive: [path],
        )

        # Create a mock user interface
        self.mock_user_interface = JsonSerializableMock(
            get_user_input=lambda prompt: "",
            display_welcome_message=lambda: None,
            handle_system_message=lambda msg: None,
            handle_user_input=lambda msg: None,
            handle_assistant_message=lambda msg: None,
            handle_tool_use=lambda name, input: None,
            handle_tool_result=lambda name, result: None,
            display_token_count=lambda *args: None,
            permission_callback=lambda *args: True,
            permission_rendering_callback=lambda *args: True,
        )

        # Add a status method that returns a context manager
        class DummyStatus:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def update(self, *args, **kwargs):
                pass

        self.mock_user_interface.status = lambda *args, **kwargs: DummyStatus()

        # Create a model specification
        self.model_spec = {
            "title": "test-model",
            "pricing": {"input": 3.00, "output": 15.00},
            "cache_pricing": {"write": 3.75, "read": 0.30},
        }

    def tearDown(self):
        self.home_dir_patch.stop()
        self.temp_dir.cleanup()

    def create_test_context(self, parent_id=None):
        """Helper to create a test context with proper serialization"""
        return AgentContext(
            session_id=str(uuid4()),
            parent_session_id=parent_id,
            model_spec=self.model_spec,
            sandbox=self.mock_sandbox,
            user_interface=self.mock_user_interface,
            usage=[],
            memory_manager=self.mock_memory_manager,
        )

    def test_multi_level_nesting(self):
        """Test nested contexts flush to correct locations"""
        # Create a root context
        root_context = self.create_test_context()

        # Create a first-level sub-context
        level1_context = self.create_test_context(parent_id=root_context.session_id)

        # Create a second-level sub-context
        level2_context = self.create_test_context(parent_id=level1_context.session_id)

        # Simple chat history
        chat_history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]

        # Flush all contexts
        root_context.flush(chat_history)
        level1_context.flush(chat_history)
        level2_context.flush(chat_history)

        # Check that the root context saved to the correct location
        root_dir = (
            Path(self.temp_dir.name) / ".hdev" / "history" / root_context.session_id
        )
        root_file = root_dir / "root.json"
        self.assertTrue(
            root_file.exists(), f"Root history file not found at {root_file}"
        )

        # Check that the level1 context saved to the root context's directory
        level1_file = root_dir / f"{level1_context.session_id}.json"
        self.assertTrue(
            level1_file.exists(), f"Level 1 history file not found at {level1_file}"
        )

        # Check that the level2 context saved correctly
        # Currently, this would save to level1's directory, which might not be what we want
        level1_dir = (
            Path(self.temp_dir.name) / ".hdev" / "history" / level1_context.session_id
        )
        level2_file = level1_dir / f"{level2_context.session_id}.json"

        # THIS TEST SHOULD FAIL with the current implementation
        self.assertTrue(
            level2_file.exists(), f"Level 2 history file not found at {level2_file}"
        )
