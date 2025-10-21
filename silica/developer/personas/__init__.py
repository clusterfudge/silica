"""
Personas for the developer agent.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Import specific personas
from .basic_agent import PERSONA as BASIC_AGENT  # noqa: E402
from .deep_research_agent import PERSONA as DEEP_RESEARCH_AGENT
from .coding_agent import PERSONA as AUTONOMOUS_ENGINEER  # noqa: E402
from ..utils import wrap_text_as_content_block

DEFAULT_PERSONA_NAME = "default"

_personas = {
    "basic_agent": BASIC_AGENT,
    "deep_research_agent": DEEP_RESEARCH_AGENT,
    "autonomous_engineer": AUTONOMOUS_ENGINEER,
}

_persona_descriptions = {
    "basic_agent": "General purpose assistant with access to various tools",
    "deep_research_agent": "Research and comprehensive document creation specialist",
    "autonomous_engineer": "Autonomous software engineering and development agent",
}

_PERSONAS_BASE_DIRECTORY: Path = Path("~/.silica/personas").expanduser()


@dataclass
class Persona(object):
    system_block: dict[str, Any] | None
    base_directory: Path


def for_name(name: str | None) -> Persona:
    persona_prompt = _personas.get(name.lower(), None)

    system_block: dict[str, Any] | None = (
        wrap_text_as_content_block(persona_prompt) if persona_prompt else None
    )
    name: str = name or DEFAULT_PERSONA_NAME
    return Persona(
        system_block=system_block, base_directory=_PERSONAS_BASE_DIRECTORY / name
    )


def names():
    return list(_personas.keys())


def get_builtin_descriptions() -> dict[str, str]:
    """Get descriptions of all built-in personas.

    Returns:
        Dictionary mapping persona names to their descriptions
    """
    return _persona_descriptions.copy()


def get_builtin_prompt(name: str) -> str:
    """Get the prompt text for a built-in persona.

    Args:
        name: Name of the built-in persona

    Returns:
        The persona prompt text, or empty string if not found
    """
    return _personas.get(name, "")


def create_persona_directory(name: str, base_prompt: str = "") -> Path:
    """Create a new persona directory with persona.md file.

    Args:
        name: Name of the persona
        base_prompt: Optional prompt text to write to persona.md

    Returns:
        Path to the created persona directory
    """
    persona_dir = _PERSONAS_BASE_DIRECTORY / name
    persona_dir.mkdir(parents=True, exist_ok=True)

    persona_file = persona_dir / "persona.md"
    if not persona_file.exists():
        with open(persona_file, "w") as f:
            f.write(base_prompt)

    return persona_dir


def persona_exists(name: str) -> bool:
    """Check if a persona directory and persona.md file exist.

    Args:
        name: Name of the persona

    Returns:
        True if both the directory and persona.md file exist
    """
    persona_dir = _PERSONAS_BASE_DIRECTORY / name
    persona_file = persona_dir / "persona.md"
    return persona_dir.exists() and persona_file.exists()


# List of all available personas
__all__ = [
    for_name,
    get_builtin_descriptions,
    get_builtin_prompt,
    create_persona_directory,
    persona_exists,
]
