"""Tests for file manipulation tools."""

import pytest
from unittest.mock import MagicMock

from silica.developer.context import AgentContext
from silica.developer.sandbox import Sandbox, SandboxMode
from silica.developer.tools.files import (
    read_file,
    write_file,
    edit_file,
    list_directory,
)


@pytest.fixture
def mock_context(tmp_path):
    """Create a mock context with a real sandbox in a temp directory."""
    mock_ui = MagicMock()
    sandbox = Sandbox(str(tmp_path), SandboxMode.ALLOW_ALL)

    context = MagicMock(spec=AgentContext)
    context.sandbox = sandbox
    context.user_interface = mock_ui

    return context


@pytest.mark.asyncio
async def test_read_file_success(mock_context, tmp_path):
    """Test reading a file successfully."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!")

    result = await read_file(mock_context, "test.txt")
    assert result == "Hello, World!"


@pytest.mark.asyncio
async def test_read_file_not_found(mock_context):
    """Test reading a non-existent file."""
    result = await read_file(mock_context, "nonexistent.txt")
    assert "Error" in result


def test_write_file_success(mock_context, tmp_path):
    """Test writing a file successfully."""
    result = write_file(mock_context, "test.txt", "Hello, World!")
    assert result == "File written successfully"

    test_file = tmp_path / "test.txt"
    assert test_file.exists()
    assert test_file.read_text() == "Hello, World!"


def test_list_directory_success(mock_context, tmp_path):
    """Test listing directory contents."""
    # Create some test files
    (tmp_path / "file1.txt").write_text("content1")
    (tmp_path / "file2.txt").write_text("content2")

    result = list_directory(mock_context, ".")
    assert "file1.txt" in result
    assert "file2.txt" in result
    assert "Contents of ." in result


@pytest.mark.asyncio
async def test_edit_file_success(mock_context, tmp_path):
    """Test editing a file with a unique match."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!\nThis is a test.")

    result = await edit_file(
        mock_context, "test.txt", "Hello, World!", "Hello, Universe!"
    )

    assert result == "File edited successfully"
    assert test_file.read_text() == "Hello, Universe!\nThis is a test."


@pytest.mark.asyncio
async def test_edit_file_not_unique(mock_context, tmp_path):
    """Test editing a file when match text appears multiple times."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!\nHello, World!")

    result = await edit_file(
        mock_context, "test.txt", "Hello, World!", "Hello, Universe!"
    )

    assert "Error" in result
    assert "not unique" in result
    # File should remain unchanged
    assert test_file.read_text() == "Hello, World!\nHello, World!"


@pytest.mark.asyncio
async def test_edit_file_not_found(mock_context, tmp_path):
    """Test editing a file when match text is not found."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!")

    result = await edit_file(
        mock_context, "test.txt", "Goodbye, World!", "Hello, Universe!"
    )

    assert "Error" in result
    assert "Could not find" in result
    # File should remain unchanged
    assert test_file.read_text() == "Hello, World!"


@pytest.mark.asyncio
async def test_edit_file_multiline_match(mock_context, tmp_path):
    """Test editing a file with multiline match text."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("def hello():\n    print('Hello')\n    return True")

    result = await edit_file(
        mock_context,
        "test.txt",
        "def hello():\n    print('Hello')",
        "def hello():\n    print('Hello, Universe!')",
    )

    assert result == "File edited successfully"
    assert (
        test_file.read_text()
        == "def hello():\n    print('Hello, Universe!')\n    return True"
    )


@pytest.mark.asyncio
async def test_edit_file_empty_replacement(mock_context, tmp_path):
    """Test editing a file with empty replacement (deletion)."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!\nThis is a test.")

    result = await edit_file(mock_context, "test.txt", "Hello, World!\n", "")

    assert result == "File edited successfully"
    assert test_file.read_text() == "This is a test."


@pytest.mark.asyncio
async def test_edit_file_preserves_other_content(mock_context, tmp_path):
    """Test that editing preserves content before and after the match."""
    test_file = tmp_path / "test.txt"
    original = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
    test_file.write_text(original)

    result = await edit_file(mock_context, "test.txt", "Line 3", "Modified Line 3")

    assert result == "File edited successfully"
    expected = "Line 1\nLine 2\nModified Line 3\nLine 4\nLine 5"
    assert test_file.read_text() == expected


@pytest.mark.asyncio
async def test_edit_file_case_sensitive(mock_context, tmp_path):
    """Test that edit_file is case-sensitive."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello, World!")

    result = await edit_file(
        mock_context,
        "test.txt",
        "hello, world!",  # lowercase
        "Hello, Universe!",
    )

    assert "Error" in result
    assert "Could not find" in result
    # File should remain unchanged
    assert test_file.read_text() == "Hello, World!"
