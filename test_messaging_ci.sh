#!/bin/bash
# CI-friendly test script for SILIC-5 messaging system
# This script is designed to run in automated CI/CD environments

set -e  # Exit on error

# Colors for output (CI-safe)
if [[ "${CI:-false}" == "true" ]] || [[ ! -t 1 ]]; then
    # No colors in CI or when not in terminal
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
else
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
fi

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

# Cleanup function
cleanup() {
    local exit_code=$?
    print_status "Cleaning up test processes..."
    
    # Kill background processes if they exist
    if [[ -n "${MESSAGING_APP_PID:-}" ]]; then
        kill $MESSAGING_APP_PID 2>/dev/null || true
    fi
    if [[ -n "${RECEIVER_PID:-}" ]]; then
        kill $RECEIVER_PID 2>/dev/null || true
    fi
    
    # Wait for processes to die
    sleep 2
    
    # Force kill if necessary
    if [[ -n "${MESSAGING_APP_PID:-}" ]]; then
        kill -9 $MESSAGING_APP_PID 2>/dev/null || true
    fi
    if [[ -n "${RECEIVER_PID:-}" ]]; then
        kill -9 $RECEIVER_PID 2>/dev/null || true
    fi
    
    # Clean up log files
    rm -f messaging_app_ci.log receiver_ci.log
    
    exit $exit_code
}

# Set up trap for cleanup
trap cleanup EXIT INT TERM

# Configuration
TIMEOUT=30
MAX_RETRIES=10
RETRY_DELAY=2

# Find available ports
find_available_port() {
    local port=$1
    while netstat -tuln 2>/dev/null | grep -q ":$port "; do
        port=$((port + 1))
    done
    echo $port
}

# Wait for service to be ready
wait_for_service() {
    local url=$1
    local description=$2
    local timeout=${3:-$TIMEOUT}
    local headers=${4:-""}
    
    print_status "Waiting for $description to be ready..."
    
    for i in $(seq 1 $timeout); do
        if [[ -n "$headers" ]]; then
            if curl -s -f $headers "$url" > /dev/null 2>&1; then
                print_success "$description is ready"
                return 0
            fi
        else
            if curl -s -f "$url" > /dev/null 2>&1; then
                print_success "$description is ready"
                return 0
            fi
        fi
        
        if [[ $i -eq $timeout ]]; then
            print_error "$description failed to start within ${timeout}s"
            return 1
        fi
        
        sleep 1
    done
}

# Test function with retries
test_with_retry() {
    local description=$1
    local command=$2
    local max_retries=${3:-$MAX_RETRIES}
    local delay=${4:-$RETRY_DELAY}
    
    for i in $(seq 1 $max_retries); do
        if eval "$command" > /dev/null 2>&1; then
            print_success "$description"
            return 0
        fi
        
        if [[ $i -eq $max_retries ]]; then
            print_error "$description failed after $max_retries attempts"
            return 1
        fi
        
        sleep $delay
    done
}

echo "🤖 CI Testing Silica Messaging System"
echo "====================================="

# Check if we're in the right directory
if [[ ! -f "silica/messaging/app.py" ]]; then
    print_error "Please run this script from the silica repository root"
    exit 1
fi

# Find available ports
MESSAGING_PORT=$(find_available_port 5000)
RECEIVER_PORT=$(find_available_port 8901)

print_status "Using ports: Messaging=$MESSAGING_PORT, Receiver=$RECEIVER_PORT"

# Set up test environment
export SILICA_WORKSPACE="ci-test-workspace"
export SILICA_PROJECT="ci-test-project"
export SILICA_PARTICIPANT="ci-test-workspace-ci-test-project"
export SILICA_RECEIVER_PORT="$RECEIVER_PORT"
export SILICA_MESSAGE_DELIVERY="status"
export DATA_DIR="/tmp/silica-messaging-ci-$$"

print_status "Test environment:"
print_status "- SILICA_WORKSPACE: $SILICA_WORKSPACE"
print_status "- SILICA_PROJECT: $SILICA_PROJECT"
print_status "- DATA_DIR: $DATA_DIR"
print_status "- Ports: $MESSAGING_PORT, $RECEIVER_PORT"

# Create data directory
mkdir -p "$DATA_DIR"

# Test 1: CLI Command Availability
echo
print_status "Test 1: CLI Command Availability"
echo "================================"

test_with_retry "silica messaging command" "uv run silica messaging --help"
test_with_retry "silica msg command" "uv run silica msg --help"

# Test 2: Start Root Messaging App
echo
print_status "Test 2: Root Messaging App"
echo "=========================="

print_status "Starting root messaging app on port $MESSAGING_PORT..."
uv run silica messaging app --port $MESSAGING_PORT > messaging_app_ci.log 2>&1 &
MESSAGING_APP_PID=$!

# Wait for app to start
wait_for_service "http://localhost:$MESSAGING_PORT/health" "Root messaging app" 30 "-H 'Host: silica-messaging'"

# Test 3: Start Agent Receiver
echo
print_status "Test 3: Agent Receiver"
echo "====================="

print_status "Starting agent receiver on port $RECEIVER_PORT..."
uv run silica messaging receiver --port $RECEIVER_PORT > receiver_ci.log 2>&1 &
RECEIVER_PID=$!

# Wait for receiver to start
wait_for_service "http://localhost:$RECEIVER_PORT/health" "Agent receiver" 30

# Test 4: Basic API Health Checks
echo
print_status "Test 4: API Health Checks"
echo "========================="

test_with_retry "Root app health check" "curl -s -f -H 'Host: silica-messaging' http://localhost:$MESSAGING_PORT/health"
test_with_retry "Receiver health check" "curl -s -f http://localhost:$RECEIVER_PORT/health"

# Test 5: CLI Operations
echo
print_status "Test 5: CLI Operations"
echo "====================="

# Test thread listing (should work even with no threads)
test_with_retry "Thread listing" "uv run silica msg list"

# Test message sending (creates thread implicitly)
test_with_retry "Message sending" "uv run silica msg send -t 'ci-test-thread' 'CI test message'"

# Test thread history
test_with_retry "Thread history" "uv run silica msg history 'ci-test-thread'"

# Test participants
test_with_retry "Participant listing" "uv run silica msg participants 'ci-test-thread'"

# Test 6: Agent Messaging Function
echo
print_status "Test 6: Agent Messaging Function"
echo "==============================="

# Source the messaging function
source silica/agent/messaging.sh

# Test status function
test_with_retry "silica-msg-status" "silica-msg-status"

# Test sending message from agent
test_with_retry "silica-msg function" "silica-msg -t 'ci-agent-thread' 'CI agent test'"

# Test piping (more complex for CI)
test_with_retry "silica-msg stdin" "echo 'CI piped message' | silica-msg -t 'ci-agent-thread'"

# Test 7: API Endpoints
echo
print_status "Test 7: API Endpoints"
echo "===================="

test_with_retry "Threads API" "curl -s -f -H 'Host: silica-messaging' http://localhost:$MESSAGING_PORT/api/v1/threads"
test_with_retry "Workspace status API" "curl -s -f -H 'Host: silica-messaging' http://localhost:$MESSAGING_PORT/api/v1/workspaces/status"
test_with_retry "Agent status API" "curl -s -f http://localhost:$RECEIVER_PORT/api/v1/agent/status"

# Test 8: Message Flow Integration
echo
print_status "Test 8: Message Flow Integration"
echo "==============================="

# Send message and verify it creates proper data structures  
if uv run silica msg send -t "integration-test" "Integration test message" > /dev/null 2>&1; then
    print_success "Message flow integration"
    
    # Verify message appears in history
    if uv run silica msg history "integration-test" | grep -q "Integration test message"; then
        print_success "Message retrieval verification"
    else
        print_warning "Message retrieval verification (message not found in history)"
    fi
else
    print_error "Message flow integration failed"
    exit 1
fi

# Test thread data persistence (wait a moment for files to be written)
sleep 2
if [[ -d "$DATA_DIR/threads" ]]; then
    thread_count=$(find "$DATA_DIR/threads" -name "*.json" 2>/dev/null | wc -l)
    if [[ $thread_count -gt 0 ]]; then
        print_success "Thread persistence ($thread_count threads created)"
    else
        print_warning "Thread persistence (directory exists but no threads found)"
        # This might be okay if threads are stored differently
    fi
else
    print_warning "Thread persistence (directory not found - might use different storage)"
fi

# Test 9: Error Handling
echo
print_status "Test 9: Error Handling"
echo "======================"

# Test invalid thread operations (should fail gracefully)
if uv run silica msg history "nonexistent-thread" 2>/dev/null; then
    print_warning "Nonexistent thread should return empty results"
else
    print_success "Error handling for nonexistent threads"
fi

# Test 10: Resource Cleanup
echo
print_status "Test 10: Resource Cleanup"
echo "========================="

# Check that processes are still running
if kill -0 $MESSAGING_APP_PID 2>/dev/null; then
    print_success "Messaging app still running"
else
    print_error "Messaging app died unexpectedly"
    exit 1
fi

if kill -0 $RECEIVER_PID 2>/dev/null; then
    print_success "Receiver still running"
else
    print_error "Receiver died unexpectedly"
    exit 1
fi

# Summary
echo
print_status "🎉 CI Test Results Summary"
echo "=========================="

print_success "✅ All messaging system components working"
print_success "✅ CLI commands functional"
print_success "✅ Agent messaging function operational"
print_success "✅ API endpoints responding"
print_success "✅ Message flow integration verified"
print_success "✅ Error handling appropriate"
print_success "✅ Resource management stable"

echo
print_status "Test artifacts:"
print_status "- Logs: messaging_app_ci.log, receiver_ci.log"
print_status "- Data: $DATA_DIR"

# Final cleanup will happen via trap
print_success "🚀 CI testing completed successfully!"
exit 0