"""ID generation utilities using heare.ids."""

from heare import ids
from typing import Callable


def generate_prompt_id() -> str:
    """Generate an ID for a prompt."""
    return ids.new("prompt")


def generate_job_id() -> str:
    """Generate an ID for a scheduled job."""
    return ids.new("job")


def generate_execution_id() -> str:
    """Generate an ID for a job execution."""
    return ids.new("exec")


def generate_generic_id() -> str:
    """Generate a generic ID with 'item' prefix."""
    return ids.new("item")


# Default ID generator - can be used for any model
generate: Callable[[], str] = generate_generic_id
