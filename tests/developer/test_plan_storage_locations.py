"""Tests for plan storage location features (local vs global)."""

import pytest

from silica.developer.plans import (
    PlanManager,
    get_local_plans_dir,
    LOCATION_LOCAL,
    LOCATION_GLOBAL,
)


@pytest.fixture
def temp_dirs(tmp_path):
    """Create temp directories for testing."""
    persona_dir = tmp_path / "persona"
    project_dir = tmp_path / "project"
    persona_dir.mkdir()
    project_dir.mkdir()
    # Initialize git in project
    (project_dir / ".git").mkdir()
    return {"persona": persona_dir, "project": project_dir}


class TestGetLocalPlansDir:
    """Tests for local plans directory resolution."""

    def test_prefers_silica_if_exists(self, tmp_path):
        """Should use .silica/plans if .silica exists."""
        (tmp_path / ".silica").mkdir()
        result = get_local_plans_dir(tmp_path)
        assert result == tmp_path / ".silica" / "plans"

    def test_prefers_agent_if_exists(self, tmp_path):
        """Should use .agent/plans if .agent exists but not .silica."""
        (tmp_path / ".agent").mkdir()
        result = get_local_plans_dir(tmp_path)
        assert result == tmp_path / ".agent" / "plans"

    def test_silica_over_agent_when_both_exist(self, tmp_path):
        """Should prefer .silica if both exist."""
        (tmp_path / ".silica" / "plans").mkdir(parents=True)
        (tmp_path / ".agent" / "plans").mkdir(parents=True)
        result = get_local_plans_dir(tmp_path)
        assert result == tmp_path / ".silica" / "plans"

    def test_defaults_to_agent_when_neither_exists(self, tmp_path):
        """Should default to .agent/plans for new projects."""
        result = get_local_plans_dir(tmp_path)
        assert result == tmp_path / ".agent" / "plans"


class TestPlanManagerLocations:
    """Tests for PlanManager with dual storage locations."""

    def test_creates_global_dirs(self, temp_dirs):
        """Should always create global directories."""
        pm = PlanManager(temp_dirs["persona"])
        assert pm.global_active_dir.exists()
        assert pm.global_completed_dir.exists()

    def test_local_dirs_when_project_root(self, temp_dirs):
        """Should have local dirs when project_root is provided."""
        pm = PlanManager(temp_dirs["persona"], project_root=temp_dirs["project"])
        assert pm.local_plans_dir is not None

    def test_no_local_dirs_without_project_root(self, temp_dirs):
        """Should have no local dirs without project_root."""
        pm = PlanManager(temp_dirs["persona"])
        assert pm.local_plans_dir is None

    def test_create_plan_defaults_to_local_in_repo(self, temp_dirs):
        """Plans should default to local storage in git repo."""
        pm = PlanManager(temp_dirs["persona"], project_root=temp_dirs["project"])
        plan = pm.create_plan("Test", "session-1")
        assert plan.storage_location == LOCATION_LOCAL

    def test_create_plan_defaults_to_global_outside_repo(self, temp_dirs):
        """Plans should default to global storage outside git repo."""
        pm = PlanManager(temp_dirs["persona"])
        plan = pm.create_plan("Test", "session-1")
        assert plan.storage_location == LOCATION_GLOBAL

    def test_create_plan_force_local(self, temp_dirs):
        """Can force local storage."""
        pm = PlanManager(temp_dirs["persona"], project_root=temp_dirs["project"])
        plan = pm.create_plan("Test", "session-1", location=LOCATION_LOCAL)
        assert plan.storage_location == LOCATION_LOCAL
        # Verify file is in local dir
        assert (pm.local_active_dir / f"{plan.id}.md").exists()

    def test_create_plan_force_global(self, temp_dirs):
        """Can force global storage."""
        pm = PlanManager(temp_dirs["persona"], project_root=temp_dirs["project"])
        plan = pm.create_plan("Test", "session-1", location=LOCATION_GLOBAL)
        assert plan.storage_location == LOCATION_GLOBAL
        # Verify file is in global dir
        assert (pm.global_active_dir / f"{plan.id}.md").exists()


class TestPlanManagerSearch:
    """Tests for searching plans across locations."""

    def test_get_plan_finds_local(self, temp_dirs):
        """Should find plans in local storage."""
        pm = PlanManager(temp_dirs["persona"], project_root=temp_dirs["project"])
        plan = pm.create_plan("Local Plan", "session-1", location=LOCATION_LOCAL)
        found = pm.get_plan(plan.id)
        assert found is not None
        assert found.title == "Local Plan"

    def test_get_plan_finds_global(self, temp_dirs):
        """Should find plans in global storage."""
        pm = PlanManager(temp_dirs["persona"], project_root=temp_dirs["project"])
        plan = pm.create_plan("Global Plan", "session-1", location=LOCATION_GLOBAL)
        found = pm.get_plan(plan.id)
        assert found is not None
        assert found.title == "Global Plan"

    def test_list_plans_includes_both_locations(self, temp_dirs):
        """Should list plans from both local and global."""
        pm = PlanManager(temp_dirs["persona"], project_root=temp_dirs["project"])
        local_plan = pm.create_plan("Local", "s1", location=LOCATION_LOCAL)
        global_plan = pm.create_plan("Global", "s2", location=LOCATION_GLOBAL)

        plans = pm.list_active_plans()
        plan_ids = [p.id for p in plans]
        assert local_plan.id in plan_ids
        assert global_plan.id in plan_ids


class TestPlanMove:
    """Tests for moving plans between locations."""

    def test_move_local_to_global(self, temp_dirs):
        """Should move plan from local to global."""
        pm = PlanManager(temp_dirs["persona"], project_root=temp_dirs["project"])
        plan = pm.create_plan("Moveable", "session-1", location=LOCATION_LOCAL)

        assert pm.move_plan(plan.id, LOCATION_GLOBAL)

        moved = pm.get_plan(plan.id)
        assert moved.storage_location == LOCATION_GLOBAL
        # Original file should be gone
        assert not (pm.local_active_dir / f"{plan.id}.md").exists()
        # New file should exist
        assert (pm.global_active_dir / f"{plan.id}.md").exists()

    def test_move_global_to_local(self, temp_dirs):
        """Should move plan from global to local."""
        pm = PlanManager(temp_dirs["persona"], project_root=temp_dirs["project"])
        plan = pm.create_plan("Moveable", "session-1", location=LOCATION_GLOBAL)

        assert pm.move_plan(plan.id, LOCATION_LOCAL)

        moved = pm.get_plan(plan.id)
        assert moved.storage_location == LOCATION_LOCAL

    def test_move_to_local_fails_without_project(self, temp_dirs):
        """Should fail to move to local without a project."""
        pm = PlanManager(temp_dirs["persona"])  # No project_root
        plan = pm.create_plan("Global", "session-1")

        assert not pm.move_plan(plan.id, LOCATION_LOCAL)


class TestRootDirsMultiple:
    """Tests for plans with multiple root directories."""

    def test_matches_single_directory(self, temp_dirs):
        """Plan with one root_dir should match that directory."""
        pm = PlanManager(temp_dirs["persona"], project_root=temp_dirs["project"])
        plan = pm.create_plan("Test", "s1", root_dir=str(temp_dirs["project"]))

        assert plan.matches_directory(str(temp_dirs["project"]))
        assert not plan.matches_directory("/other/path")

    def test_matches_any_directory(self, temp_dirs):
        """Plan with multiple root_dirs should match any of them."""
        pm = PlanManager(temp_dirs["persona"])
        plan = pm.create_plan("Test", "s1")
        plan.root_dirs = ["/path/a", "/path/b"]
        pm.update_plan(plan)

        reloaded = pm.get_plan(plan.id)
        assert reloaded.matches_directory("/path/a")
        assert reloaded.matches_directory("/path/b")
        assert not reloaded.matches_directory("/path/c")

    def test_root_dir_backward_compat(self, temp_dirs):
        """root_dir property should return first root_dirs entry."""
        pm = PlanManager(temp_dirs["persona"])
        plan = pm.create_plan("Test", "s1")
        plan.root_dirs = ["/first", "/second"]

        assert plan.root_dir == "/first"

    def test_root_dir_empty_when_no_dirs(self, temp_dirs):
        """root_dir should be empty string when no root_dirs."""
        pm = PlanManager(temp_dirs["persona"])
        plan = pm.create_plan("Test", "s1")
        plan.root_dirs = []

        assert plan.root_dir == ""


class TestLocationEmoji:
    """Tests for location display in CLI (via toolbox)."""

    def test_plan_has_storage_location(self, temp_dirs):
        """Plans should have storage_location field."""
        pm = PlanManager(temp_dirs["persona"], project_root=temp_dirs["project"])
        local = pm.create_plan("Local", "s1", location=LOCATION_LOCAL)
        global_ = pm.create_plan("Global", "s2", location=LOCATION_GLOBAL)

        assert local.storage_location == LOCATION_LOCAL
        assert global_.storage_location == LOCATION_GLOBAL
