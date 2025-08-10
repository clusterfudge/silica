import unittest
from unittest.mock import MagicMock
from silica.developer.prompt import (
    build_tree,
    render_tree,
    render_sandbox_content,
    estimate_token_count,
    create_system_message,
)


class TestPrompt(unittest.TestCase):
    def test_build_tree(self):
        mock_sandbox = MagicMock()
        mock_sandbox.get_directory_listing.return_value = [
            "file1.txt",
            "dir1/file2.txt",
            "dir1/subdir/file3.txt",
        ]

        expected_tree = {
            "file1.txt": {"path": "file1.txt", "is_leaf": True},
            "is_leaf": False,
            "dir1": {
                "file2.txt": {"path": "dir1/file2.txt", "is_leaf": True},
                "is_leaf": False,
                "subdir": {
                    "is_leaf": False,
                    "file3.txt": {"path": "dir1/subdir/file3.txt", "is_leaf": True},
                },
            },
        }

        result = build_tree(mock_sandbox)
        self.assertEqual(expected_tree, result)

    def test_render_tree(self):
        tree = {
            "file1.txt": {"path": "file1.txt", "is_leaf": True},
            "dir1": {
                "file2.txt": {"path": "dir1/file2.txt", "is_leaf": True},
                "subdir": {
                    "file3.txt": {"path": "dir1/subdir/file3.txt", "is_leaf": True}
                },
            },
        }

        expected_output = """dir1/
  file2.txt
  subdir/
    file3.txt
file1.txt
"""

        result = render_tree(tree)
        self.assertEqual(result, expected_output)

    def test_render_sandbox_content(self):
        mock_sandbox = MagicMock()
        mock_sandbox.get_directory_listing.return_value = [
            "file1.txt",
            "dir1/file2.txt",
        ]

        expected_output = """<sandbox_contents>
dir1/
  file2.txt
file1.txt
</sandbox_contents>
"""

        result = render_sandbox_content(mock_sandbox, False)
        self.assertEqual(expected_output, result)

    def test_estimate_token_count(self):
        text = "This is a sample text with ten words in it."
        result = estimate_token_count(text)
        self.assertAlmostEqual(result, 13, delta=1)  # 10 words * 1.3 ≈ 13 tokens

    def test_create_system_message(self):
        mock_sandbox = MagicMock()
        mock_sandbox.get_directory_listing.return_value = [
            "file1.txt",
            "dir1/file2.txt",
            "dir1/subdir/file3.txt",
        ]

        mock_agent_context = MagicMock()
        mock_agent_context.sandbox = mock_sandbox

        result = create_system_message(mock_agent_context)
        # Check the structure is a list with at least two text blocks
        self.assertIsInstance(result, list)
        self.assertTrue(len(result) >= 2)

        # First section contains the AI assistant introduction
        first_content = result[0]["text"]
        self.assertIn(
            "You are an AI assistant with access to a sandbox environment.",
            first_content,
        )

        # Second section contains the sandbox contents
        second_content = result[1]["text"]
        self.assertIn("<sandbox_contents>", second_content)
        self.assertIn("file1.txt", second_content)
        self.assertIn("dir1/", second_content)
        self.assertIn("file2.txt", second_content)
        self.assertIn("</sandbox_contents>", second_content)
        self.assertIn(
            "You can read, write, and list files/directories, as well as execute some bash commands.",
            second_content,
        )


if __name__ == "__main__":
    unittest.main()
