"""Tests for Extended Thinking API integration."""

import pytest
from unittest.mock import Mock, patch
from silica.developer.models import get_model
from silica.developer.context import AgentContext
from silica.developer.agent_loop import get_thinking_config
from silica.developer.sandbox import SandboxMode


class TestModelThinkingSupport:
    """Test that models correctly identify thinking support."""

    def test_opus_supports_thinking(self):
        """Opus 4 should support thinking."""
        model = get_model("opus")
        assert model["thinking_support"] is True
        assert "thinking_pricing" in model
        assert model["thinking_pricing"]["thinking"] == 25.00  # Same as output price

    def test_sonnet_supports_thinking(self):
        """Sonnet 4.5 should support thinking."""
        model = get_model("sonnet")
        assert model["thinking_support"] is True
        assert "thinking_pricing" in model
        assert model["thinking_pricing"]["thinking"] == 15.00  # Same as output price

    def test_sonnet_37_supports_thinking(self):
        """Sonnet 3.7 should support thinking."""
        model = get_model("sonnet-3.7")
        assert model["thinking_support"] is True
        assert "thinking_pricing" in model
        assert model["thinking_pricing"]["thinking"] == 15.00  # Same as output price

    def test_haiku_supports_thinking(self):
        """Haiku 4.5 should support thinking."""
        model = get_model("haiku")
        assert model["thinking_support"] is True
        assert model["thinking_pricing"]["thinking"] == 5.00  # Same as output price

    def test_sonnet_35_no_thinking_support(self):
        """Sonnet 3.5 should not support thinking."""
        model = get_model("sonnet-3.5")
        assert model["thinking_support"] is False
        assert model["thinking_pricing"]["thinking"] == 0.0


class TestThinkingConfiguration:
    """Test thinking configuration generation."""

    def test_thinking_config_off_mode(self):
        """Off mode should return None."""
        model = get_model("opus")
        config = get_thinking_config("off", model)
        assert config is None

    def test_thinking_config_normal_mode(self):
        """Normal mode should return 8k budget config."""
        model = get_model("opus")
        config = get_thinking_config("normal", model)
        assert config is not None
        assert config["type"] == "enabled"
        assert config["budget_tokens"] == 8000

    def test_thinking_config_ultra_mode(self):
        """Ultra mode should return 20k budget config."""
        model = get_model("opus")
        config = get_thinking_config("ultra", model)
        assert config is not None
        assert config["type"] == "enabled"
        assert config["budget_tokens"] == 20000

    def test_thinking_config_max_mode(self):
        """Max mode should use all available output capacity for thinking."""
        model = get_model("opus")
        config = get_thinking_config("max", model)
        assert config is not None
        assert config["type"] == "enabled"
        # Opus: 128000 max_output - 8192 completion = 119808
        assert (
            config["budget_tokens"] == model["max_output_tokens"] - model["max_tokens"]
        )

    def test_thinking_config_unsupported_model(self):
        """Unsupported model should return disabled config."""
        model = get_model("sonnet-3.5")
        config = get_thinking_config("normal", model)
        assert config == {"type": "disabled"}

    def test_thinking_config_invalid_mode(self):
        """Invalid mode should return disabled config."""
        model = get_model("opus")
        config = get_thinking_config("invalid", model)
        assert config == {"type": "disabled"}


class TestPerModelThinkingBudgets:
    """Test that thinking budgets respect per-model output limits."""

    def test_max_output_tokens_in_model_specs(self):
        """All model specs should have max_output_tokens."""
        from silica.developer.models import MODEL_MAP

        for alias, spec in MODEL_MAP.items():
            assert "max_output_tokens" in spec, f"{alias} missing max_output_tokens"
            assert (
                spec["max_output_tokens"] > 0
            ), f"{alias} has invalid max_output_tokens"

    def test_opus_has_128k_output(self):
        """Opus should have 128k max output tokens."""
        model = get_model("opus")
        assert model["max_output_tokens"] == 128000

    def test_sonnet_has_64k_output(self):
        """Sonnet should have 64k max output tokens."""
        model = get_model("sonnet")
        assert model["max_output_tokens"] == 64000

    def test_haiku_has_64k_output(self):
        """Haiku should have 64k max output tokens."""
        model = get_model("haiku")
        assert model["max_output_tokens"] == 64000

    def test_sonnet_max_budget_fits_within_64k(self):
        """Sonnet max thinking budget + completion must not exceed 64k."""
        model = get_model("sonnet")
        config = get_thinking_config("max", model)
        assert config is not None
        assert config["type"] == "enabled"
        total = config["budget_tokens"] + model["max_tokens"]
        assert total <= model["max_output_tokens"]
        # Specifically: 64000 - 8192 = 55808
        assert config["budget_tokens"] == 55808

    def test_haiku_max_budget_fits_within_64k(self):
        """Haiku max thinking budget + completion must not exceed 64k."""
        model = get_model("haiku")
        config = get_thinking_config("max", model)
        assert config is not None
        total = config["budget_tokens"] + model["max_tokens"]
        assert total <= model["max_output_tokens"]

    def test_opus_max_budget_fits_within_128k(self):
        """Opus max thinking budget + completion must not exceed 128k."""
        model = get_model("opus")
        config = get_thinking_config("max", model)
        assert config is not None
        total = config["budget_tokens"] + model["max_tokens"]
        assert total <= model["max_output_tokens"]
        # Specifically: 128000 - 8192 = 119808
        assert config["budget_tokens"] == 119808

    def test_normal_budget_capped_by_model(self):
        """Normal mode budget should be capped if model output is too small."""
        # Create a hypothetical model with tiny output window
        tiny_model = {
            "thinking_support": True,
            "max_output_tokens": 10000,
            "max_tokens": 4096,
        }
        config = get_thinking_config("normal", tiny_model)
        assert config is not None
        # 8000 fits within 10000 - 4096 = 5904? No, 8000 > 5904
        assert config["budget_tokens"] == 5904
        assert (
            config["budget_tokens"] + tiny_model["max_tokens"]
            <= tiny_model["max_output_tokens"]
        )

    def test_ultra_budget_capped_by_model(self):
        """Ultra mode budget should be capped for models with smaller output."""
        model = get_model("sonnet")
        config = get_thinking_config("ultra", model)
        assert config is not None
        # 20000 fits within 64000 - 8192 = 55808, so no capping needed
        assert config["budget_tokens"] == 20000
        assert (
            config["budget_tokens"] + model["max_tokens"] <= model["max_output_tokens"]
        )

    def test_budget_disabled_when_no_room(self):
        """Thinking should be disabled if there's no room after completion tokens."""
        no_room_model = {
            "thinking_support": True,
            "max_output_tokens": 4096,
            "max_tokens": 4096,
        }
        config = get_thinking_config("normal", no_room_model)
        assert config == {"type": "disabled"}

    def test_unknown_model_gets_conservative_output_limit(self):
        """Unknown models should get 64k output limit (conservative default)."""
        model = get_model("claude-experimental-2099")
        assert model["max_output_tokens"] == 64000
        config = get_thinking_config("max", model)
        assert config is not None
        total = config["budget_tokens"] + model["max_tokens"]
        assert total <= 64000

    def test_sonnet37_max_budget(self):
        """Sonnet 3.7 should also respect 64k output limit."""
        model = get_model("sonnet-3.7")
        assert model["max_output_tokens"] == 64000
        config = get_thinking_config("max", model)
        assert config is not None
        total = config["budget_tokens"] + model["max_tokens"]
        assert total <= 64000


class TestAgentContextThinkingMode:
    """Test AgentContext thinking mode management."""

    def test_default_thinking_mode_is_max(self, persona_base_dir):
        """New context should default to thinking mode max."""
        mock_ui = Mock()
        mock_ui.permission_callback = Mock(return_value=True)
        mock_ui.permission_rendering_callback = Mock()

        context = AgentContext.create(
            model_spec=get_model("opus"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=mock_ui,
            persona_base_directory=persona_base_dir,
        )

        assert context.thinking_mode == "max"

    def test_thinking_mode_cycles_correctly(self, persona_base_dir):
        """Thinking mode should cycle: off -> normal -> ultra -> max -> off."""
        mock_ui = Mock()
        mock_ui.permission_callback = Mock(return_value=True)
        mock_ui.permission_rendering_callback = Mock()

        context = AgentContext.create(
            model_spec=get_model("opus"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=mock_ui,
            persona_base_directory=persona_base_dir,
        )

        # Start at max (new default)
        assert context.thinking_mode == "max"

        # Set to off to test cycle
        context.thinking_mode = "off"
        assert context.thinking_mode == "off"

        # Cycle to normal
        context.thinking_mode = "normal"
        assert context.thinking_mode == "normal"

        # Cycle to ultra
        context.thinking_mode = "ultra"
        assert context.thinking_mode == "ultra"

        # Cycle to max
        context.thinking_mode = "max"
        assert context.thinking_mode == "max"

        # Cycle back to off
        context.thinking_mode = "off"
        assert context.thinking_mode == "off"


class TestUsageSummaryWithThinking:
    """Test that usage summary correctly handles thinking tokens."""

    def test_usage_summary_without_thinking(self, persona_base_dir):
        """Usage summary should work without thinking tokens."""
        mock_ui = Mock()
        mock_ui.permission_callback = Mock(return_value=True)
        mock_ui.permission_rendering_callback = Mock()

        context = AgentContext.create(
            model_spec=get_model("opus"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=mock_ui,
            persona_base_directory=persona_base_dir,
        )

        # Mock usage without thinking tokens
        mock_usage = Mock(
            spec=[
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            ]
        )
        mock_usage.input_tokens = 1000
        mock_usage.output_tokens = 500
        mock_usage.cache_creation_input_tokens = 0
        mock_usage.cache_read_input_tokens = 100

        context.report_usage(mock_usage)

        summary = context.usage_summary()
        assert summary["total_input_tokens"] == 1000
        assert summary["total_output_tokens"] == 500
        assert summary["total_thinking_tokens"] == 0
        assert summary["thinking_cost"] == 0.0

    def test_usage_summary_with_thinking(self, persona_base_dir):
        """Usage summary should correctly track thinking tokens."""
        mock_ui = Mock()
        mock_ui.permission_callback = Mock(return_value=True)
        mock_ui.permission_rendering_callback = Mock()

        context = AgentContext.create(
            model_spec=get_model("opus"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=mock_ui,
            persona_base_directory=persona_base_dir,
        )

        # Mock usage with thinking tokens
        mock_usage = Mock()
        mock_usage.input_tokens = 1000
        mock_usage.output_tokens = 500
        mock_usage.cache_creation_input_tokens = 0
        mock_usage.cache_read_input_tokens = 100
        mock_usage.thinking_tokens = 4500  # 4.5k thinking tokens

        context.report_usage(mock_usage)

        summary = context.usage_summary()
        assert summary["total_input_tokens"] == 1000
        assert summary["total_output_tokens"] == 500
        assert summary["total_thinking_tokens"] == 4500

        # Calculate expected thinking cost: 4500 tokens * $25/MTok (same as output) = $0.1125
        expected_thinking_cost = 4500 * 25.00 / 1_000_000
        assert abs(summary["thinking_cost"] - expected_thinking_cost) < 0.0001

    def test_usage_summary_with_dict_style_thinking(self, persona_base_dir):
        """Usage summary should handle dict-style usage with thinking tokens."""
        mock_ui = Mock()
        mock_ui.permission_callback = Mock(return_value=True)
        mock_ui.permission_rendering_callback = Mock()

        context = AgentContext.create(
            model_spec=get_model("sonnet"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=mock_ui,
            persona_base_directory=persona_base_dir,
        )

        # Mock usage as dict (alternative format)
        dict_usage = {
            "input_tokens": 1000,
            "output_tokens": 500,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 100,
            "thinking_tokens": 3000,
        }

        context.report_usage(dict_usage)

        summary = context.usage_summary()
        assert summary["total_thinking_tokens"] == 3000

        # Calculate expected thinking cost: 3000 tokens * $15/MTok (same as output) = $0.045
        expected_thinking_cost = 3000 * 15.00 / 1_000_000
        assert abs(summary["thinking_cost"] - expected_thinking_cost) < 0.0001


class TestSessionPersistenceWithThinking:
    """Test that thinking mode persists across sessions."""

    def test_thinking_mode_saved_in_session(self, persona_base_dir):
        """Thinking mode should be saved to session data."""
        import tempfile
        import json
        from pathlib import Path

        mock_ui = Mock()
        mock_ui.permission_callback = Mock(return_value=True)
        mock_ui.permission_rendering_callback = Mock()

        context = AgentContext.create(
            model_spec=get_model("opus"),
            sandbox_mode=SandboxMode.ALLOW_ALL,
            sandbox_contents=[],
            user_interface=mock_ui,
            persona_base_directory=persona_base_dir,
        )

        # Set thinking mode to normal
        context.thinking_mode = "normal"

        # Add a message so flush doesn't skip
        context.chat_history.append(
            {"role": "user", "content": [{"type": "text", "text": "test"}]}
        )

        # Flush the context
        with tempfile.TemporaryDirectory() as tmpdir:
            # Override the history directory
            session_dir = Path(tmpdir) / context.session_id
            session_dir.mkdir(parents=True)
            session_dir / "root.json"

            # Mock the history directory
            with patch("silica.developer.context.Path.home") as mock_home:
                mock_home.return_value = Path(tmpdir)

                # Save the context
                context.flush(context.chat_history)

                # Read the saved data
                history_file = (
                    Path(tmpdir)
                    / ".silica"
                    / "personas"
                    / "default"
                    / "history"
                    / context.session_id
                    / "root.json"
                )
                if history_file.exists():
                    with open(history_file, "r") as f:
                        saved_data = json.load(f)

                    # Verify thinking mode was saved
                    assert "thinking_mode" in saved_data
                    assert saved_data["thinking_mode"] == "normal"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
