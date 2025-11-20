"""Tests for custom model name fallback to Opus ModelSpec."""

from silica.developer.models import get_model, model_names


def test_get_registered_model():
    """Test that registered models are returned correctly."""
    sonnet = get_model("sonnet")
    assert sonnet["title"] == "claude-sonnet-4-5-20250929"
    assert sonnet["pricing"]["input"] == 3.00

    opus = get_model("opus")
    assert opus["title"] == "claude-opus-4-20250514"
    assert opus["pricing"]["input"] == 15.00

    haiku = get_model("haiku")
    assert haiku["title"] == "claude-3-5-haiku-20241022"
    assert haiku["pricing"]["input"] == 0.80


def test_get_model_case_insensitive():
    """Test that model lookup is case-insensitive."""
    sonnet_upper = get_model("SONNET")
    sonnet_lower = get_model("sonnet")
    assert sonnet_upper["title"] == sonnet_lower["title"]

    opus_mixed = get_model("OpUs")
    opus_lower = get_model("opus")
    assert opus_mixed["title"] == opus_lower["title"]


def test_get_model_by_full_name():
    """Test that models can be retrieved by their full title."""
    model = get_model("claude-sonnet-4-5-20250929")
    assert model["title"] == "claude-sonnet-4-5-20250929"
    assert model["pricing"]["input"] == 3.00


def test_custom_model_uses_opus_fallback():
    """Test that unregistered model names use Opus ModelSpec as fallback."""
    custom_model = get_model("claude-custom-model-xyz")

    # Should use Opus pricing and limits
    opus = get_model("opus")
    assert custom_model["pricing"] == opus["pricing"]
    assert custom_model["cache_pricing"] == opus["cache_pricing"]
    assert custom_model["max_tokens"] == opus["max_tokens"]
    assert custom_model["context_window"] == opus["context_window"]
    assert custom_model["thinking_support"] == opus["thinking_support"]
    assert custom_model["thinking_pricing"] == opus["thinking_pricing"]

    # But should have the custom model name
    assert custom_model["title"] == "claude-custom-model-xyz"
    assert custom_model["title"] != opus["title"]


def test_custom_model_preserves_name():
    """Test that custom model names are preserved in the ModelSpec."""
    custom_names = [
        "claude-3-opus-20240229",
        "claude-sonnet-experimental",
        "claude-4-opus-preview",
        "my-custom-model",
    ]

    for name in custom_names:
        model = get_model(name)
        assert model["title"] == name


def test_custom_model_is_copy():
    """Test that custom models don't modify the original Opus spec."""
    custom1 = get_model("custom-model-1")
    custom2 = get_model("custom-model-2")
    opus = get_model("opus")

    # Custom models should have different titles
    assert custom1["title"] != custom2["title"]
    assert custom1["title"] != opus["title"]
    assert custom2["title"] != opus["title"]

    # But same pricing (from Opus)
    assert custom1["pricing"] == opus["pricing"]
    assert custom2["pricing"] == opus["pricing"]


def test_model_names_returns_registered_only():
    """Test that model_names() still returns only registered models."""
    names = model_names()

    # Should include all registered model aliases
    assert "opus" in names
    assert "sonnet" in names
    assert "haiku" in names

    # Should include full model titles
    assert "claude-opus-4-20250514" in names
    assert "claude-sonnet-4-5-20250929" in names

    # Should NOT include arbitrary custom names
    assert "custom-model-xyz" not in names


def test_opus_spec_not_modified():
    """Test that getting custom models doesn't modify the original Opus spec."""
    # Get the original Opus spec
    opus_before = get_model("opus")
    original_title = opus_before["title"]

    # Get some custom models
    custom1 = get_model("custom-model-1")
    custom2 = get_model("custom-model-2")

    # Get Opus again
    opus_after = get_model("opus")

    # Opus title should be unchanged
    assert opus_after["title"] == original_title
    assert opus_after["title"] != custom1["title"]
    assert opus_after["title"] != custom2["title"]


def test_fallback_has_all_required_fields():
    """Test that fallback ModelSpec has all required fields."""
    custom = get_model("my-custom-model")

    # Check all required fields are present
    assert "title" in custom
    assert "pricing" in custom
    assert "cache_pricing" in custom
    assert "max_tokens" in custom
    assert "context_window" in custom
    assert "thinking_support" in custom
    assert "thinking_pricing" in custom

    # Check nested fields
    assert "input" in custom["pricing"]
    assert "output" in custom["pricing"]
    assert "write" in custom["cache_pricing"]
    assert "read" in custom["cache_pricing"]
    assert "thinking" in custom["thinking_pricing"]


def test_custom_model_with_special_characters():
    """Test that custom models with special characters work."""
    special_names = [
        "claude-3.5-sonnet-experimental",
        "model-2024-01-01",
        "test_model_v1.2.3",
    ]

    for name in special_names:
        model = get_model(name)
        assert model["title"] == name
        # Should still have Opus pricing
        opus = get_model("opus")
        assert model["pricing"] == opus["pricing"]
