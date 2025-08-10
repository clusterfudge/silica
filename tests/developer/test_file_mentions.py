import tempfile
from pathlib import Path
import copy

import pytest

from silica.developer.agent_loop import (
    _extract_file_mentions,
    _inline_latest_file_mentions,
)


@pytest.fixture
def temp_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create some test files
        tmpdir_path = Path(tmpdir)

        file1_path = tmpdir_path / "test1.txt"
        file1_path.write_text("Content of test1")

        file2_path = tmpdir_path / "test2.txt"
        file2_path.write_text("Content of test2")

        subdir = tmpdir_path / "subdir"
        subdir.mkdir()
        file3_path = subdir / "test3.txt"
        file3_path.write_text("Content of test3")

        yield {
            "file1": file1_path,
            "file2": file2_path,
            "file3": file3_path,
            "root": tmpdir_path,
        }


def test_extract_file_mentions_string_content(temp_files):
    # Keep the old string format test to ensure backward compatibility
    message = {
        "role": "user",
        "content": f"Check @{temp_files['file1']} and @{temp_files['file2']} but not @nonexistent.txt",
    }

    result = _extract_file_mentions(message)
    assert len(result) == 2
    assert temp_files["file1"] in result
    assert temp_files["file2"] in result

    # Also test with the new content block format
    message_with_blocks = {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": f"Check @{temp_files['file1']} and @{temp_files['file2']} but not @nonexistent.txt",
            }
        ],
    }

    result_blocks = _extract_file_mentions(message_with_blocks)
    assert len(result_blocks) == 2
    assert temp_files["file1"] in result_blocks
    assert temp_files["file2"] in result_blocks


def test_extract_file_mentions_list_content(temp_files):
    message = {
        "role": "user",
        "content": [
            {"type": "text", "text": f"Check @{temp_files['file1']}"},
            {"type": "text", "text": f"and @{temp_files['file2']}"},
        ],
    }

    result = _extract_file_mentions(message)
    assert len(result) == 2
    assert temp_files["file1"] in result
    assert temp_files["file2"] in result


def test_extract_file_mentions_no_mentions():
    message = {"role": "user", "content": "No file mentions in this message"}

    result = _extract_file_mentions(message)
    assert len(result) == 0


def test_extract_file_mentions_nonexistent_files():
    message = {"role": "user", "content": "Check @nonexistent.txt"}

    result = _extract_file_mentions(message)
    assert len(result) == 0


def test_inline_latest_file_mentions_basic(temp_files):
    chat_history = [
        {
            "role": "user",
            "content": [{"type": "text", "text": f"Check @{temp_files['file1']}"}],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "Looking at it"}]},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Check @{temp_files['file1']} again"}
            ],
        },
    ]

    # Make a deep copy to verify original is not modified
    original = copy.deepcopy(chat_history)

    result = _inline_latest_file_mentions(chat_history)

    # Verify original is not modified
    assert chat_history == original

    # Check that only the last mention has the content
    assert isinstance(result[2]["content"], list)
    assert any(
        f"<mentioned_file path={temp_files['file1'].as_posix()}>" in block["text"]
        for block in result[2]["content"]
    )
    # Both messages should have content in list format
    assert isinstance(result[0]["content"], list)


def test_inline_latest_file_mentions_multiple_files(temp_files):
    chat_history = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"Check @{temp_files['file1']} and @{temp_files['file2']}",
                }
            ],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "Looking at them"}]},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Check @{temp_files['file1']} again"}
            ],
        },
    ]

    original = copy.deepcopy(chat_history)
    result = _inline_latest_file_mentions(chat_history)

    # Verify original is not modified
    assert chat_history == original

    # Check that file1 content is in the last message
    assert isinstance(result[2]["content"], list)
    assert any(
        f"<mentioned_file path={temp_files['file1'].as_posix()}>" in block["text"]
        for block in result[2]["content"]
    )

    # Check that file2 content is in the first message
    assert isinstance(result[0]["content"], list)
    assert any(
        f"<mentioned_file path={temp_files['file2'].as_posix()}>" in block["text"]
        for block in result[0]["content"]
    )


def test_inline_latest_file_mentions_preserves_non_user_messages(temp_files):
    chat_history = [
        {
            "role": "user",
            "content": [{"type": "text", "text": f"Check @{temp_files['file1']}"}],
        },
        {"role": "assistant", "content": [{"type": "text", "text": "Looking at it"}]},
        {"role": "system", "content": [{"type": "text", "text": "System message"}]},
    ]

    original = copy.deepcopy(chat_history)
    result = _inline_latest_file_mentions(chat_history)

    # Verify original is not modified
    assert chat_history == original

    # Check that assistant and system messages are preserved in role and content
    assert result[1]["role"] == chat_history[1]["role"]
    assert result[1]["content"] == chat_history[1]["content"]
    assert result[2]["role"] == chat_history[2]["role"]
    assert result[2]["content"] == chat_history[2]["content"]
