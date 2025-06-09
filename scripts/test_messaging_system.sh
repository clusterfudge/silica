#!/bin/bash
set -e

# Messaging System Test Script
# This script contains the mutable parts of messaging system tests
# that were previously in the GitHub workflow

echo "🧪 Starting Messaging System Tests..."

# Test CLI commands availability
echo "📋 Testing CLI commands availability..."
uv run silica messaging --help >/dev/null
uv run silica msg --help >/dev/null
echo "✅ CLI commands available"

# Test messaging function syntax
echo "📋 Testing messaging function syntax..."
bash -n silica/agent/messaging.sh
echo "✅ Messaging function syntax valid"

# Test Python imports
echo "📋 Testing Python imports..."
uv run python -c "from silica.cli.commands.messaging import messaging" >/dev/null
uv run python -c "from silica.cli.commands.msg import msg" >/dev/null
uv run python -c "from silica.utils.messaging import deploy_messaging_app" >/dev/null
echo "✅ Python imports successful"

# Run comprehensive messaging system tests
echo "📋 Running comprehensive messaging system tests..."
if [ -f "./test_messaging_ci_simple.sh" ]; then
    bash ./test_messaging_ci_simple.sh
    echo "✅ Comprehensive tests passed"
else
    echo "❌ test_messaging_ci_simple.sh not found"
    exit 1
fi

echo "🎉 All messaging system tests passed!"