#!/bin/bash
# Silica Agent Messaging Functions
# This file is sourced by agent workspaces to enable messaging functionality

# silica-msg - Send messages to thread participants
silica-msg() {
    local usage="silica-msg - Send messages to thread participants

Usage:
  silica-msg [OPTIONS] [MESSAGE]
  echo \"message\" | silica-msg [OPTIONS]
  command | silica-msg [OPTIONS]

Options:
  -t, --thread THREAD_ID   Send to specific thread (default: \$SILICA_THREAD_ID or workspace name)
  -s, --sender SENDER      Specify sender identity (default: \$SILICA_PARTICIPANT)
  -p, --priority LEVEL     Set priority: normal, high (default: normal)
  -f, --format FORMAT      Message format: text, code, json (default: text)
  -h, --help              Show this help message

Examples:
  # Send a simple message to current thread
  silica-msg \"Processing complete\"
  
  # Send command output to current thread
  ls -la | silica-msg
  
  # Send to specific thread
  silica-msg -t thread123 \"Status update: 50% complete\"
  
  # Send with specific sender identity (for agent-to-agent communication)
  silica-msg -s \"my-agent-workspace-project\" \"Hello from my agent\"
  
  # Send code output with formatting
  cat script.py | silica-msg -f code
  
  # High priority alert
  silica-msg -p high \"Critical: Disk space low\"

Environment:
  SILICA_THREAD_ID       Current thread ID (set by incoming messages)
  SILICA_WORKSPACE       Current workspace name
  SILICA_PROJECT         Current project name
  SILICA_PARTICIPANT     Agent's participant ID (\${workspace}-\${project})
  SILICA_LAST_SENDER     Sender of last received message

Notes:
  - Threads are created implicitly when first referenced
  - If no thread is specified, uses SILICA_THREAD_ID or workspace name as default
  - Messages fan out to all participants in the thread
  - Supports agent-to-agent communication via sender parameter
  - Large outputs are automatically truncated with a note"

    local message=""
    local thread_id="${SILICA_THREAD_ID:-}"
    local sender="${SILICA_PARTICIPANT:-}"
    local priority="normal"
    local format="text"
    local workspace="${SILICA_WORKSPACE}"
    local project="${SILICA_PROJECT}"

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -t|--thread)
                thread_id="$2"
                shift 2
                ;;
            -s|--sender)
                sender="$2"
                shift 2
                ;;
            -p|--priority)
                priority="$2"
                shift 2
                ;;
            -f|--format)
                format="$2"
                shift 2
                ;;
            -h|--help)
                echo "$usage"
                return 0
                ;;
            -*)
                echo "Error: Unknown option $1" >&2
                echo "$usage" >&2
                return 1
                ;;
            *)
                # Remaining arguments are the message
                message="$*"
                break
                ;;
        esac
    done

    # Get message from stdin if not provided as argument
    if [[ -z "$message" ]]; then
        if [[ -t 0 ]]; then
            echo "Error: No message provided and stdin is a terminal" >&2
            echo "Usage: silica-msg \"message\" or echo \"message\" | silica-msg" >&2
            return 1
        else
            # Read from stdin
            message=$(cat)
        fi
    fi

    # Truncate very large messages
    if [[ ${#message} -gt 10000 ]]; then
        message="${message:0:10000}... [truncated - full output too large]"
    fi

    # Use default thread if none specified
    if [[ -z "$thread_id" ]]; then
        thread_id="${workspace:-general}"
        echo "Using default thread: $thread_id" >&2
    fi

    # Set default sender if not specified
    if [[ -z "$sender" ]]; then
        if [[ -n "$workspace" ]] && [[ -n "$project" ]]; then
            sender="${workspace}-${project}"
        else
            sender="agent"
        fi
    fi

    # Create JSON payload using proper escaping
    local payload
    payload=$(python3 -c "
import json
import sys

# Read message from arguments, handling newlines properly
message = '''$message'''

data = {
    'thread_id': '$thread_id',
    'message': message,
    'sender': '$sender',
    'metadata': {
        'format': '$format', 
        'priority': '$priority'
    }
}

print(json.dumps(data))
" 2>/dev/null)

    if [[ $? -ne 0 ]]; then
        echo "Error: Failed to create message payload" >&2
        return 1
    fi

    # Send to root messaging app
    local response
    response=$(curl -s -X POST http://localhost/api/v1/messages/send \
        -H "Host: silica-messaging" \
        -H "Content-Type: application/json" \
        -d "$payload")

    # Check response
    if [[ $? -eq 0 ]]; then
        local status
        status=$(echo "$response" | python3 -c "
import sys
import json
try:
    data = json.load(sys.stdin)
    if 'message_id' in data:
        print('success')
        delivery_statuses = data.get('delivery_statuses', [])
        if delivery_statuses:
            print('Delivery:', ', '.join(delivery_statuses), file=sys.stderr)
    else:
        print('error')
        if 'error' in data:
            print('Error:', data['error'], file=sys.stderr)
except:
    print('error')
" 2>&1)
        
        if [[ "$status" == "success" ]]; then
            echo "Message sent successfully to thread '$thread_id'" >&2
        else
            echo "Warning: Message may not have been sent properly" >&2
            echo "Response: $response" >&2
        fi
    else
        echo "Error: Failed to send message" >&2
        echo "Check if messaging app is running: curl -s http://localhost/health -H 'Host: silica-messaging'" >&2
        return 1
    fi
}

# Export function so it's available in subshells
export -f silica-msg

# Helper function to check messaging system status
silica-msg-status() {
    echo "Checking messaging system status..."
    echo "Workspace: ${SILICA_WORKSPACE:-'not set'}"
    echo "Project: ${SILICA_PROJECT:-'not set'}"
    echo "Current Thread: ${SILICA_THREAD_ID:-'not set (will use workspace name)'}"
    echo "Participant ID: ${SILICA_PARTICIPANT:-'not set'}"
    echo "Last Sender: ${SILICA_LAST_SENDER:-'not set'}"
    echo
    
    # Check root messaging app
    local health_response
    health_response=$(curl -s http://localhost/health -H "Host: silica-messaging" 2>/dev/null)
    if [[ $? -eq 0 ]]; then
        echo "Root messaging app: ✓ Running"
        echo "Response: $health_response"
    else
        echo "Root messaging app: ✗ Not accessible"
    fi
    
    # List available threads
    echo
    echo "Available threads:"
    curl -s http://localhost/api/v1/threads -H "Host: silica-messaging" | \
        python3 -c "
import sys
import json
try:
    data = json.load(sys.stdin)
    threads = data.get('threads', [])
    if threads:
        for thread in threads[:5]:  # Show first 5
            print(f\"  {thread['thread_id']}: {thread['title']} ({len(thread.get('participants', []))} participants)\")
        if len(threads) > 5:
            print(f\"  ... and {len(threads) - 5} more\")
    else:
        print('  No threads found')
except:
    print('  Error retrieving threads')
" 2>/dev/null
}

# Export status function too
export -f silica-msg-status

# Helper function to list participants in current thread
silica-msg-participants() {
    local thread_id="${SILICA_THREAD_ID:-${SILICA_WORKSPACE:-general}}"
    
    echo "Participants in thread '$thread_id':"
    curl -s "http://localhost/api/v1/threads/$thread_id/participants" -H "Host: silica-messaging" | \
        python3 -c "
import sys
import json
try:
    data = json.load(sys.stdin)
    participants = data.get('participants', [])
    if participants:
        for p in participants:
            print(f\"  - {p}\")
    else:
        print('  No participants found')
except:
    print('  Error retrieving participants or thread not found')
" 2>/dev/null
}

# Export participants function
export -f silica-msg-participants

# Set up environment variables if not already set
if [[ -n "$SILICA_WORKSPACE" ]] && [[ -n "$SILICA_PROJECT" ]]; then
    export SILICA_PARTICIPANT="${SILICA_WORKSPACE}-${SILICA_PROJECT}"
fi