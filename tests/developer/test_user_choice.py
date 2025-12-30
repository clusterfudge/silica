"""Tests for the user_choice tool."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import json

from silica.developer.tools.user_choice import user_choice


@pytest.fixture
def mock_context():
    """Create a mock context with a mock user interface."""
    context = MagicMock()
    context.user_interface = MagicMock()
    return context


class TestUserChoiceTool:
    """Test the user_choice tool."""

    @pytest.mark.asyncio
    async def test_user_choice_with_get_user_choice_method(self, mock_context):
        """Test that user_choice uses get_user_choice when available."""
        # Set up mock to return a selected option
        mock_context.user_interface.get_user_choice = AsyncMock(return_value="Option 2")

        options = json.dumps(["Option 1", "Option 2", "Option 3"])
        result = await user_choice(mock_context, "Which option?", options)

        assert result == "Option 2"
        mock_context.user_interface.get_user_choice.assert_called_once_with(
            "Which option?", ["Option 1", "Option 2", "Option 3"]
        )

    @pytest.mark.asyncio
    async def test_user_choice_fallback_number_selection(self, mock_context):
        """Test fallback behavior when get_user_choice is not available."""
        # Remove get_user_choice method to trigger fallback
        del mock_context.user_interface.get_user_choice

        # Mock get_user_input to return a number
        mock_context.user_interface.get_user_input = AsyncMock(return_value="2")

        options = json.dumps(["Option 1", "Option 2", "Option 3"])
        result = await user_choice(mock_context, "Which option?", options)

        assert result == "Option 2"

    @pytest.mark.asyncio
    async def test_user_choice_fallback_text_input(self, mock_context):
        """Test fallback with free text input."""
        del mock_context.user_interface.get_user_choice

        # Mock get_user_input to return text directly
        mock_context.user_interface.get_user_input = AsyncMock(
            return_value="something custom"
        )

        options = json.dumps(["Option 1", "Option 2"])
        result = await user_choice(mock_context, "Which option?", options)

        assert result == "something custom"

    @pytest.mark.asyncio
    async def test_user_choice_fallback_say_something_else(self, mock_context):
        """Test fallback when user selects 'say something else' option."""
        del mock_context.user_interface.get_user_choice

        # First call returns the number for "say something else", second returns custom text
        mock_context.user_interface.get_user_input = AsyncMock(
            side_effect=["3", "my custom response"]
        )

        options = json.dumps(["Option 1", "Option 2"])
        result = await user_choice(mock_context, "Which option?", options)

        assert result == "my custom response"

    @pytest.mark.asyncio
    async def test_user_choice_invalid_json(self, mock_context):
        """Test error handling for invalid JSON."""
        result = await user_choice(mock_context, "Which?", "not valid json")

        assert "Error parsing options JSON" in result

    @pytest.mark.asyncio
    async def test_user_choice_not_array(self, mock_context):
        """Test error handling when options is not an array."""
        result = await user_choice(mock_context, "Which?", '{"key": "value"}')

        assert "Error: options must be a JSON array" in result

    @pytest.mark.asyncio
    async def test_user_choice_non_string_options(self, mock_context):
        """Test error handling when options contains non-strings."""
        result = await user_choice(mock_context, "Which?", "[1, 2, 3]")

        assert "Error: all options must be strings" in result

    @pytest.mark.asyncio
    async def test_user_choice_empty_options_freeform(self, mock_context):
        """Test that empty options triggers free-form text input."""
        # Mock get_user_input for free-form
        mock_context.user_interface.get_user_input = AsyncMock(return_value="my answer")

        result = await user_choice(mock_context, "What's your name?", "")

        assert result == "my answer"

    @pytest.mark.asyncio
    async def test_user_choice_no_options_freeform(self, mock_context):
        """Test that no options parameter triggers free-form text input."""
        mock_context.user_interface.get_user_input = AsyncMock(
            return_value="free input"
        )

        result = await user_choice(mock_context, "Tell me something")

        assert result == "free input"


class TestUserChoiceMultiQuestion:
    """Test the multi-question mode of user_choice."""

    @pytest.mark.asyncio
    async def test_multi_question_detected(self, mock_context):
        """Test that JSON array of questions triggers multi-question mode."""
        # Mock run_questionnaire to return answers
        mock_context.user_interface.run_questionnaire = AsyncMock(
            return_value={"name": "test", "type": "web"}
        )

        questions = json.dumps(
            [
                {"id": "name", "prompt": "Project name?"},
                {"id": "type", "prompt": "Type?", "options": ["web", "cli"]},
            ]
        )

        result = await user_choice(mock_context, questions)
        parsed = json.loads(result)

        assert parsed == {"name": "test", "type": "web"}

    @pytest.mark.asyncio
    async def test_multi_question_cancelled(self, mock_context):
        """Test multi-question cancellation."""
        mock_context.user_interface.run_questionnaire = AsyncMock(return_value=None)

        questions = json.dumps([{"id": "name", "prompt": "Name?"}])

        result = await user_choice(mock_context, questions)
        parsed = json.loads(result)

        assert parsed == {"cancelled": True}

    @pytest.mark.asyncio
    async def test_single_question_not_confused_with_multi(self, mock_context):
        """Test that a regular question isn't confused with multi-question mode."""
        mock_context.user_interface.get_user_choice = AsyncMock(return_value="Yes")

        # This looks like it might be JSON but isn't a valid question array
        result = await user_choice(
            mock_context, "Do you want to continue?", '["Yes", "No"]'
        )

        assert result == "Yes"
        mock_context.user_interface.get_user_choice.assert_called_once()


class TestUserChoiceSchema:
    """Test the user_choice tool schema."""

    def test_schema_has_required_fields(self):
        """Test that the schema has all required fields."""
        schema = user_choice.schema()

        assert schema["name"] == "user_choice"
        assert "description" in schema
        assert "input_schema" in schema

    def test_schema_required_parameters(self):
        """Test that only question is required (options is optional)."""
        schema = user_choice.schema()

        assert "question" in schema["input_schema"]["required"]
        # options is now optional for free-form and multi-question modes
        assert "options" not in schema["input_schema"]["required"]

    def test_schema_parameter_types(self):
        """Test parameter types in schema."""
        schema = user_choice.schema()
        props = schema["input_schema"]["properties"]

        assert props["question"]["type"] == "string"
        assert props["options"]["type"] == "string"
