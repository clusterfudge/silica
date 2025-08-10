import unittest
from unittest.mock import MagicMock
from silica.developer.tools.repl import python_repl


class TestPythonREPL(unittest.TestCase):
    def setUp(self):
        # Create a mock context that can be passed to the tool
        self.mock_context = MagicMock()

    def test_basic_execution(self):
        """Test simple Python code execution"""
        code = "a = 5\nb = 10\nprint(a + b)"
        result = python_repl(self.mock_context, code)
        self.assertIn("15", result)

    def test_complex_computation(self):
        """Test more complex mathematical operations"""
        code = """
def fibonacci(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a

for i in range(10):
    print(fibonacci(i))
"""
        result = python_repl(self.mock_context, code)
        expected_output = "0\n1\n1\n2\n3\n5\n8\n13\n21\n34"
        for num in expected_output.split("\n"):
            self.assertIn(num, result)

    def test_syntax_error(self):
        """Test handling of syntax errors"""
        code = "for i in range(5) print(i)"  # Missing colon
        result = python_repl(self.mock_context, code)
        self.assertIn("Syntax Error", result)

    def test_runtime_error(self):
        """Test handling of runtime errors"""
        code = "1/0"  # Division by zero
        result = python_repl(self.mock_context, code)
        self.assertIn("Error executing code", result)
        self.assertIn("ZeroDivisionError", result)

    def test_restricted_import(self):
        """Test that dangerous imports are restricted"""
        code = "import os\nos.system('echo test')"
        result = python_repl(self.mock_context, code)
        self.assertIn("restricted for security reasons", result)

    def test_restricted_file_operations(self):
        """Test that file operations are restricted"""
        code = "open('test.txt', 'w').write('hello')"
        result = python_repl(self.mock_context, code)
        self.assertIn("restricted for security reasons", result)

    def test_use_of_safe_modules(self):
        """Test using allowed modules"""
        code = """
# Test math
print(math.sqrt(16))

# Test random
random.seed(42)
print(random.randint(1, 100))

# Test datetime
print(datetime.datetime(2023, 1, 1).year)

# Test json
print(json.dumps({"key": "value"}))

# Test regex
print(re.match(r'\\d+', '123abc').group())
"""
        result = python_repl(self.mock_context, code)
        self.assertIn("4.0", result)  # math.sqrt(16)
        self.assertIn("2023", result)  # datetime year
        self.assertIn('"key": "value"', result)  # json output
        self.assertIn("123", result)  # regex match

    def test_no_output(self):
        """Test code that produces no output"""
        code = "a = 5"
        result = python_repl(self.mock_context, code)
        self.assertIn("executed successfully with no output", result)

    def test_exec_eval_restricted(self):
        """Test that exec and eval are restricted"""
        code = "eval('__import__(\\'os\\').system(\\'ls\\')')"
        result = python_repl(self.mock_context, code)
        self.assertIn("restricted for security reasons", result)


if __name__ == "__main__":
    unittest.main()
