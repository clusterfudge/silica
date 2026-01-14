"""Tests for plan storage location features (local vs global)."""

import pytest

from silica.developer.plans import (
    PlanManager,
    PlanStatus,
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


class TestSlugify:
    """Tests for the slugify function."""

    def test_basic_slugify(self):
        from silica.developer.plans import slugify

        assert slugify("Add User Avatars") == "add-user-avatars"

    def test_slugify_special_chars(self):
        from silica.developer.plans import slugify

        assert slugify("Fix bug #123") == "fix-bug-123"
        assert slugify("Refactor auth/middleware") == "refactor-auth-middleware"

    def test_slugify_max_length(self):
        from silica.developer.plans import slugify

        long_title = "This is a very long plan title that should be truncated"
        result = slugify(long_title, max_length=20)
        assert len(result) <= 20
        assert not result.endswith("-")

    def test_plan_get_slug(self, temp_dirs):
        pm = PlanManager(temp_dirs["persona"])
        plan = pm.create_plan("Add Dark Mode Support", "s1")
        assert plan.get_slug() == "add-dark-mode-support"


class TestShelving:
    """Tests for plan shelving and remote execution."""

    def test_approve_with_shelve(self, temp_dirs):
        """Approve with shelve=True should set shelved flag."""
        pm = PlanManager(temp_dirs["persona"])
        plan = pm.create_plan("Test", "s1")
        plan.add_task("Do something")
        pm.update_plan(plan)
        pm.submit_for_review(plan.id)

        pm.approve_plan(plan.id, shelve=True)

        reloaded = pm.get_plan(plan.id)
        assert reloaded.status == PlanStatus.APPROVED
        assert reloaded.shelved is True

    def test_approve_without_shelve(self, temp_dirs):
        """Approve without shelve should not set shelved flag."""
        pm = PlanManager(temp_dirs["persona"])
        plan = pm.create_plan("Test", "s1")
        plan.add_task("Do something")
        pm.update_plan(plan)
        pm.submit_for_review(plan.id)

        pm.approve_plan(plan.id, shelve=False)

        reloaded = pm.get_plan(plan.id)
        assert reloaded.status == PlanStatus.APPROVED
        assert reloaded.shelved is False

    def test_list_shelved_plans(self, temp_dirs):
        """list_shelved_plans should only return approved+shelved plans."""
        pm = PlanManager(temp_dirs["persona"])

        # Create and shelve one plan
        p1 = pm.create_plan("Shelved", "s1")
        p1.add_task("Task")
        pm.update_plan(p1)
        pm.submit_for_review(p1.id)
        pm.approve_plan(p1.id, shelve=True)

        # Create approved but not shelved
        p2 = pm.create_plan("Not Shelved", "s2")
        p2.add_task("Task")
        pm.update_plan(p2)
        pm.submit_for_review(p2.id)
        pm.approve_plan(p2.id, shelve=False)

        # Create draft
        pm.create_plan("Draft", "s3")

        shelved = pm.list_shelved_plans()
        assert len(shelved) == 1
        assert shelved[0].id == p1.id

    def test_remote_workspace_fields(self, temp_dirs):
        """Plan should store remote workspace and branch."""
        pm = PlanManager(temp_dirs["persona"])
        plan = pm.create_plan("Test", "s1")
        plan.remote_workspace = "plan-test"
        plan.remote_branch = "plan/test"
        pm.update_plan(plan)

        reloaded = pm.get_plan(plan.id)
        assert reloaded.remote_workspace == "plan-test"
        assert reloaded.remote_branch == "plan/test"


class TestPlanRejection:
    """Tests for plan rejection and revision flow."""

    def test_reject_returns_to_draft(self, temp_dirs):
        """Rejecting a plan should return it to DRAFT status."""
        pm = PlanManager(temp_dirs["persona"])
        plan = pm.create_plan("Test", "s1")
        plan.add_task("Do something")
        pm.update_plan(plan)

        # Submit for review
        pm.submit_for_review(plan.id)
        assert pm.get_plan(plan.id).status == PlanStatus.IN_REVIEW

        # Manually revert (simulating reject)
        plan = pm.get_plan(plan.id)
        plan.status = PlanStatus.DRAFT
        plan.add_progress("Plan rejected - revisions requested")
        pm.update_plan(plan)

        reloaded = pm.get_plan(plan.id)
        assert reloaded.status == PlanStatus.DRAFT
        assert "rejected" in reloaded.progress_log[-1].message.lower()
