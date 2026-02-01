"""Tests for remote coordinator mode in silica remote tell."""

from silica.remote.cli.commands.tell import (
    COORDINATOR_PREFIX,
    _wrap_coordinator_message,
)


class TestCoordinatorPrefix:
    """Test coordinator mode detection."""

    def test_prefix_defined(self):
        """Coordinator prefix should be defined."""
        assert COORDINATOR_PREFIX == "coordinate:"

    def test_prefix_detection(self):
        """Messages starting with prefix should be detected."""
        message = "coordinate: build a web scraper"
        assert message.lower().startswith(COORDINATOR_PREFIX)

    def test_non_coordinator_message(self):
        """Regular messages should not match prefix."""
        message = "implement feature X"
        assert not message.lower().startswith(COORDINATOR_PREFIX)


class TestWrapCoordinatorMessage:
    """Test coordinator message wrapping."""

    def test_wrap_includes_goal(self):
        """Wrapped message should include the goal."""
        goal = "build a web scraper with 3 workers"
        wrapped = _wrap_coordinator_message(goal)
        assert goal in wrapped

    def test_wrap_includes_coordinator_mode(self):
        """Wrapped message should mention coordinator mode."""
        wrapped = _wrap_coordinator_message("test goal")
        assert "Coordinator Mode" in wrapped

    def test_wrap_mentions_spawn_agent(self):
        """Wrapped message should mention spawn_agent tool."""
        wrapped = _wrap_coordinator_message("test goal")
        assert "spawn_agent" in wrapped

    def test_wrap_mentions_poll_messages(self):
        """Wrapped message should mention poll_messages tool."""
        wrapped = _wrap_coordinator_message("test goal")
        assert "poll_messages" in wrapped

    def test_wrap_mentions_permissions(self):
        """Wrapped message should mention permission handling."""
        wrapped = _wrap_coordinator_message("test goal")
        assert "permission" in wrapped.lower()

    def test_wrap_mentions_workers(self):
        """Wrapped message should explain worker concept."""
        wrapped = _wrap_coordinator_message("test goal")
        assert "worker" in wrapped.lower()
