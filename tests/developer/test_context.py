import unittest
from unittest.mock import Mock
from uuid import uuid4
from anthropic.types import Usage

from silica.developer.context import AgentContext
from silica.developer.models import ModelSpec


class TestAgentContext(unittest.TestCase):
    def test_usage_summary(self):
        mock_user_interface = Mock()
        model_spec = ModelSpec(
            title="test-model",
            pricing={"input": 3.00, "output": 15.00},
            cache_pricing={"write": 3.75, "read": 0.30},
        )
        context = AgentContext.create(
            model_spec=model_spec,
            sandbox_mode="read-only",
            sandbox_contents=[],
            user_interface=mock_user_interface,
        )

        # Mock usage data
        mock_usage_1 = Mock(spec=Usage)
        mock_usage_1.input_tokens = 100
        mock_usage_1.output_tokens = 25
        mock_usage_1.cache_creation_input_tokens = 0
        mock_usage_1.cache_read_input_tokens = 0
        mock_usage_2 = Mock(spec=Usage)
        mock_usage_2.input_tokens = 125
        mock_usage_2.output_tokens = 175
        mock_usage_2.cache_creation_input_tokens = 0
        mock_usage_2.cache_read_input_tokens = 0

        context = AgentContext(
            session_id=str(uuid4()),
            parent_session_id=None,
            model_spec=model_spec,
            sandbox=context.sandbox,
            user_interface=context.user_interface,
            usage=[(mock_usage_1, model_spec), (mock_usage_2, model_spec)],
            memory_manager=context.memory_manager,
        )

        expected_summary = {
            "total_input_tokens": 225,
            "total_output_tokens": 200,
            "total_cost": 0.003675,
            "model_breakdown": {
                "test-model": {
                    "total_input_tokens": 225,
                    "total_output_tokens": 200,
                    "total_cost": 0.003675,
                },
            },
        }

        actual_summary = context.usage_summary()
        self.assertAlmostEqual(
            actual_summary["total_cost"], expected_summary["total_cost"], places=8
        )


if __name__ == "__main__":
    unittest.main()
