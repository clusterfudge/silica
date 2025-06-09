#!/bin/bash
set -e

# Messaging Components Test Script
# This script contains the mutable parts of messaging component tests
# that were previously in the GitHub workflow

echo "🧪 Starting Messaging Components Tests..."

# Test root messaging app startup
echo "📋 Testing root messaging app startup..."
timeout 15s uv run python silica/messaging/app.py --port 5555 &
APP_PID=$!
sleep 5
if curl -f -H "Host: silica-messaging" http://localhost:5555/health >/dev/null 2>&1; then
    echo "✅ Root messaging app startup successful"
else
    echo "❌ Root messaging app startup failed"
    kill $APP_PID 2>/dev/null || true
    exit 1
fi
kill $APP_PID 2>/dev/null || true

# Test agent receiver startup  
echo "📋 Testing agent receiver startup..."
export SILICA_WORKSPACE=test
export SILICA_PROJECT=ci
timeout 15s uv run silica messaging receiver --port 8888 &
RECEIVER_PID=$!
sleep 5
if curl -f http://localhost:8888/health >/dev/null 2>&1; then
    echo "✅ Agent receiver startup successful"
else
    echo "❌ Agent receiver startup failed"
    kill $RECEIVER_PID 2>/dev/null || true
    exit 1
fi
kill $RECEIVER_PID 2>/dev/null || true

# Test Pure CSS web interface
echo "📋 Testing Pure CSS web interface..."
timeout 15s uv run python silica/messaging/app.py --port 5556 &
WEB_PID=$!
sleep 5
response=$(curl -s -H "Host: silica-messaging" http://localhost:5556/ || echo "")
if echo "$response" | grep -q "purecss\|pure-css\|Pure CSS\|messaging\|Silica Messaging" >/dev/null 2>&1; then
    echo "✅ Pure CSS web interface test passed"
else
    echo "❌ Pure CSS web interface test failed"
    echo "Response received: $response"
    kill $WEB_PID 2>/dev/null || true
    exit 1
fi
kill $WEB_PID 2>/dev/null || true

# Test messaging function exports
echo "📋 Testing messaging function exports..."
if source silica/agent/messaging.sh 2>/dev/null; then
    if type silica-msg >/dev/null 2>&1 && \
       type silica-msg-status >/dev/null 2>&1 && \
       type silica-msg-participants >/dev/null 2>&1; then
        echo "✅ Messaging function exports successful"
    else
        echo "❌ Messaging function exports failed"
        exit 1
    fi
else
    echo "❌ Failed to source messaging functions"
    exit 1
fi

echo "🎉 All messaging component tests passed!"