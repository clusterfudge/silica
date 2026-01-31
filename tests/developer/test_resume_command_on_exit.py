"""Tests for the resume command output on CLI exit."""

import sys
from io import StringIO


class TestPrintResumeCommand:
    """Tests for the _print_resume_command function."""

    def test_basic_session_id(self):
        """Test that basic session ID is included in output."""
        from silica.developer.hdev import _print_resume_command

        # Capture stderr
        old_stderr = sys.stderr
        sys.stderr = StringIO()

        try:
            _print_resume_command("test-session-123")
            output = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        assert "silica --session-id test-session-123" in output
        assert "# To resume this session:" in output

    def test_with_non_default_persona(self):
        """Test that persona flag is included for non-default personas."""
        from silica.developer.hdev import _print_resume_command

        old_stderr = sys.stderr
        sys.stderr = StringIO()

        try:
            _print_resume_command("test-session-456", "my_custom_persona")
            output = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        assert (
            "silica --session-id test-session-456 --persona my_custom_persona" in output
        )

    def test_default_persona_not_included(self):
        """Test that --persona flag is NOT included for 'default' persona."""
        from silica.developer.hdev import _print_resume_command

        old_stderr = sys.stderr
        sys.stderr = StringIO()

        try:
            _print_resume_command("test-session-789", "default")
            output = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        assert "--persona" not in output
        assert "silica --session-id test-session-789" in output

    def test_none_persona_not_included(self):
        """Test that --persona flag is NOT included when persona is None."""
        from silica.developer.hdev import _print_resume_command

        old_stderr = sys.stderr
        sys.stderr = StringIO()

        try:
            _print_resume_command("test-session-000", None)
            output = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        assert "--persona" not in output
        assert "silica --session-id test-session-000" in output

    def test_output_goes_to_stderr(self):
        """Test that output goes to stderr, not stdout."""
        from silica.developer.hdev import _print_resume_command

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()

        try:
            _print_resume_command("test-session", "persona")
            stdout_output = sys.stdout.getvalue()
            stderr_output = sys.stderr.getvalue()
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        # Should have content in stderr
        assert "silica" in stderr_output
        # Should have nothing in stdout
        assert stdout_output == ""

    def test_ansi_codes_present(self):
        """Test that ANSI color codes are present for terminal formatting."""
        from silica.developer.hdev import _print_resume_command

        old_stderr = sys.stderr
        sys.stderr = StringIO()

        try:
            _print_resume_command("test-session")
            output = sys.stderr.getvalue()
        finally:
            sys.stderr = old_stderr

        # Check for ANSI escape codes (dim text and cyan)
        assert "\033[2m" in output  # dim
        assert "\033[36m" in output  # cyan
        assert "\033[0m" in output  # reset


class TestAtexitRegistration:
    """Tests for atexit handler registration."""

    def test_import_atexit_in_cyclopts_main(self):
        """Test that atexit is importable and usable."""
        import atexit
        from silica.developer.hdev import _print_resume_command

        # This should not raise
        # Note: We don't actually register here to avoid polluting the test environment
        # Just verify the function signature is compatible
        assert callable(_print_resume_command)
        assert callable(atexit.register)
