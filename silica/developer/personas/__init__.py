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
    """Get a persona by name, loading from persona.md if it exists.

    Args:
        name: Name of the persona (None uses DEFAULT_PERSONA_NAME)

    Returns:
        Persona object with system_block and base_directory

    Priority:
        1. Load from persona.md if file exists
        2. Use built-in template if available
        3. Use None (no custom system prompt)
    """
    name = name or DEFAULT_PERSONA_NAME
    base_directory = _PERSONAS_BASE_DIRECTORY / name
    persona_file = base_directory / "persona.md"

    # Try to load from persona.md first
    if persona_file.exists():
        try:
            with open(persona_file, "r") as f:
                persona_content = f.read().strip()
            # Only create system_block if file has content
            system_block = (
                wrap_text_as_content_block(persona_content) if persona_content else None
            )
        except (IOError, OSError):
            # Fall back to built-in if file read fails
            persona_prompt = _personas.get(name.lower(), None)
            system_block = (
                wrap_text_as_content_block(persona_prompt) if persona_prompt else None
            )
    else:
        # No persona.md - use built-in if available
        persona_prompt = _personas.get(name.lower(), None)
        system_block = (
            wrap_text_as_content_block(persona_prompt) if persona_prompt else None
        )

    return Persona(system_block=system_block, base_directory=base_directory)


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
    """Check if a persona directory exists (regardless of persona.md).

    Args:
        name: Name of the persona

    Returns:
        True if the persona directory exists

    Note:
        A persona is considered to exist if its directory exists, even without
        persona.md. The system will use built-in templates or custom persona.md
        as appropriate via for_name().
    """
    persona_dir = _PERSONAS_BASE_DIRECTORY / name
    return persona_dir.exists()


# List of all available personas
__all__ = [
    for_name,
    get_builtin_descriptions,
    get_builtin_prompt,
    create_persona_directory,
    persona_exists,
]
