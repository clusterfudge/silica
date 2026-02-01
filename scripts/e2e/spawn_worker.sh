#!/bin/bash
# Spawn a worker process in tmux for E2E testing
#
# Usage: ./spawn_worker.sh <session_name> <invite_url> [agent_id]
#
# Example:
#   ./spawn_worker.sh e2e-worker-1 "data:application/json;base64,..." agent-abc123

set -e

SESSION_NAME="${1:-e2e-worker}"
INVITE_URL="$2"
AGENT_ID="${3:-unknown}"

# Use environment variable if set, otherwise default to local
DEADDROP_URL="${DEADDROP_URL:-http://127.0.0.1:8765}"

if [ -z "$INVITE_URL" ]; then
    echo "Usage: $0 <session_name> <invite_url> [agent_id]"
    echo "  session_name: tmux session name"
    echo "  invite_url: DEADDROP_INVITE_URL value"
    echo "  agent_id: COORDINATION_AGENT_ID value (optional)"
    echo ""
    echo "Environment variables:"
    echo "  DEADDROP_URL: Override deaddrop server URL (default: http://127.0.0.1:8765)"
    exit 1
fi

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SILICA_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Check if tmux session exists
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "Warning: tmux session '$SESSION_NAME' already exists. Killing it..."
    tmux kill-session -t "$SESSION_NAME"
fi

echo "Starting worker in tmux session: $SESSION_NAME"
echo "  Agent ID: $AGENT_ID"
echo "  Deaddrop URL: $DEADDROP_URL"

# Create tmux session and run worker
tmux new-session -d -s "$SESSION_NAME" -c "$SILICA_DIR" \
    "DEADDROP_INVITE_URL='$INVITE_URL' COORDINATION_AGENT_ID='$AGENT_ID' DEADDROP_URL='$DEADDROP_URL' uv run python scripts/e2e/minimal_worker.py; read -p 'Press Enter to close...'"

echo "Worker started. View with: tmux attach -t $SESSION_NAME"
echo "Kill with: tmux kill-session -t $SESSION_NAME"
