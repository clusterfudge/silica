"""Tests for Procfile UV cache clearing and upgrade functionality."""

from pathlib import Path


class TestProcfileUpgrade:
    """Test that Procfile contains proper UV cache clearing and upgrade commands."""

    def test_procfile_contains_cache_clean(self):
        """Test that Procfile clears UV cache before starting antennae."""
        procfile_path = (
            Path(__file__).parent.parent.parent
            / "silica"
            / "remote"
            / "utils"
            / "templates"
            / "Procfile"
        )

        assert procfile_path.exists(), f"Procfile not found at {procfile_path}"

        with open(procfile_path, "r") as f:
            content = f.read()

        # Check that the Procfile contains the cache clean command
        assert "uv cache clean" in content, (
            "Procfile should contain 'uv cache clean' command"
        )

        # Check that it specifically cleans pysilica
        assert "uv cache clean pysilica" in content, (
            "Procfile should clean pysilica cache specifically"
        )

    def test_procfile_contains_sync_upgrade(self):
        """Test that Procfile syncs with upgrade flag before starting antennae."""
        procfile_path = (
            Path(__file__).parent.parent.parent
            / "silica"
            / "remote"
            / "utils"
            / "templates"
            / "Procfile"
        )

        with open(procfile_path, "r") as f:
            content = f.read()

        # Check that the Procfile contains the sync --upgrade command
        assert "uv sync --upgrade" in content, (
            "Procfile should contain 'uv sync --upgrade' command"
        )

    def test_procfile_command_order(self):
        """Test that cache clean and sync happen before antennae starts."""
        procfile_path = (
            Path(__file__).parent.parent.parent
            / "silica"
            / "remote"
            / "utils"
            / "templates"
            / "Procfile"
        )

        with open(procfile_path, "r") as f:
            content = f.read()

        # Find the web process line
        web_lines = [line for line in content.split("\n") if line.startswith("web:")]
        assert len(web_lines) == 1, "Should have exactly one web process definition"

        web_command = web_lines[0]

        # Check that cache clean comes before sync
        cache_clean_pos = web_command.find("uv cache clean")
        sync_pos = web_command.find("uv sync --upgrade")
        antennae_pos = web_command.find("uv run silica remote antennae")

        assert cache_clean_pos != -1, "Cache clean command should be present"
        assert sync_pos != -1, "Sync upgrade command should be present"
        assert antennae_pos != -1, "Antennae start command should be present"

        # Verify order: cache clean -> sync -> run
        assert cache_clean_pos < sync_pos, (
            "Cache clean should come before sync --upgrade"
        )
        assert sync_pos < antennae_pos, (
            "Sync --upgrade should come before starting antennae"
        )

    def test_procfile_uses_shell_chaining(self):
        """Test that Procfile uses && to chain commands properly."""
        procfile_path = (
            Path(__file__).parent.parent.parent
            / "silica"
            / "remote"
            / "utils"
            / "templates"
            / "Procfile"
        )

        with open(procfile_path, "r") as f:
            content = f.read()

        web_lines = [line for line in content.split("\n") if line.startswith("web:")]
        web_command = web_lines[0]

        # Count the number of && operators (should be 2: cache && sync && run)
        assert web_command.count("&&") >= 2, "Should chain commands with && operators"

        # Verify it's the specific pattern we expect
        expected_pattern = (
            "uv cache clean pysilica && uv sync --upgrade && uv run silica"
        )
        assert expected_pattern in web_command, (
            f"Procfile should contain the pattern: {expected_pattern}"
        )
