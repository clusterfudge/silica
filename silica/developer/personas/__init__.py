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


# List of all available personas
__all__ = [for_name]
