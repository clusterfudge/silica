"""Tests for coordinator persona."""

from silica.developer.personas.coordinator_agent import (
    PERSONA,
    TOOL_GROUPS,
    MODEL,
)


class TestCoordinatorPersona:
    """Test coordinator persona definition."""

    def test_persona_defined(self):
        """Persona should be defined and non-empty."""
        assert PERSONA is not None
        assert len(PERSONA) > 100

    def test_persona_describes_role(self):
        """Persona should describe coordination / delegation capabilities."""
        lower = PERSONA.lower()
        assert "worker" in lower
        assert "delegate" in lower or "spawn" in lower
        assert "task" in lower

    def test_tool_groups_limited(self):
        """Coordinator should have limited tool groups."""
        assert "coordination" in TOOL_GROUPS
        assert "memory" in TOOL_GROUPS
        # Should NOT have direct file/shell access
        assert "shell" not in TOOL_GROUPS
        assert "files" not in TOOL_GROUPS

    def test_model_is_opus(self):
        """Coordinator should use the strongest model for high-leverage decisions."""
        assert MODEL == "opus"

    def test_persona_covers_key_concepts(self):
        """Persona should cover coordination concepts without listing tools."""
        lower = PERSONA.lower()
        # Core concepts the persona should address
        assert "spawn" in lower  # Creating workers
        assert "message" in lower or "assign" in lower  # Communicating tasks
        assert "poll" in lower  # Checking for updates
        assert "permission" in lower  # Permission handling

    def test_persona_covers_workflow(self):
        """Persona should explain when to delegate vs handle directly."""
        lower = PERSONA.lower()
        assert "parallel" in lower  # Parallel execution
        assert "simple" in lower or "directly" in lower  # Handle simple things directly

    def test_persona_session_awareness(self):
        """Persona should handle new vs resumed sessions differently."""
        lower = PERSONA.lower()
        assert "fresh session" in lower or "new" in lower
        assert "resumed" in lower or "resume" in lower
