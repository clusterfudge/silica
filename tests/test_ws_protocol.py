"""Tests for WebSocket protocol module."""

import json
import pytest

from silica.serve.protocol import (
    PROTOCOL_VERSION,
    CLIENT_MESSAGE_TYPES,
    SERVER_MESSAGE_TYPES,
    # Client messages
    UserInputMessage,
    ToolResponseMessage,
    InterruptMessage,
    PermissionResponseMessage,
    PingMessage,
    # Server messages
    AssistantMessageChunk,
    AssistantMessageComplete,
    SystemMessage,
    ToolUseMessage,
    ToolResultMessage,
    PermissionRequestMessage,
    TokenCountMessage,
    StatusMessage,
    ThinkingMessage,
    ErrorMessage,
    PongMessage,
    SessionInfoMessage,
    # Functions
    parse_client_message,
    serialize_server_message,
    ProtocolError,
)


class TestProtocolVersion:
    """Test protocol version constant."""

    def test_protocol_version_exists(self):
        assert PROTOCOL_VERSION is not None

    def test_protocol_version_is_string(self):
        assert isinstance(PROTOCOL_VERSION, str)

    def test_protocol_version_format(self):
        parts = PROTOCOL_VERSION.split(".")
        assert len(parts) >= 2
        assert all(part.isdigit() for part in parts)


class TestMessageTypeConstants:
    """Test message type dictionaries."""

    def test_client_message_types_is_dict(self):
        assert isinstance(CLIENT_MESSAGE_TYPES, dict)
        assert len(CLIENT_MESSAGE_TYPES) > 0

    def test_server_message_types_is_dict(self):
        assert isinstance(SERVER_MESSAGE_TYPES, dict)
        assert len(SERVER_MESSAGE_TYPES) > 0

    def test_expected_client_types(self):
        expected = {
            "user_input",
            "tool_response",
            "interrupt",
            "permission_response",
            "ping",
        }
        assert expected == set(CLIENT_MESSAGE_TYPES.keys())

    def test_expected_server_types(self):
        expected = {
            "assistant_chunk",
            "assistant_complete",
            "system_message",
            "tool_use",
            "tool_result",
            "permission_request",
            "token_count",
            "status",
            "thinking",
            "error",
            "pong",
            "session_info",
        }
        assert expected == set(SERVER_MESSAGE_TYPES.keys())


class TestClientMessages:
    """Test client message types."""

    def test_user_input_message(self):
        msg = UserInputMessage(content="Hello, world!")
        assert msg.type == "user_input"
        assert msg.content == "Hello, world!"
        assert msg.session_id is None

    def test_user_input_with_session(self):
        msg = UserInputMessage(content="test", session_id="sess-123")
        assert msg.session_id == "sess-123"

    def test_tool_response_message(self):
        msg = ToolResponseMessage(tool_use_id="tu-123", result={"output": "data"})
        assert msg.type == "tool_response"
        assert msg.tool_use_id == "tu-123"
        assert msg.result == {"output": "data"}
        assert msg.is_error is False

    def test_tool_response_with_error(self):
        msg = ToolResponseMessage(
            tool_use_id="tu-456", result={"error": "Failed"}, is_error=True
        )
        assert msg.is_error is True

    def test_interrupt_message(self):
        msg = InterruptMessage()
        assert msg.type == "interrupt"
        assert msg.reason is None

    def test_interrupt_with_reason(self):
        msg = InterruptMessage(reason="User stopped")
        assert msg.reason == "User stopped"

    def test_permission_response_allowed(self):
        msg = PermissionResponseMessage(request_id="pr-123", allowed=True)
        assert msg.type == "permission_response"
        assert msg.request_id == "pr-123"
        assert msg.allowed is True

    def test_permission_response_denied(self):
        msg = PermissionResponseMessage(request_id="pr-456", allowed=False)
        assert msg.allowed is False

    def test_ping_message(self):
        msg = PingMessage()
        assert msg.type == "ping"


class TestServerMessages:
    """Test server message types."""

    def test_assistant_chunk(self):
        msg = AssistantMessageChunk(content="Hello", message_id="msg-1")
        assert msg.type == "assistant_chunk"
        assert msg.content == "Hello"
        assert msg.message_id == "msg-1"

    def test_assistant_complete(self):
        msg = AssistantMessageComplete(content="Hello, world!", message_id="msg-1")
        assert msg.type == "assistant_complete"
        assert msg.content == "Hello, world!"

    def test_system_message(self):
        msg = SystemMessage(content="Connected.")
        assert msg.type == "system_message"
        assert msg.content == "Connected."
        assert msg.markdown is True
        assert msg.level == "info"

    def test_system_message_levels(self):
        for level in ["info", "warning", "error"]:
            msg = SystemMessage(content="test", level=level)
            assert msg.level == level

    def test_tool_use_message(self):
        msg = ToolUseMessage(
            tool_use_id="tu-1", tool_name="shell_execute", tool_params={"command": "ls"}
        )
        assert msg.type == "tool_use"
        assert msg.tool_name == "shell_execute"
        assert msg.tool_params == {"command": "ls"}

    def test_tool_result_message(self):
        msg = ToolResultMessage(
            tool_use_id="tu-1", tool_name="shell_execute", result={"output": "file.txt"}
        )
        assert msg.type == "tool_result"
        assert msg.result == {"output": "file.txt"}
        assert msg.is_error is False

    def test_permission_request_message(self):
        msg = PermissionRequestMessage(
            request_id="pr-1", action="shell", resource="ls -la"
        )
        assert msg.type == "permission_request"
        assert msg.action == "shell"
        assert msg.resource == "ls -la"

    def test_token_count_message(self):
        msg = TokenCountMessage(
            prompt_tokens=100, completion_tokens=50, total_tokens=150, total_cost=0.001
        )
        assert msg.type == "token_count"
        assert msg.prompt_tokens == 100
        assert msg.total_cost == 0.001

    def test_status_message(self):
        msg = StatusMessage(message="Processing...")
        assert msg.type == "status"
        assert msg.message == "Processing..."
        assert msg.active is True

    def test_thinking_message(self):
        msg = ThinkingMessage(content="Analyzing...", tokens=500, cost=0.01)
        assert msg.type == "thinking"
        assert msg.tokens == 500
        assert msg.collapsed is True

    def test_error_message(self):
        msg = ErrorMessage(code="RATE_LIMIT", message="Too many requests")
        assert msg.type == "error"
        assert msg.code == "RATE_LIMIT"
        assert msg.recoverable is True

    def test_pong_message(self):
        msg = PongMessage()
        assert msg.type == "pong"

    def test_session_info_message(self):
        msg = SessionInfoMessage(session_id="sess-123")
        assert msg.type == "session_info"
        assert msg.session_id == "sess-123"
        assert msg.protocol_version == PROTOCOL_VERSION
        assert msg.resumed is False


class TestParseClientMessage:
    """Test parse_client_message function."""

    def test_parse_user_input(self):
        data = {"type": "user_input", "content": "Hello"}
        msg = parse_client_message(data)
        assert isinstance(msg, UserInputMessage)
        assert msg.content == "Hello"

    def test_parse_user_input_from_json_string(self):
        data = '{"type": "user_input", "content": "Hello"}'
        msg = parse_client_message(data)
        assert isinstance(msg, UserInputMessage)

    def test_parse_tool_response(self):
        data = {"type": "tool_response", "tool_use_id": "tu-1", "result": {"data": 1}}
        msg = parse_client_message(data)
        assert isinstance(msg, ToolResponseMessage)

    def test_parse_interrupt(self):
        data = {"type": "interrupt"}
        msg = parse_client_message(data)
        assert isinstance(msg, InterruptMessage)

    def test_parse_permission_response(self):
        data = {"type": "permission_response", "request_id": "pr-1", "allowed": True}
        msg = parse_client_message(data)
        assert isinstance(msg, PermissionResponseMessage)

    def test_parse_ping(self):
        data = {"type": "ping"}
        msg = parse_client_message(data)
        assert isinstance(msg, PingMessage)

    def test_parse_invalid_type_raises_error(self):
        data = {"type": "unknown_type"}
        with pytest.raises(ProtocolError) as exc:
            parse_client_message(data)
        assert exc.value.code == "UNKNOWN_TYPE"

    def test_parse_missing_type_raises_error(self):
        data = {"content": "Hello"}
        with pytest.raises(ProtocolError) as exc:
            parse_client_message(data)
        assert exc.value.code == "MISSING_TYPE"

    def test_parse_invalid_json_raises_error(self):
        data = "not valid json{"
        with pytest.raises(ProtocolError) as exc:
            parse_client_message(data)
        assert exc.value.code == "INVALID_JSON"

    def test_parse_missing_required_field(self):
        # UserInputMessage requires 'content'
        data = {"type": "user_input"}
        with pytest.raises(ProtocolError) as exc:
            parse_client_message(data)
        assert exc.value.code == "VALIDATION_ERROR"


class TestSerializeServerMessage:
    """Test serialize_server_message function."""

    def test_serialize_assistant_chunk(self):
        msg = AssistantMessageChunk(content="Hi", message_id="m-1")
        result = serialize_server_message(msg)
        data = json.loads(result)
        assert data["type"] == "assistant_chunk"
        assert data["content"] == "Hi"

    def test_serialize_system_message(self):
        msg = SystemMessage(content="Hello")
        result = serialize_server_message(msg)
        data = json.loads(result)
        assert data["type"] == "system_message"

    def test_serialize_tool_use(self):
        msg = ToolUseMessage(tool_use_id="tu-1", tool_name="test", tool_params={"a": 1})
        result = serialize_server_message(msg)
        data = json.loads(result)
        assert data["tool_params"] == {"a": 1}

    def test_serialize_error_message(self):
        msg = ErrorMessage(code="ERR", message="Test error")
        result = serialize_server_message(msg)
        data = json.loads(result)
        assert data["code"] == "ERR"

    def test_serialize_all_server_types(self):
        """Ensure all server message types can be serialized."""
        messages = [
            AssistantMessageChunk(content="", message_id="m"),
            AssistantMessageComplete(content="", message_id="m"),
            SystemMessage(content=""),
            ToolUseMessage(tool_use_id="t", tool_name="n", tool_params={}),
            ToolResultMessage(tool_use_id="t", tool_name="n", result={}),
            PermissionRequestMessage(request_id="r", action="a", resource="r"),
            TokenCountMessage(
                prompt_tokens=0, completion_tokens=0, total_tokens=0, total_cost=0
            ),
            StatusMessage(message=""),
            ThinkingMessage(content="", tokens=0, cost=0),
            ErrorMessage(code="", message=""),
            PongMessage(),
            SessionInfoMessage(session_id="s"),
        ]
        for msg in messages:
            result = serialize_server_message(msg)
            assert isinstance(result, str)
            data = json.loads(result)
            assert "type" in data


class TestProtocolError:
    """Test ProtocolError exception."""

    def test_protocol_error_is_exception(self):
        error = ProtocolError(code="TEST", message="Test error")
        assert isinstance(error, Exception)

    def test_protocol_error_attributes(self):
        error = ProtocolError(
            code="ERR_CODE", message="Error message", details={"key": "value"}
        )
        assert error.code == "ERR_CODE"
        assert error.message == "Error message"
        assert error.details == {"key": "value"}

    def test_protocol_error_can_be_raised(self):
        with pytest.raises(ProtocolError) as exc:
            raise ProtocolError(code="TEST", message="Test")
        assert exc.value.code == "TEST"


class TestRoundTrip:
    """Test message round-trip serialization."""

    def test_user_input_roundtrip(self):
        original = {"type": "user_input", "content": "Hello, world!"}
        msg = parse_client_message(original)
        # Client messages don't have serialize, but we can verify parsing
        assert msg.content == original["content"]

    def test_unicode_content(self):
        msg = UserInputMessage(content="Hello 世界 🌍")
        assert msg.content == "Hello 世界 🌍"

    def test_empty_content(self):
        msg = UserInputMessage(content="")
        assert msg.content == ""

    def test_special_characters(self):
        msg = UserInputMessage(content="Line1\nLine2\tTabbed")
        assert "\n" in msg.content
        assert "\t" in msg.content
