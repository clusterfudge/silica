"""Tests for worker persona."""

from silica.developer.personas.worker_agent import (
    PERSONA,
    TOOL_GROUPS,
    MODEL,
)


class TestWorkerPersona:
    """Test worker persona definition."""

    def test_persona_defined(self):
        """Persona should be defined and non-empty."""
        assert PERSONA is not None
        assert len(PERSONA) > 100

    def test_persona_describes_role(self):
        """Persona should describe worker role."""
        assert "Worker" in PERSONA
        assert "executor" in PERSONA.lower()
        assert "task" in PERSONA.lower()

    def test_tool_groups_comprehensive(self):
        """Worker should have comprehensive tool access."""
        assert "worker_coordination" in TOOL_GROUPS
        assert "files" in TOOL_GROUPS
        assert "shell" in TOOL_GROUPS
        assert "web" in TOOL_GROUPS
        assert "memory" in TOOL_GROUPS

    def test_model_is_opus(self):
        """Model should be opus for best autonomous execution."""
        assert MODEL == "opus"

    def test_persona_mentions_key_tools(self):
        """Persona should mention key coordination tools."""
        assert "check_inbox" in PERSONA
        assert "send_to_coordinator" in PERSONA
        assert "broadcast_status" in PERSONA
        assert "mark_idle" in PERSONA
        assert "request_permission" in PERSONA

    def test_persona_explains_workflow(self):
        """Persona should explain worker workflow."""
        # Key workflow concepts
        assert "ack" in PERSONA.lower()  # Acknowledge tasks
        assert "progress" in PERSONA.lower()  # Report progress
        assert "result" in PERSONA.lower()  # Send results
        assert "idle" in PERSONA.lower()  # Signal idle

    def test_persona_covers_error_handling(self):
        """Persona should cover error handling."""
        assert "error" in PERSONA.lower()
        assert "failed" in PERSONA.lower()
