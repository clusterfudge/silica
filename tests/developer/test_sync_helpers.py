"""Tests for sync CLI helpers."""

import io
import re

import pytest
from rich.console import Console

from silica.developer.cli.sync_helpers import display_sync_plan, _format_size
from silica.developer.memory.sync import SyncPlan, SyncOperationDetail


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi_escape.sub("", text)


@pytest.fixture
def console():
    """Create a console that captures output."""
    output = io.StringIO()
    return Console(file=output, force_terminal=True, width=120), output


def test_display_empty_plan(console):
    """Test displaying an empty sync plan."""
    console_obj, output = console
    plan = SyncPlan()

    display_sync_plan(console_obj, plan)

    result = strip_ansi(output.getvalue())
    assert "in sync" in result.lower()
    assert "No operations" in result


def test_display_plan_with_uploads(console):
    """Test displaying a plan with uploads."""
    console_obj, output = console
    plan = SyncPlan(
        upload=[
            SyncOperationDetail(
                type="upload", path="test.md", reason="New local file", local_size=1024
            ),
            SyncOperationDetail(
                type="upload", path="notes.md", reason="Local file modified"
            ),
        ]
    )

    display_sync_plan(console_obj, plan)

    result = strip_ansi(output.getvalue())
    assert "Uploads" in result
    assert "2" in result
    assert "test.md" in result
    assert "notes.md" in result


def test_display_plan_with_downloads(console):
    """Test displaying a plan with downloads."""
    console_obj, output = console
    plan = SyncPlan(
        download=[
            SyncOperationDetail(
                type="download",
                path="remote.md",
                reason="New remote file",
                remote_size=2048,
            ),
        ]
    )

    display_sync_plan(console_obj, plan)

    result = strip_ansi(output.getvalue())
    assert "Downloads" in result
    assert "1" in result
    assert "remote.md" in result


def test_display_plan_with_deletes(console):
    """Test displaying a plan with delete operations."""
    console_obj, output = console
    plan = SyncPlan(
        delete_local=[
            SyncOperationDetail(
                type="delete_local",
                path="old-local.md",
                reason="Explicit remote deletion",
            ),
        ],
        delete_remote=[
            SyncOperationDetail(
                type="delete_remote", path="old-remote.md", reason="Deleted locally"
            ),
        ],
    )

    display_sync_plan(console_obj, plan)

    result = strip_ansi(output.getvalue())
    assert "Delete local" in result
    assert "Delete remote" in result
    assert "old-local.md" in result
    assert "old-remote.md" in result


def test_display_plan_with_conflicts(console):
    """Test displaying a plan with conflicts."""
    console_obj, output = console
    plan = SyncPlan(
        conflicts=[
            SyncOperationDetail(
                type="conflict",
                path="conflict.md",
                reason="Both local and remote modified since last sync",
            ),
        ]
    )

    display_sync_plan(console_obj, plan)

    result = strip_ansi(output.getvalue())
    assert "Conflicts" in result
    assert "conflict.md" in result
    assert "Both local and remote modified" in result
    assert "LLM merge" in result


def test_display_plan_with_context(console):
    """Test displaying a plan with context."""
    console_obj, output = console
    plan = SyncPlan(
        upload=[SyncOperationDetail(type="upload", path="test.md", reason="New file")]
    )

    display_sync_plan(console_obj, plan, context="persona 'default'")

    result = strip_ansi(output.getvalue())
    assert "persona 'default'" in result


def test_display_plan_many_operations(console):
    """Test displaying a plan with more than 10 operations."""
    console_obj, output = console

    # Create 15 uploads
    uploads = [
        SyncOperationDetail(type="upload", path=f"file{i}.md", reason="New file")
        for i in range(15)
    ]
    plan = SyncPlan(upload=uploads)

    display_sync_plan(console_obj, plan)

    result = strip_ansi(output.getvalue())
    assert "file0.md" in result
    assert "file9.md" in result  # First 10 should be shown
    assert "5 more" in result  # Remaining should be indicated


def test_format_size_bytes():
    """Test formatting bytes."""
    assert _format_size(100) == "100 B"
    assert _format_size(0) == "0 B"


def test_format_size_kilobytes():
    """Test formatting kilobytes."""
    result = _format_size(1024)
    assert "KB" in result
    assert "1.0" in result


def test_format_size_megabytes():
    """Test formatting megabytes."""
    result = _format_size(1024 * 1024)
    assert "MB" in result
    assert "1.0" in result


def test_format_size_gigabytes():
    """Test formatting gigabytes."""
    result = _format_size(1024 * 1024 * 1024)
    assert "GB" in result
    assert "1.0" in result


def test_display_plan_shows_size_info(console):
    """Test that size info is shown for operations with size."""
    console_obj, output = console
    plan = SyncPlan(
        upload=[
            SyncOperationDetail(
                type="upload",
                path="big.md",
                reason="New file",
                local_size=1024 * 1024,  # 1MB
            )
        ],
        download=[
            SyncOperationDetail(
                type="download",
                path="small.md",
                reason="New remote file",
                remote_size=512,  # 512 B
            )
        ],
    )

    display_sync_plan(console_obj, plan)

    result = strip_ansi(output.getvalue())
    assert "MB" in result or "1.0" in result
    assert "512 B" in result


def test_display_full_plan(console):
    """Test displaying a comprehensive plan with all operation types."""
    console_obj, output = console
    plan = SyncPlan(
        upload=[
            SyncOperationDetail(type="upload", path="upload.md", reason="New file")
        ],
        download=[
            SyncOperationDetail(
                type="download", path="download.md", reason="New remote"
            )
        ],
        delete_local=[
            SyncOperationDetail(
                type="delete_local", path="del-local.md", reason="Remote deleted"
            )
        ],
        delete_remote=[
            SyncOperationDetail(
                type="delete_remote", path="del-remote.md", reason="Local deleted"
            )
        ],
        conflicts=[
            SyncOperationDetail(
                type="conflict", path="conflict.md", reason="Both changed"
            )
        ],
    )

    display_sync_plan(console_obj, plan, context="test")

    result = strip_ansi(output.getvalue())
    # Should have summary
    assert "Uploads" in result
    assert "Downloads" in result
    assert "Delete local" in result
    assert "Delete remote" in result
    assert "Conflicts" in result
    # Should show total (conflicts are not counted in total_operations)
    assert "Total operations" in result
    assert "4" in result  # 4 operations (conflicts excluded from total)
