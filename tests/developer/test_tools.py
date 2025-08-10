import unittest
from typing import Optional
from silica.developer.tools.framework import tool
from silica.developer.context import AgentContext


# Test fixtures
@tool
def simple_func(context: "AgentContext", arg1: str):
    """A simple function with one required argument.

    Args:
        arg1: First argument description
    """
    return arg1


@tool
def multi_arg_func(
    context: "AgentContext",
    required1: str,
    required2: int,
    optional1: Optional[bool] = None,
):
    """A function with multiple arguments, some optional.

    Args:
        required1: First required argument
        required2: Second required argument
        optional1: First optional argument
    """
    return required1, required2, optional1


@tool
def no_docstring_func(
    context: "AgentContext", arg1: str, optional1: Optional[str] = None
):
    return arg1


class TestToolDecorator(unittest.TestCase):
    def test_context_parameter_validation(self):
        """Test that tool decorator validates context parameter"""
        # Test missing context parameter
        with self.assertRaises(ValueError) as cm:

            @tool
            def no_context(arg1: str):
                pass

        self.assertIn("must be 'context'", str(cm.exception))

        # Test wrong parameter name
        with self.assertRaises(ValueError) as cm:

            @tool
            def wrong_param_name(wrong_name: "AgentContext", arg1: str):
                pass

        self.assertIn("must be 'context'", str(cm.exception))

        # Test wrong parameter type
        with self.assertRaises(ValueError) as cm:

            @tool
            def wrong_param_type(context: str, arg1: str):
                pass

        self.assertIn("must be annotated with 'AgentContext' type", str(cm.exception))

        # Test valid context parameter
        @tool
        def valid_func(context: "AgentContext", arg1: str):
            pass

        # Should not raise any exception

    def test_schema_basic_structure(self):
        """Test that schema() adds all expected top-level keys"""
        schema = simple_func.schema()
        self.assertIsInstance(schema, dict)
        self.assertIn("name", schema)
        self.assertIn("description", schema)
        self.assertIn("input_schema", schema)
        self.assertIn("properties", schema["input_schema"])
        self.assertIn("required", schema["input_schema"])

    def test_schema_name(self):
        """Test that schema name matches function name"""
        self.assertEqual(simple_func.schema()["name"], "simple_func")
        self.assertEqual(multi_arg_func.schema()["name"], "multi_arg_func")

    def test_schema_description(self):
        """Test that schema description comes from docstring"""
        self.assertEqual(
            simple_func.schema()["description"],
            "A simple function with one required argument.",
        )

    def test_schema_no_docstring(self):
        """Test handling of functions without docstrings"""
        schema = no_docstring_func.schema()
        self.assertEqual(schema["description"], "")
        self.assertIn("arg1", schema["input_schema"]["properties"])

    def test_required_parameters(self):
        """Test that non-Optional parameters are marked as required"""
        schema = multi_arg_func.schema()
        required = schema["input_schema"]["required"]
        self.assertIn("required1", required)
        self.assertIn("required2", required)
        self.assertNotIn("optional1", required)

    def test_optional_parameters(self):
        """Test that Optional parameters are not marked as required"""
        schema = multi_arg_func.schema()
        self.assertIn("optional1", schema["input_schema"]["properties"])
        self.assertNotIn("optional1", schema["input_schema"]["required"])

    def test_parameter_descriptions(self):
        """Test that parameter descriptions are extracted from docstring"""
        schema = multi_arg_func.schema()
        props = schema["input_schema"]["properties"]
        self.assertEqual(props["required1"]["description"], "First required argument")
        self.assertEqual(props["optional1"]["description"], "First optional argument")

    def test_context_parameter_excluded(self):
        """Test that context parameter is not included in schema"""
        schema = simple_func.schema()
        self.assertNotIn("context", schema["input_schema"]["properties"])
        self.assertNotIn("context", schema["input_schema"]["required"])

    def test_original_function_behavior(self):
        """Test that decorated function still works normally"""

        # Create a minimal context mock
        class MockContext:
            pass

        context = MockContext()

        # Test simple function
        self.assertEqual(simple_func(context, "test"), "test")

        # Test multi-argument function
        result = multi_arg_func(context, "test", 42)
        self.assertEqual(result, ("test", 42, None))

        # Test with optional argument
        result = multi_arg_func(context, "test", 42, True)
        self.assertEqual(result, ("test", 42, True))


if __name__ == "__main__":
    unittest.main()
