#!/bin/bash
# Minimal CI test for messaging system
set -e

echo "🤖 Minimal Messaging System Test"

# Cleanup function
cleanup() {
    jobs -p | xargs kill 2>/dev/null || true
    sleep 1
    jobs -p | xargs kill -9 2>/dev/null || true
}

trap cleanup EXIT

# Test environment
export SILICA_WORKSPACE="ci-test"
export SILICA_PROJECT="test"
export DATA_DIR="/tmp/silica-ci-$$"
mkdir -p "$DATA_DIR"

echo "✅ Testing CLI commands"
uv run silica messaging --help >/dev/null
uv run silica msg --help >/dev/null

echo "✅ Testing Python imports"
uv run python -c "from silica.cli.commands.messaging import messaging" >/dev/null
uv run python -c "from silica.cli.commands.msg import msg" >/dev/null

echo "✅ Testing messaging function syntax"
bash -n silica/agent/messaging.sh

echo "✅ Testing messaging app"
timeout 6s uv run python silica/messaging/app.py --port 15555 >/dev/null 2>&1 &
sleep 2
curl -s -H "Host: silica-messaging" "http://localhost:15555/health" >/dev/null

echo "✅ Testing receiver"
timeout 6s uv run silica messaging receiver --port 18888 >/dev/null 2>&1 &
sleep 2  
curl -s "http://localhost:18888/health" >/dev/null

echo "🎉 Essential messaging tests passed!"
cleanup
exit 0