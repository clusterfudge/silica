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
        """Persona should describe coordinator role."""
        assert "Coordinator" in PERSONA
        assert "orchestrat" in PERSONA.lower()
        assert "worker" in PERSONA.lower()

    def test_tool_groups_limited(self):
        """Coordinator should have limited tool groups."""
        assert "coordination" in TOOL_GROUPS
        assert "memory" in TOOL_GROUPS
        # Should NOT have direct file/shell access
        assert "shell" not in TOOL_GROUPS
        assert "files" not in TOOL_GROUPS

    def test_model_specified(self):
        """Model should be specified."""
        assert MODEL is not None
        # Coordinator doesn't need the most expensive model
        assert MODEL in ("sonnet", "haiku", "opus")

    def test_persona_mentions_key_tools(self):
        """Persona should mention key coordination tools."""
        assert "spawn_agent" in PERSONA
        assert "message_agent" in PERSONA
        assert "poll_messages" in PERSONA
        assert "list_agents" in PERSONA
        assert "grant_permission" in PERSONA

    def test_persona_explains_workflow(self):
        """Persona should explain coordination workflow."""
        # Key workflow concepts
        assert "decompos" in PERSONA.lower()  # Task decomposition
        assert "monitor" in PERSONA.lower()  # Monitoring
        assert "delegate" in PERSONA.lower()  # Delegation
