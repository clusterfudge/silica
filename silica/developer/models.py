from typing import TypedDict


class ModelSpec(TypedDict):
    title: str
    pricing: dict[str, float]
    cache_pricing: dict[str, float]
    max_tokens: int
    context_window: int


MODEL_MAP: dict[str, ModelSpec] = {
    "opus": {
        "title": "claude-opus-4-20250514",
        "pricing": {"input": 15.00, "output": 18.75},
        "cache_pricing": {"write": 3.75, "read": 0.30},
        "max_tokens": 8192,
        "context_window": 200000,  # 200k tokens context window
    },
    "sonnet": {
        "title": "claude-sonnet-4-20250514",
        "pricing": {"input": 3.00, "output": 15.00},
        "cache_pricing": {"write": 3.75, "read": 0.30},
        "max_tokens": 8192,
        "context_window": 200000,  # 200k tokens context window
    },
    "haiku": {
        "title": "claude-3-5-haiku-20241022",
        "pricing": {"input": 0.80, "output": 4.00},
        "cache_pricing": {"write": 1.00, "read": 0.08},
        "max_tokens": 8192,
        "context_window": 100000,  # 100k tokens context window
    },
    # Legacy model aliases for backwards compatibility
    "sonnet-3.5": {
        "title": "claude-3-5-sonnet-20241022",
        "pricing": {"input": 3.00, "output": 15.00},
        "cache_pricing": {"write": 3.75, "read": 0.30},
        "max_tokens": 8192,
        "context_window": 200000,
    },
    "sonnet-3.7": {
        "title": "claude-3-7-sonnet-20250219",
        "pricing": {"input": 3.00, "output": 15.00},
        "cache_pricing": {"write": 3.75, "read": 0.30},
        "max_tokens": 8192,
        "context_window": 200000,
    },
}

# pivot on model ids as well
_KEY_MAP = {model.get("title"): model for model in MODEL_MAP.values()}

_ALL_ALIASES = _KEY_MAP | MODEL_MAP


def model_names() -> list[str]:
    return list(_ALL_ALIASES.keys())


def get_model(model_name: str) -> ModelSpec:
    # Try exact match first
    if model_name in _ALL_ALIASES:
        return _ALL_ALIASES[model_name]

    # Try case-insensitive match
    model_name_lower = model_name.lower()
    for alias, spec in _ALL_ALIASES.items():
        if alias.lower() == model_name_lower:
            return spec

    raise ValueError(f"{model_name} is not a valid model name")
