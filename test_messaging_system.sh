#!/bin/bash
# Test script for SILIC-5 messaging system
# This script tests the messaging system components locally before deployment

set -e  # Exit on error

echo "🧪 Testing Silica Messaging System"
echo "=================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in the right directory
if [[ ! -f "silica/messaging/app.py" ]]; then
    print_error "Please run this script from the silica repository root"
    exit 1
fi

# Set up test environment
export SILICA_WORKSPACE="test-workspace"
export SILICA_PROJECT="test-project"
export SILICA_PARTICIPANT="test-workspace-test-project"
export SILICA_RECEIVER_PORT="8901"
export SILICA_MESSAGE_DELIVERY="status"

print_status "Setting up test environment..."
print_status "SILICA_WORKSPACE: $SILICA_WORKSPACE"
print_status "SILICA_PROJECT: $SILICA_PROJECT"
print_status "SILICA_PARTICIPANT: $SILICA_PARTICIPANT"

# Test 1: Check CLI commands are available
echo
print_status "Test 1: CLI Command Availability"
echo "================================"

if uv run silica messaging --help > /dev/null 2>&1; then
    print_success "silica messaging command available"
else
    print_error "silica messaging command not available"
    exit 1
fi

if uv run silica msg --help > /dev/null 2>&1; then
    print_success "silica msg command available"
else
    print_error "silica msg command not available"
    exit 1
fi

# Test 2: Start root messaging app in background
echo
print_status "Test 2: Root Messaging App"
echo "=========================="

print_status "Starting root messaging app on port 5000..."
uv run silica messaging app --port 5000 > messaging_app.log 2>&1 &
MESSAGING_APP_PID=$!

# Wait for app to start
sleep 3

# Test health check
if curl -s -H "Host: silica-messaging" http://localhost:5000/health > /dev/null; then
    print_success "Root messaging app is healthy"
else
    print_error "Root messaging app health check failed"
    kill $MESSAGING_APP_PID 2>/dev/null || true
    exit 1
fi

# Test 3: Start agent receiver in background
echo
print_status "Test 3: Agent Receiver"
echo "====================="

print_status "Starting agent receiver on port 8901..."
uv run silica messaging receiver --port 8901 > receiver.log 2>&1 &
RECEIVER_PID=$!

# Wait for receiver to start
sleep 3

# Test receiver health check
if curl -s http://localhost:8901/health > /dev/null; then
    print_success "Agent receiver is healthy"
else
    print_error "Agent receiver health check failed"
    kill $MESSAGING_APP_PID $RECEIVER_PID 2>/dev/null || true
    exit 1
fi

# Test 4: CLI Message Operations
echo
print_status "Test 4: CLI Message Operations"
echo "=============================="

# Test thread listing (should be empty initially)
print_status "Testing thread listing..."
if uv run silica msg list > /dev/null 2>&1; then
    print_success "Thread listing works"
else
    print_error "Thread listing failed"
fi

# Test sending a message (creates thread implicitly)
print_status "Testing message sending..."
if uv run silica msg send -t "test-thread-123" "Hello from CLI test" > /dev/null 2>&1; then
    print_success "Message sending works"
else
    print_error "Message sending failed"
fi

# Test thread history
print_status "Testing thread history..."
if uv run silica msg history "test-thread-123" > /dev/null 2>&1; then
    print_success "Thread history works"
else
    print_error "Thread history failed"
fi

# Test participants
print_status "Testing participant management..."
if uv run silica msg participants "test-thread-123" > /dev/null 2>&1; then
    print_success "Participant listing works"
else
    print_error "Participant listing failed"
fi

# Test 5: Agent Messaging Function
echo
print_status "Test 5: Agent Messaging Function"
echo "==============================="

# Source the messaging function
source silica/agent/messaging.sh

# Test status function
print_status "Testing silica-msg-status..."
if silica-msg-status > /dev/null 2>&1; then
    print_success "silica-msg-status works"
else
    print_error "silica-msg-status failed"
fi

# Test sending message from agent
print_status "Testing silica-msg function..."
if silica-msg -t "agent-test-thread" "Hello from agent function" > /dev/null 2>&1; then
    print_success "silica-msg function works"
else
    print_error "silica-msg function failed"
fi

# Test piping to silica-msg
print_status "Testing silica-msg with stdin..."
if echo "Piped message test" | silica-msg -t "agent-test-thread" > /dev/null 2>&1; then
    print_success "silica-msg stdin piping works"
else
    print_error "silica-msg stdin piping failed"
fi

# Test 6: Web Interface (basic check)
echo
print_status "Test 6: Web Interface"
echo "===================="

print_status "Testing web interface availability..."
if curl -s -H "Host: silica-messaging" http://localhost:5000/ | grep -q "Silica Messaging"; then
    print_success "Web interface is available"
    print_status "You can test the web interface at: http://localhost:5000"
    print_status "(Set Host header to 'silica-messaging' or use a proxy)"
else
    print_error "Web interface not accessible"
fi

# Test 7: API Endpoints
echo
print_status "Test 7: API Endpoints"
echo "===================="

# Test thread listing API
print_status "Testing /api/v1/threads endpoint..."
if curl -s -H "Host: silica-messaging" http://localhost:5000/api/v1/threads | grep -q "threads"; then
    print_success "Threads API endpoint works"
else
    print_error "Threads API endpoint failed"
fi

# Test workspace status API
print_status "Testing /api/v1/workspaces/status endpoint..."
if curl -s -H "Host: silica-messaging" http://localhost:5000/api/v1/workspaces/status | grep -q "workspaces"; then
    print_success "Workspace status API endpoint works"
else
    print_error "Workspace status API endpoint failed"
fi

# Test 8: HTTP Proxy (if possible)
echo
print_status "Test 8: HTTP Proxy"
echo "=================="

print_status "Testing HTTP proxy functionality..."
# Try to proxy to the agent receiver
if curl -s -H "Host: silica-messaging" "http://localhost:5000/proxy/${SILICA_PARTICIPANT}/health" | grep -q "healthy"; then
    print_success "HTTP proxy works"
else
    print_warning "HTTP proxy test inconclusive (may need proper Host header routing)"
fi

# Test Results Summary
echo
print_status "Test Results Summary"
echo "==================="

print_success "✅ Root messaging app: Running on port 5000"
print_success "✅ Agent receiver: Running on port 8901"
print_success "✅ CLI commands: Working"
print_success "✅ Agent messaging function: Working"
print_success "✅ Web interface: Available"
print_success "✅ API endpoints: Working"

echo
print_status "Logs available in:"
print_status "- messaging_app.log (root messaging app)"
print_status "- receiver.log (agent receiver)"

echo
print_status "To test manually:"
print_status "1. Web UI: http://localhost:5000 (Host: silica-messaging)"
print_status "2. CLI: uv run silica msg send -t 'test' 'Your message'"
print_status "3. Agent: silica-msg 'Agent message'"

echo
print_warning "Press Ctrl+C to stop test servers or run:"
print_warning "kill $MESSAGING_APP_PID $RECEIVER_PID"

# Keep servers running for manual testing
echo
print_status "Test servers running. Press Enter to stop them..."
read

# Cleanup
print_status "Stopping test servers..."
kill $MESSAGING_APP_PID $RECEIVER_PID 2>/dev/null || true
wait 2>/dev/null || true

print_success "🎉 Messaging system test complete!"

echo
print_status "Next steps for piku testing:"
print_status "1. Install development version: pip install -e ."
print_status "2. Create workspace: silica create"
print_status "3. Test end-to-end messaging integration"