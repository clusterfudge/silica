"""Tests for request/response logging functionality."""

import json
import tempfile
from pathlib import Path
import pytest
from silica.developer.request_logger import RequestResponseLogger


@pytest.fixture
def temp_log_file():
    """Create a temporary log file."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as f:
        log_path = Path(f.name)
    yield log_path
    # Cleanup
    if log_path.exists():
        log_path.unlink()


@pytest.fixture
def logger(temp_log_file):
    """Create a logger instance."""
    return RequestResponseLogger(str(temp_log_file))


def test_logger_disabled_when_no_path():
    """Test that logger is disabled when no path is provided."""
    logger = RequestResponseLogger(None)
    assert not logger.enabled
    assert logger.log_file_path is None


def test_logger_enabled_with_path(temp_log_file):
    """Test that logger is enabled when path is provided."""
    logger = RequestResponseLogger(str(temp_log_file))
    assert logger.enabled
    assert logger.log_file_path == temp_log_file


def test_log_request(logger, temp_log_file):
    """Test logging a request."""
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": [{"type": "text", "text": "Hi there!"}]},
    ]
    system_message = [{"type": "text", "text": "You are a helpful assistant"}]

    logger.log_request(
        messages=messages,
        system_message=system_message,
        model="claude-3-5-sonnet-20241022",
        max_tokens=4096,
        tools=[],
        thinking_config=None,
    )

    # Read the log file
    with open(temp_log_file) as f:
        log_entry = json.loads(f.readline())

    assert log_entry["type"] == "request"
    assert log_entry["model"] == "claude-3-5-sonnet-20241022"
    assert log_entry["max_tokens"] == 4096
    assert len(log_entry["messages"]) == 2
    assert log_entry["messages"][0]["role"] == "user"
    assert log_entry["messages"][0]["content"] == "Hello"
    assert "timestamp" in log_entry
    assert "unix_timestamp" in log_entry


def test_log_response(logger, temp_log_file):
    """Test logging a response."""
    # Create a mock message object
    message = type(
        "Message",
        (),
        {
            "id": "msg_123",
            "content": [
                type("TextBlock", (), {"type": "text", "text": "Hello world"})()
            ],
            "usage": type(
                "Usage",
                (),
                {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            )(),
            "stop_reason": "end_turn",
        },
    )()

    usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    logger.log_response(
        message=message,
        usage=type("Usage", (), usage)(),
        stop_reason="end_turn",
        thinking_content=None,
    )

    # Read the log file
    with open(temp_log_file) as f:
        log_entry = json.loads(f.readline())

    assert log_entry["type"] == "response"
    assert log_entry["message_id"] == "msg_123"
    assert log_entry["stop_reason"] == "end_turn"
    assert log_entry["usage"]["input_tokens"] == 100
    assert log_entry["usage"]["output_tokens"] == 50
    assert "timestamp" in log_entry


def test_log_tool_execution(logger, temp_log_file):
    """Test logging tool execution."""
    logger.log_tool_execution(
        tool_name="read_file",
        tool_input={"path": "test.py"},
        tool_result={
            "type": "tool_result",
            "tool_use_id": "toolu_123",
            "content": "print('hello')",
        },
    )

    # Read the log file
    with open(temp_log_file) as f:
        log_entry = json.loads(f.readline())

    assert log_entry["type"] == "tool_execution"
    assert log_entry["tool_name"] == "read_file"
    assert log_entry["input"]["path"] == "test.py"
    assert log_entry["result"]["content"] == "print('hello')"
    assert "timestamp" in log_entry


def test_log_error(logger, temp_log_file):
    """Test logging an error."""
    logger.log_error(
        error_type="RateLimitError",
        error_message="Rate limit exceeded",
        context={"attempt": 1, "max_retries": 5},
    )

    # Read the log file
    with open(temp_log_file) as f:
        log_entry = json.loads(f.readline())

    assert log_entry["type"] == "error"
    assert log_entry["error_type"] == "RateLimitError"
    assert log_entry["error_message"] == "Rate limit exceeded"
    assert log_entry["context"]["attempt"] == 1
    assert "timestamp" in log_entry


def test_multiple_log_entries(logger, temp_log_file):
    """Test logging multiple entries."""
    logger.log_request(
        messages=[{"role": "user", "content": "Test"}],
        system_message=[],
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        tools=[],
    )

    logger.log_tool_execution(
        tool_name="shell_execute",
        tool_input={"command": "ls"},
        tool_result={
            "type": "tool_result",
            "tool_use_id": "toolu_1",
            "content": "file1.txt",
        },
    )

    logger.log_error(
        error_type="TestError",
        error_message="Test error",
        context={},
    )

    # Read all log entries
    with open(temp_log_file) as f:
        lines = f.readlines()

    assert len(lines) == 3

    entry1 = json.loads(lines[0])
    entry2 = json.loads(lines[1])
    entry3 = json.loads(lines[2])

    assert entry1["type"] == "request"
    assert entry2["type"] == "tool_execution"
    assert entry3["type"] == "error"


def test_large_tool_result_truncation(logger, temp_log_file):
    """Test that large tool results are truncated."""
    large_content = "x" * 20000  # 20KB content

    logger.log_tool_execution(
        tool_name="read_file",
        tool_input={"path": "large_file.txt"},
        tool_result={
            "type": "tool_result",
            "tool_use_id": "toolu_123",
            "content": large_content,
        },
    )

    # Read the log file
    with open(temp_log_file) as f:
        log_entry = json.loads(f.readline())

    # Content should be truncated to 10KB + truncation message
    assert len(log_entry["result"]["content"]) < len(large_content)
    assert "truncated" in log_entry["result"]["content"]


def test_logger_creates_parent_directory(tmp_path):
    """Test that logger creates parent directories if they don't exist."""
    log_path = tmp_path / "logs" / "subdir" / "requests.jsonl"

    logger = RequestResponseLogger(str(log_path))
    assert logger.enabled
    assert log_path.parent.exists()


def test_disabled_logger_no_ops(temp_log_file):
    """Test that disabled logger doesn't write anything."""
    logger = RequestResponseLogger(None)

    logger.log_request(
        messages=[{"role": "user", "content": "Test"}],
        system_message=[],
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        tools=[],
    )

    logger.log_response(
        message=type(
            "Message",
            (),
            {
                "id": "msg_123",
                "content": [],
                "usage": type(
                    "Usage",
                    (),
                    {
                        "input_tokens": 10,
                        "output_tokens": 5,
                    },
                )(),
                "stop_reason": "end_turn",
            },
        )(),
        usage=type(
            "Usage",
            (),
            {
                "input_tokens": 10,
                "output_tokens": 5,
            },
        )(),
        stop_reason="end_turn",
    )

    # Since logger is disabled, no file operations should occur
    # We can't check file content, but we ensure no exceptions are raised


def test_serialize_messages_with_list_content(logger):
    """Test serializing messages with list content."""
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": "World"},
            ],
        }
    ]

    serialized = logger._serialize_messages(messages)

    assert len(serialized) == 1
    assert serialized[0]["role"] == "user"
    assert len(serialized[0]["content"]) == 2
    assert serialized[0]["content"][0]["text"] == "Hello"
    assert serialized[0]["content"][1]["text"] == "World"


def test_serialize_tool_use_block(logger):
    """Test serializing a tool use block."""
    block = type(
        "ToolUseBlock",
        (),
        {
            "type": "tool_use",
            "id": "toolu_123",
            "name": "read_file",
            "input": {"path": "test.py"},
        },
    )()

    serialized = logger._serialize_content_block(block)

    assert serialized["type"] == "tool_use"
    assert serialized["id"] == "toolu_123"
    assert serialized["name"] == "read_file"
    assert serialized["input"]["path"] == "test.py"
