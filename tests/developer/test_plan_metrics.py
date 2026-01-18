"""Tests for plan metrics tracking functionality.

Tests cover:
- Data model serialization (MetricDefinition, MetricSnapshot, PlanMetrics)
- Snapshot capture with cost tracking
- Capture command execution and parsing
- Feedback message generation
- Backward compatibility with plans without metrics
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from silica.developer.plans import (
    MetricDefinition,
    MetricSnapshot,
    Plan,
    PlanMetrics,
    PlanStatus,
    get_agent_version,
    get_silica_version,
)


class TestMetricDefinition:
    """Tests for MetricDefinition dataclass."""

    def test_basic_creation(self):
        """Test creating a basic metric definition."""
        metric = MetricDefinition(
            name="tests_passing",
            metric_type="int",
            direction="up",
            target_value=100,
        )
        assert metric.name == "tests_passing"
        assert metric.metric_type == "int"
        assert metric.direction == "up"
        assert metric.target_value == 100
        assert metric.capture_command == ""
        assert metric.validated is False

    def test_burn_down_metric(self):
        """Test creating a burn-down metric (lower is better)."""
        metric = MetricDefinition(
            name="test_failures",
            metric_type="int",
            direction="down",
            target_value=0,
        )
        assert metric.direction == "down"
        assert metric.target_value == 0

    def test_to_dict(self):
        """Test serialization to dict."""
        metric = MetricDefinition(
            name="coverage",
            metric_type="percent",
            direction="up",
            capture_command="./coverage.sh",
            description="Code coverage",
            target_value=80.0,
            validated=True,
        )
        d = metric.to_dict()
        assert d["name"] == "coverage"
        assert d["metric_type"] == "percent"
        assert d["direction"] == "up"
        assert d["capture_command"] == "./coverage.sh"
        assert d["description"] == "Code coverage"
        assert d["target_value"] == 80.0
        assert d["validated"] is True

    def test_from_dict(self):
        """Test deserialization from dict."""
        d = {
            "name": "tests_passing",
            "metric_type": "int",
            "direction": "up",
            "capture_command": "echo 42",
            "target_value": 100,
            "validated": True,
        }
        metric = MetricDefinition.from_dict(d)
        assert metric.name == "tests_passing"
        assert metric.target_value == 100
        assert metric.validated is True

    def test_from_dict_defaults(self):
        """Test deserialization with missing fields uses defaults."""
        d = {"name": "basic"}
        metric = MetricDefinition.from_dict(d)
        assert metric.name == "basic"
        assert metric.metric_type == "int"
        assert metric.direction == "up"
        assert metric.validated is False


class TestMetricSnapshot:
    """Tests for MetricSnapshot dataclass."""

    def test_basic_creation(self):
        """Test creating a basic snapshot."""
        now = datetime.now(timezone.utc)
        snapshot = MetricSnapshot(
            timestamp=now,
            wall_clock_seconds=120.5,
            trigger="task_complete:abc123",
            input_tokens=1000,
            output_tokens=500,
            cost_dollars=0.05,
            agent_version="v1.0.0",
            silica_version="0.1.0",
            metrics={"tests_passing": 42},
        )
        assert snapshot.timestamp == now
        assert snapshot.wall_clock_seconds == 120.5
        assert snapshot.trigger == "task_complete:abc123"
        assert snapshot.input_tokens == 1000
        assert snapshot.cost_dollars == 0.05
        assert snapshot.metrics["tests_passing"] == 42

    def test_to_dict(self):
        """Test serialization to dict."""
        now = datetime.now(timezone.utc)
        snapshot = MetricSnapshot(
            timestamp=now,
            wall_clock_seconds=60.0,
            trigger="plan_start",
            input_tokens=500,
            output_tokens=200,
            metrics={"foo": 10.5},
            metric_errors={"bar": "command failed"},
        )
        d = snapshot.to_dict()
        assert d["wall_clock_seconds"] == 60.0
        assert d["trigger"] == "plan_start"
        assert d["metrics"]["foo"] == 10.5
        assert d["metric_errors"]["bar"] == "command failed"

    def test_from_dict(self):
        """Test deserialization from dict."""
        d = {
            "timestamp": "2026-01-18T12:00:00+00:00",
            "wall_clock_seconds": 300.0,
            "trigger": "manual",
            "input_tokens": 2000,
            "output_tokens": 800,
            "cost_dollars": 0.10,
            "metrics": {"tests": 50},
        }
        snapshot = MetricSnapshot.from_dict(d)
        assert snapshot.wall_clock_seconds == 300.0
        assert snapshot.trigger == "manual"
        assert snapshot.metrics["tests"] == 50


class TestPlanMetrics:
    """Tests for PlanMetrics dataclass."""

    def test_empty_creation(self):
        """Test creating empty plan metrics."""
        metrics = PlanMetrics()
        assert metrics.definitions == []
        assert metrics.snapshots == []
        assert metrics.execution_started_at is None

    def test_with_definitions(self):
        """Test creating plan metrics with definitions."""
        definitions = [
            MetricDefinition(name="tests", direction="up"),
            MetricDefinition(name="failures", direction="down"),
        ]
        metrics = PlanMetrics(definitions=definitions)
        assert len(metrics.definitions) == 2

    def test_to_dict_and_from_dict(self):
        """Test round-trip serialization."""
        now = datetime.now(timezone.utc)
        metrics = PlanMetrics(
            definitions=[MetricDefinition(name="coverage", target_value=80)],
            snapshots=[
                MetricSnapshot(
                    timestamp=now,
                    wall_clock_seconds=0,
                    trigger="plan_start",
                    metrics={"coverage": 50},
                )
            ],
            execution_started_at=now,
            baseline_input_tokens=1000,
            baseline_cost_dollars=0.05,
        )

        d = metrics.to_dict()
        restored = PlanMetrics.from_dict(d)

        assert len(restored.definitions) == 1
        assert restored.definitions[0].name == "coverage"
        assert len(restored.snapshots) == 1
        assert restored.snapshots[0].trigger == "plan_start"
        assert restored.baseline_input_tokens == 1000

    def test_get_start_snapshot(self):
        """Test getting the plan_start snapshot."""
        now = datetime.now(timezone.utc)
        metrics = PlanMetrics(
            snapshots=[
                MetricSnapshot(
                    timestamp=now, wall_clock_seconds=0, trigger="plan_start"
                ),
                MetricSnapshot(
                    timestamp=now, wall_clock_seconds=60, trigger="task_complete:1"
                ),
            ]
        )
        start = metrics.get_start_snapshot()
        assert start is not None
        assert start.trigger == "plan_start"

    def test_get_previous_snapshot(self):
        """Test getting the most recent snapshot."""
        now = datetime.now(timezone.utc)
        metrics = PlanMetrics(
            snapshots=[
                MetricSnapshot(
                    timestamp=now, wall_clock_seconds=0, trigger="plan_start"
                ),
                MetricSnapshot(
                    timestamp=now, wall_clock_seconds=60, trigger="task_complete:1"
                ),
            ]
        )
        prev = metrics.get_previous_snapshot()
        assert prev is not None
        assert prev.trigger == "task_complete:1"


class TestPlanWithMetrics:
    """Tests for Plan with metrics field."""

    def test_plan_has_metrics_field(self):
        """Test that Plan has a metrics field."""
        plan = Plan(
            id="test",
            title="Test Plan",
            status=PlanStatus.DRAFT,
            session_id="session",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert hasattr(plan, "metrics")
        assert isinstance(plan.metrics, PlanMetrics)

    def test_plan_metrics_serialization(self):
        """Test that plan metrics are serialized correctly."""
        plan = Plan(
            id="test",
            title="Test Plan",
            status=PlanStatus.DRAFT,
            session_id="session",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        plan.metrics.definitions.append(
            MetricDefinition(name="tests", target_value=100)
        )

        d = plan.to_dict()
        assert "metrics" in d
        assert len(d["metrics"]["definitions"]) == 1

    def test_plan_from_dict_without_metrics(self):
        """Test backward compatibility - loading plan without metrics field."""
        d = {
            "id": "old-plan",
            "title": "Old Plan",
            "status": "draft",
            "session_id": "session",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
        plan = Plan.from_dict(d)
        assert plan.metrics is not None
        assert isinstance(plan.metrics, PlanMetrics)
        assert plan.metrics.definitions == []


class TestVersionHelpers:
    """Tests for version helper functions."""

    def test_get_silica_version(self):
        """Test getting silica version."""
        version = get_silica_version()
        assert isinstance(version, str)
        assert version != ""

    def test_get_agent_version_returns_string(self):
        """Test that get_agent_version returns a string."""
        version = get_agent_version()
        assert isinstance(version, str)

    @patch("subprocess.run")
    def test_get_agent_version_with_tag(self, mock_run):
        """Test getting agent version when on a tag."""
        mock_run.return_value = MagicMock(returncode=0, stdout="v1.2.3\n")
        version = get_agent_version()
        assert version == "v1.2.3"

    @patch("subprocess.run")
    def test_get_agent_version_with_sha(self, mock_run):
        """Test getting agent version falls back to SHA."""
        # First call (tag) fails, second call (SHA) succeeds
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="not a tag"),
            MagicMock(returncode=0, stdout="abc1234\n"),
        ]
        version = get_agent_version()
        assert version == "abc1234"


class TestCaptureCommandHelpers:
    """Tests for capture command helper functions."""

    def test_run_capture_command_success(self):
        """Test running a successful capture command."""
        from silica.developer.tools.planning import _run_capture_command

        success, output = _run_capture_command("echo 42")
        assert success is True
        assert output == "42"

    def test_run_capture_command_failure(self):
        """Test running a failing capture command."""
        from silica.developer.tools.planning import _run_capture_command

        success, output = _run_capture_command("exit 1")
        assert success is False
        assert "failed" in output.lower() or "exit" in output.lower()

    def test_run_capture_command_empty(self):
        """Test running with empty command."""
        from silica.developer.tools.planning import _run_capture_command

        success, output = _run_capture_command("")
        assert success is False

    def test_parse_metric_value_int(self):
        """Test parsing integer metric value."""
        from silica.developer.tools.planning import _parse_metric_value

        assert _parse_metric_value("42", "int") == 42.0
        assert _parse_metric_value("  100  ", "int") == 100.0

    def test_parse_metric_value_float(self):
        """Test parsing float metric value."""
        from silica.developer.tools.planning import _parse_metric_value

        assert _parse_metric_value("3.14", "float") == 3.14
        assert _parse_metric_value("42.0", "float") == 42.0

    def test_parse_metric_value_percent(self):
        """Test parsing percent metric value."""
        from silica.developer.tools.planning import _parse_metric_value

        assert _parse_metric_value("75%", "percent") == 75.0
        assert _parse_metric_value("80.5%", "percent") == 80.5
        assert _parse_metric_value("90", "percent") == 90.0

    def test_parse_metric_value_empty(self):
        """Test parsing empty value raises error."""
        from silica.developer.tools.planning import _parse_metric_value

        with pytest.raises(ValueError):
            _parse_metric_value("", "int")


class TestMetricsFeedback:
    """Tests for metrics feedback generation."""

    def test_generate_metrics_feedback_empty(self):
        """Test feedback generation with no definitions."""
        from silica.developer.tools.planning import _generate_metrics_feedback

        plan = Plan(
            id="test",
            title="Test",
            status=PlanStatus.IN_PROGRESS,
            session_id="session",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        snapshot = MetricSnapshot(
            timestamp=datetime.now(timezone.utc),
            wall_clock_seconds=60,
            trigger="test",
        )

        feedback = _generate_metrics_feedback(plan, snapshot)
        assert feedback == ""  # No definitions = no feedback

    def test_generate_metrics_feedback_with_metrics(self):
        """Test feedback generation with metrics."""
        from silica.developer.tools.planning import _generate_metrics_feedback

        now = datetime.now(timezone.utc)
        plan = Plan(
            id="test",
            title="Test",
            status=PlanStatus.IN_PROGRESS,
            session_id="session",
            created_at=now,
            updated_at=now,
        )
        plan.metrics.definitions.append(
            MetricDefinition(
                name="tests_passing",
                direction="up",
                target_value=100,
                validated=True,
            )
        )
        plan.metrics.snapshots.append(
            MetricSnapshot(
                timestamp=now,
                wall_clock_seconds=0,
                trigger="plan_start",
                metrics={"tests_passing": 50},
            )
        )

        snapshot = MetricSnapshot(
            timestamp=now,
            wall_clock_seconds=120,
            trigger="task_complete:1",
            input_tokens=1000,
            output_tokens=500,
            cost_dollars=0.05,
            metrics={"tests_passing": 75},
        )
        plan.metrics.snapshots.append(snapshot)

        feedback = _generate_metrics_feedback(plan, snapshot)

        assert "Metrics Snapshot" in feedback
        assert "tests_passing" in feedback
        assert "75" in feedback  # Current value
        assert "+25" in feedback  # Delta from start
        assert "Cost" in feedback


class TestCostBaseline:
    """Tests for cost baseline tracking."""

    def test_record_metrics_baseline(self):
        """Test recording cost baseline."""
        from silica.developer.tools.planning import _record_metrics_baseline

        plan = Plan(
            id="test",
            title="Test",
            status=PlanStatus.IN_PROGRESS,
            session_id="session",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_context = MagicMock()
        mock_context.usage_summary.return_value = {
            "total_input_tokens": 5000,
            "total_output_tokens": 2000,
            "total_thinking_tokens": 500,
            "cached_tokens": 1000,
            "total_cost": 0.25,
        }

        _record_metrics_baseline(plan, mock_context)

        assert plan.metrics.execution_started_at is not None
        assert plan.metrics.baseline_input_tokens == 5000
        assert plan.metrics.baseline_output_tokens == 2000
        assert plan.metrics.baseline_thinking_tokens == 500
        assert plan.metrics.baseline_cached_tokens == 1000
        assert plan.metrics.baseline_cost_dollars == 0.25

    def test_get_cost_delta(self):
        """Test getting cost delta from baseline."""
        from silica.developer.tools.planning import _get_cost_delta

        plan = Plan(
            id="test",
            title="Test",
            status=PlanStatus.IN_PROGRESS,
            session_id="session",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        plan.metrics.baseline_input_tokens = 1000
        plan.metrics.baseline_output_tokens = 500
        plan.metrics.baseline_cost_dollars = 0.05

        mock_context = MagicMock()
        mock_context.usage_summary.return_value = {
            "total_input_tokens": 3000,
            "total_output_tokens": 1500,
            "total_thinking_tokens": 200,
            "cached_tokens": 500,
            "total_cost": 0.15,
        }

        delta = _get_cost_delta(plan, mock_context)

        assert delta["input_tokens"] == 2000
        assert delta["output_tokens"] == 1000
        assert abs(delta["cost_dollars"] - 0.10) < 0.001  # Float comparison


class TestSnapshotCapture:
    """Tests for metric snapshot capture."""

    def test_capture_metric_snapshot_basic(self):
        """Test basic snapshot capture."""
        from silica.developer.tools.planning import capture_metric_snapshot

        now = datetime.now(timezone.utc)
        plan = Plan(
            id="test",
            title="Test",
            status=PlanStatus.IN_PROGRESS,
            session_id="session",
            created_at=now,
            updated_at=now,
        )
        plan.metrics.execution_started_at = now
        plan.metrics.baseline_input_tokens = 1000

        mock_context = MagicMock()
        mock_context.usage_summary.return_value = {
            "total_input_tokens": 2000,
            "total_output_tokens": 800,
            "total_thinking_tokens": 100,
            "cached_tokens": 200,
            "total_cost": 0.10,
        }

        snapshot = capture_metric_snapshot(plan, mock_context, "test_trigger")

        assert snapshot.trigger == "test_trigger"
        assert snapshot.input_tokens == 1000  # Delta from baseline
        assert len(plan.metrics.snapshots) == 1

    def test_capture_metric_snapshot_with_command(self):
        """Test snapshot capture with metric command."""
        from silica.developer.tools.planning import capture_metric_snapshot

        now = datetime.now(timezone.utc)
        plan = Plan(
            id="test",
            title="Test",
            status=PlanStatus.IN_PROGRESS,
            session_id="session",
            created_at=now,
            updated_at=now,
        )
        plan.metrics.execution_started_at = now
        plan.metrics.definitions.append(
            MetricDefinition(
                name="test_metric",
                capture_command="echo 42",
                validated=True,
            )
        )

        mock_context = MagicMock()
        mock_context.usage_summary.return_value = {
            "total_input_tokens": 1000,
            "total_output_tokens": 500,
            "total_thinking_tokens": 0,
            "cached_tokens": 0,
            "total_cost": 0.05,
        }

        snapshot = capture_metric_snapshot(plan, mock_context, "test")

        assert "test_metric" in snapshot.metrics
        assert snapshot.metrics["test_metric"] == 42.0
