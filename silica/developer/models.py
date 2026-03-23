from typing import TypedDict


class ModelSpec(TypedDict):
    title: str
    pricing: dict[str, float]
    cache_pricing: dict[str, float]
    max_tokens: int
    max_output_tokens: int  # Hard limit on total output (thinking + completion)
    context_window: int
    thinking_support: bool
    thinking_pricing: dict[str, float]


MODEL_MAP: dict[str, ModelSpec] = {
    "opus": {
        "title": "claude-opus-4-6",
        "pricing": {"input": 5.00, "output": 25.00},
        "cache_pricing": {"write": 6.25, "read": 0.50},
        "max_tokens": 8192,
        "max_output_tokens": 128000,  # 128k total output window
        "context_window": 200000,  # 200k tokens context window
        "thinking_support": True,
        "thinking_pricing": {"thinking": 25.00},  # Same as output tokens
    },
    "sonnet": {
        "title": "claude-sonnet-4-5-20250929",
        "pricing": {"input": 3.00, "output": 15.00},
        "cache_pricing": {"write": 3.75, "read": 0.30},
        "max_tokens": 8192,
        "max_output_tokens": 64000,  # 64k total output window
        "context_window": 200000,  # 200k tokens context window
        "thinking_support": True,
        "thinking_pricing": {"thinking": 15.00},  # Same as output tokens
    },
    "haiku": {
        "title": "claude-haiku-4-5-20251001",
        "pricing": {"input": 1.00, "output": 5.00},
        "cache_pricing": {"write": 1.25, "read": 0.10},
        "max_tokens": 8192,
        "max_output_tokens": 64000,  # 64k total output window
        "context_window": 200000,  # 200k tokens context window
        "thinking_support": True,
        "thinking_pricing": {"thinking": 5.00},  # Same as output tokens
    },
    # Legacy model aliases for backwards compatibility
    "sonnet-3.5": {
        "title": "claude-3-5-sonnet-20241022",
        "pricing": {"input": 3.00, "output": 15.00},
        "cache_pricing": {"write": 3.75, "read": 0.30},
        "max_tokens": 8192,
        "max_output_tokens": 8192,  # No extended output for legacy models
        "context_window": 200000,
        "thinking_support": False,
        "thinking_pricing": {"thinking": 0.00},  # Not supported
    },
    "sonnet-3.7": {
        "title": "claude-3-7-sonnet-20250219",
        "pricing": {"input": 3.00, "output": 15.00},
        "cache_pricing": {"write": 3.75, "read": 0.30},
        "max_tokens": 8192,
        "max_output_tokens": 64000,  # 64k total output window
        "context_window": 200000,
        "thinking_support": True,
        "thinking_pricing": {"thinking": 15.00},  # Same as output tokens
    },
}

# pivot on model ids as well
_KEY_MAP = {model.get("title"): model for model in MODEL_MAP.values()}

_ALL_ALIASES = _KEY_MAP | MODEL_MAP


def model_names() -> list[str]:
    return list(_ALL_ALIASES.keys())


def get_model(
    model_name: str,
    context_window: int | None = None,
    max_output_tokens: int | None = None,
) -> ModelSpec:
    """Look up a model by name or alias.

    Args:
        model_name: Short name (e.g. "opus") or full model ID
        context_window: Override context window from API (max_input_tokens)
        max_output_tokens: Override max output tokens from API (max_tokens)
    """
    # Try exact match first
    if model_name in _ALL_ALIASES:
        spec = _ALL_ALIASES[model_name]
        if context_window is not None or max_output_tokens is not None:
            spec = spec.copy()
            if context_window is not None:
                spec["context_window"] = context_window
            if max_output_tokens is not None:
                spec["max_output_tokens"] = max_output_tokens
        return spec

    # Try case-insensitive match
    model_name_lower = model_name.lower()
    for alias, spec in _ALL_ALIASES.items():
        if alias.lower() == model_name_lower:
            if context_window is not None or max_output_tokens is not None:
                spec = spec.copy()
                if context_window is not None:
                    spec["context_window"] = context_window
                if max_output_tokens is not None:
                    spec["max_output_tokens"] = max_output_tokens
            return spec

    # If model not found, use Opus ModelSpec but with the custom model name
    # This allows using any model that follows the Anthropic API
    opus_spec = MODEL_MAP["opus"].copy()
    opus_spec["title"] = model_name
    opus_spec["max_output_tokens"] = max_output_tokens or 64000
    opus_spec["context_window"] = context_window or 200000
    return opus_spec
