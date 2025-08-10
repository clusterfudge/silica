import os
import tempfile
import unittest
from unittest.mock import patch


# Direct test of the file reading functionality
class TestFilePrompt(unittest.TestCase):
    def test_file_reading(self):
        """Test that a file can be read when specified with @ prefix"""
        # Create a temporary file with test content
        with tempfile.NamedTemporaryFile(
            mode="w+", suffix=".md", delete=False
        ) as temp_file:
            test_content = "This is a test prompt loaded from a file"
            temp_file.write(test_content)
            temp_file.flush()
            filename = temp_file.name

        try:
            # Try reading the file directly to verify it works
            with open(filename, "r") as f:
                content = f.read().strip()
            self.assertEqual(content, test_content)

            # Now test the implementation behavior with a simple mock
            from silica.developer.hdev import main

            # Mock run to capture the arguments
            with patch("silica.developer.hdev.run") as mock_run, patch(
                "silica.developer.hdev.Console"
            ), patch("silica.developer.hdev.AgentContext"):
                # Call main with the file argument
                main(["hdev", "--prompt", f"@{filename}"])

                # Check if run was called with the expected arguments
                mock_run.assert_called_once()
                _, kwargs = mock_run.call_args

                print(f"Expected: '{test_content}'")
                print(f"Got: '{kwargs.get('initial_prompt')}'")

                self.assertEqual(kwargs.get("initial_prompt"), test_content)
                self.assertTrue(kwargs.get("single_response"))

        finally:
            # Cleanup
            os.unlink(filename)


if __name__ == "__main__":
    unittest.main()
