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
    persona_file = base_directory / "memory" / "persona.md"

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

    persona_file = persona_dir / "memory" / "persona.md"
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


def get_or_create(name: str | None, interactive: bool = True) -> Persona:
    """Get an existing persona or create a new one interactively.

    Args:
        name: Name of the persona (None uses DEFAULT_PERSONA_NAME)
        interactive: If True, prompt user to create persona if it doesn't exist

    Returns:
        Persona object with system_block and base_directory

    Raises:
        ValueError: If persona doesn't exist and interactive is False
    """
    from rich.console import Console
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.validation import Validator, ValidationError
    from prompt_toolkit import ANSI

    name = name or DEFAULT_PERSONA_NAME

    # If persona exists, just load and return it
    if persona_exists(name):
        return for_name(name)

    # Persona doesn't exist
    if not interactive:
        raise ValueError(
            f"Persona '{name}' does not exist and interactive mode is disabled"
        )

    # Interactive creation
    console = Console()
    console.print(f"\n[yellow]The persona '{name}' doesn't exist yet.[/yellow]")

    # Ask if they want to use a template
    try:
        use_template = (
            console.input(
                "[bold cyan]Would you like to base it on a built-in persona template? [y/n]: [/bold cyan]"
            )
            .strip()
            .lower()
        )
    except (KeyboardInterrupt, EOFError):
        console.print("\n[red]Cancelled[/red]")
        raise KeyboardInterrupt("Persona creation cancelled")

    if use_template == "y":
        # Show available templates
        console.print("\n[bold cyan]Available persona templates:[/bold cyan]")
        builtin_descriptions = get_builtin_descriptions()
        builtin_names = list(builtin_descriptions.keys())

        for idx, builtin_name in enumerate(builtin_names, 1):
            description = builtin_descriptions[builtin_name]
            console.print(f"  [cyan]{idx}.[/cyan] {builtin_name} - {description}")
        console.print(
            f"  [cyan]{len(builtin_names) + 1}.[/cyan] blank - Start with no template"
        )

        # Get user's choice
        class ChoiceValidator(Validator):
            def validate(self, document):
                text = document.text.strip()
                if not text:
                    raise ValidationError(message="Please enter a choice")
                try:
                    choice = int(text)
                    if choice < 1 or choice > len(builtin_names) + 1:
                        raise ValidationError(
                            message=f"Please enter a number between 1 and {len(builtin_names) + 1}"
                        )
                except ValueError:
                    raise ValidationError(message="Please enter a valid number")

        try:
            choice_str = pt_prompt(
                ANSI(f"\n\033[1;36mChoice [1-{len(builtin_names) + 1}]: \033[0m"),
                validator=ChoiceValidator(),
            ).strip()
            choice = int(choice_str)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[red]Cancelled[/red]")
            raise KeyboardInterrupt("Persona creation cancelled")

        # Get the selected template
        if choice <= len(builtin_names):
            selected_name = builtin_names[choice - 1]
            console.print(
                f"\n[green]Creating persona '{name}' based on '{selected_name}'[/green]"
            )
            # For template-based personas, write the built-in prompt to persona.md
            persona_dir = _PERSONAS_BASE_DIRECTORY / name
            persona_dir.mkdir(parents=True, exist_ok=True)

            # Get the built-in prompt and write it to persona.md
            base_prompt = get_builtin_prompt(selected_name)
            persona_file = persona_dir / "memory" / "persona.md"
            with open(persona_file, "w") as f:
                f.write(base_prompt)

            console.print(f"[green]✓ Created persona directory: {persona_dir}[/green]")
            console.print(f"[green]✓ Created persona file: {persona_file}[/green]")
            console.print(f"[dim]Edit {persona_file} to customize the persona.[/dim]")
        else:
            console.print(f"\n[green]Creating blank persona '{name}'[/green]")
            # For blank personas, create directory with empty persona.md
            persona_dir = _PERSONAS_BASE_DIRECTORY / name
            persona_dir.mkdir(parents=True, exist_ok=True)
            persona_file = persona_dir / "memory" / "persona.md"
            with open(persona_file, "w") as f:
                f.write("")

            console.print(f"[green]✓ Created persona directory: {persona_dir}[/green]")
            console.print(
                f"[green]✓ Created empty persona file: {persona_file}[/green]"
            )
            console.print(
                f"[dim]Edit {persona_file} to add your custom persona prompt.[/dim]"
            )
    else:
        console.print(f"\n[green]Creating blank persona '{name}'[/green]")
        # User declined template - create blank persona
        persona_dir = _PERSONAS_BASE_DIRECTORY / name
        persona_dir.mkdir(parents=True, exist_ok=True)
        persona_file = persona_dir / "memory" / "persona.md"
        with open(persona_file, "w") as f:
            f.write("")

        console.print(f"[green]✓ Created persona directory: {persona_dir}[/green]")
        console.print(f"[green]✓ Created empty persona file: {persona_file}[/green]")
        console.print(
            f"[dim]Edit {persona_file} to add your custom persona prompt.[/dim]"
        )

    console.print()  # Empty line for spacing

    # Now load and return the newly created persona
    return for_name(name)


# List of all available personas
__all__ = [
    for_name,
    get_or_create,
    get_builtin_descriptions,
    get_builtin_prompt,
    create_persona_directory,
    persona_exists,
]
