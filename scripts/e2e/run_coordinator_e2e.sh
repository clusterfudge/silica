#!/bin/bash
# Run a full coordinator E2E test with real agents
#
# This script:
# 1. Creates a coordination session
# 2. Launches the coordinator agent in tmux
# 3. Injects a task for it to accomplish using workers
#
# The coordinator should spawn workers, delegate tasks, and report results.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SILICA_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

SESSION_NAME="coord-e2e-test"
WORKER_SESSION_PREFIX="coord-e2e-worker"

echo "=============================================="
echo "Coordinator E2E Test"
echo "=============================================="
echo "This will launch a coordinator that spawns workers."
echo "Watch the coordinator delegate tasks and aggregate results."
echo ""
echo "Sessions:"
echo "  - Coordinator: $SESSION_NAME"
echo "  - Workers: ${WORKER_SESSION_PREFIX}-*"
echo ""

# Kill any existing sessions
tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true
for i in 1 2 3 4 5; do
    tmux kill-session -t "${WORKER_SESSION_PREFIX}-$i" 2>/dev/null || true
done

cd "$SILICA_DIR"

# Create the coordinator session with hdev
echo "Starting coordinator agent..."
tmux new-session -d -s "$SESSION_NAME" -c "$SILICA_DIR" \
    "uv run silica coordinator new --name 'E2E Test Coordinator'"

echo ""
echo "Coordinator started in tmux session: $SESSION_NAME"
echo ""
echo "To watch: tmux attach -t $SESSION_NAME"
echo "To kill:  tmux kill-session -t $SESSION_NAME"
echo ""
echo "Once the coordinator is ready, it will prompt for input."
echo "Give it a task like:"
echo ""
echo "  Create a simple Python function that calculates fibonacci numbers,"
echo "  and another function that checks if a number is prime. Have separate"  
echo "  workers implement each function, then report back what they created."
echo ""
