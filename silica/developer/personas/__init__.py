"""
Personas for the developer agent.
"""

# Import specific personas
from .basic_agent import PERSONA as BASIC_AGENT  # noqa: E402
from .deep_research_agent import PERSONA as DEEP_RESEARCH_AGENT
from .coding_agent import PERSONA as AUTONOMOUS_ENGINEER  # noqa: E402

_personas = {
    "basic_agent": BASIC_AGENT,
    "deep_research_agent": DEEP_RESEARCH_AGENT,
    "autonomous_engineer": AUTONOMOUS_ENGINEER,
}


def for_name(name: str) -> str | None:
    return _personas.get(name.lower(), None)


def names():
    return list(_personas.keys())


# List of all available personas
__all__ = [for_name]
