import tempfile
from pathlib import Path
import os

import pytest

from silica.developer.agent_loop import _extract_file_mentions


@pytest.fixture
def temp_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Change to the temp directory to test relative path functionality
        original_cwd = os.getcwd()
        os.chdir(tmpdir)

        try:
            # Create some test files
            tmpdir_path = Path(tmpdir)

            file1_path = Path("test1.txt")
            file1_path.write_text("Content of test1")

            file2_path = Path("test2.txt")
            file2_path.write_text("Content of test2")

            subdir = Path("subdir")
            subdir.mkdir()
            file3_path = subdir / "test3.txt"
            file3_path.write_text("Content of test3")

            # Create a directory to test that directories are filtered out
            test_dir = Path("testdir")
            test_dir.mkdir()

            yield {
                "file1": file1_path,
                "file2": file2_path,
                "file3": file3_path,
                "test_dir": test_dir,
                "root": tmpdir_path,
            }
        finally:
            os.chdir(original_cwd)


def test_extract_file_mentions_with_punctuation(temp_files):
    """Test that trailing punctuation is properly removed from file mentions"""
    message = {
        "role": "user",
        "content": f"Check @{temp_files['file1']}, @{temp_files['file2']}; and @{temp_files['file3']}.",
    }

    result = _extract_file_mentions(message)
    assert len(result) == 3
    assert temp_files["file1"] in result
    assert temp_files["file2"] in result
    assert temp_files["file3"] in result


def test_extract_file_mentions_various_punctuation(temp_files):
    """Test various types of trailing punctuation are removed"""
    message = {
        "role": "user",
        "content": f"Files: @{temp_files['file1']}! @{temp_files['file2']}? @{temp_files['file3']}:",
    }

    result = _extract_file_mentions(message)
    assert len(result) == 3
    assert temp_files["file1"] in result
    assert temp_files["file2"] in result
    assert temp_files["file3"] in result


def test_extract_file_mentions_relative_paths(temp_files):
    """Test that paths are converted to relative paths"""
    message = {
        "role": "user",
        "content": f"Check @{temp_files['file1'].absolute()}",
    }

    result = _extract_file_mentions(message)
    assert len(result) == 1
    # Should be converted to relative path
    assert result[0] == temp_files["file1"]
    assert not result[0].is_absolute()


def test_extract_file_mentions_excludes_directories(temp_files):
    """Test that directories are excluded, only files are returned"""
    message = {
        "role": "user",
        "content": f"Check @{temp_files['file1']} and @{temp_files['test_dir']}/",
    }

    result = _extract_file_mentions(message)
    assert len(result) == 1
    assert temp_files["file1"] in result
    # Directory should not be included
    assert temp_files["test_dir"] not in result


def test_extract_file_mentions_nonexistent_files():
    """Test that nonexistent files are excluded"""
    message = {
        "role": "user",
        "content": "Check @nonexistent.txt and @another/missing.py",
    }

    result = _extract_file_mentions(message)
    assert len(result) == 0


def test_extract_file_mentions_empty_after_punctuation():
    """Test that mentions that become empty after punctuation removal are ignored"""
    message = {
        "role": "user",
        "content": "Check @. and @, and @!",
    }

    result = _extract_file_mentions(message)
    assert len(result) == 0


def test_extract_file_mentions_subdir_relative_paths(temp_files):
    """Test that subdirectory files get proper relative paths"""
    message = {
        "role": "user",
        "content": f"Check @{temp_files['file3']}",
    }

    result = _extract_file_mentions(message)
    assert len(result) == 1
    assert result[0] == temp_files["file3"]
    assert str(result[0]) == "subdir/test3.txt"


def test_extract_file_mentions_list_content_with_punctuation(temp_files):
    """Test punctuation removal works with list content format"""
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": f"Check @{temp_files['file1']},"},
            {"type": "text", "text": f"and @{temp_files['file2']}."},
        ],
    }

    result = _extract_file_mentions(message)
    assert len(result) == 2
    assert temp_files["file1"] in result
    assert temp_files["file2"] in result
