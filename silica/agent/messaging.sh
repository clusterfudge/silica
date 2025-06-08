#!/bin/bash
# Silica Agent Messaging Functions
# This file is sourced by agent workspaces to enable messaging functionality

# silica-msg - Send messages from agent to user
silica-msg() {
    local usage="silica-msg - Send messages from agent to user

Usage:
  silica-msg [OPTIONS] [MESSAGE]
  echo \"message\" | silica-msg [OPTIONS]
  command | silica-msg [OPTIONS]

Options:
  -t, --thread THREAD_ID   Send to specific thread (default: \$SILICA_THREAD_ID)
  -n, --new-thread TITLE   Create new thread with title
  -p, --priority LEVEL     Set priority: normal, high (default: normal)
  -f, --format FORMAT      Message format: text, code, json (default: text)
  -h, --help              Show this help message

Examples:
  # Send a simple message to current thread
  silica-msg \"Processing complete\"
  
  # Send command output to current thread
  ls -la | silica-msg
  
  # Send to specific thread
  silica-msg -t abc123 \"Status update: 50% complete\"
  
  # Create new thread for errors
  silica-msg -n \"Error Report\" \"Failed to process file\"
  
  # Send code output with formatting
  cat script.py | silica-msg -f code
  
  # High priority alert
  silica-msg -p high \"Critical: Disk space low\"

Environment:
  SILICA_THREAD_ID       Current thread ID (set by incoming messages)
  SILICA_WORKSPACE       Current workspace name
  SILICA_PROJECT         Current project name
  SILICA_PARTICIPANT     Agent's participant ID (\${workspace}-\${project})
  SILICA_LAST_SENDER     Sender of last received message (always \"human\")

Notes:
  - If no thread is specified and SILICA_THREAD_ID is not set, 
    uses default thread with ID matching workspace name
  - Messages from stdin are sent as-is, preserving formatting
  - Large outputs are automatically truncated with a note"

    local message=""
    local thread_id="${SILICA_THREAD_ID:-}"
    local new_thread_title=""
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
            -n|--new-thread)
                new_thread_title="$2"
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

    # Validate environment
    if [[ -z "$workspace" ]] || [[ -z "$project" ]]; then
        echo "Error: SILICA_WORKSPACE and SILICA_PROJECT must be set" >&2
        echo "These should be set automatically in agent workspace environments" >&2
        return 1
    fi

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

    # Handle new thread creation
    if [[ -n "$new_thread_title" ]]; then
        # Create new thread first
        local create_response
        create_response=$(curl -s -X POST http://localhost/api/v1/threads/create \
            -H "Host: silica-messaging" \
            -H "Content-Type: application/json" \
            -d "$(printf '{"workspace":"%s","project":"%s","title":"%s"}' "$workspace" "$project" "$new_thread_title")")
        
        if [[ $? -eq 0 ]]; then
            # Extract thread_id from response
            thread_id=$(echo "$create_response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('thread_id', ''))" 2>/dev/null)
            if [[ -n "$thread_id" ]]; then
                export SILICA_THREAD_ID="$thread_id"
                echo "Created new thread: $new_thread_title ($thread_id)" >&2
            else
                echo "Error: Failed to create new thread" >&2
                return 1
            fi
        else
            echo "Error: Failed to create new thread" >&2
            return 1
        fi
    fi

    # Use default thread if none specified
    if [[ -z "$thread_id" ]]; then
        thread_id="$workspace"
        echo "Using default thread: $thread_id" >&2
        
        # Ensure default thread exists
        curl -s -X POST http://localhost/api/v1/threads/create \
            -H "Host: silica-messaging" \
            -H "Content-Type: application/json" \
            -d "$(printf '{"workspace":"%s","project":"%s","title":"Default","thread_id":"%s"}' "$workspace" "$project" "$thread_id")" \
            > /dev/null 2>&1
    fi

    # Prepare message payload
    local payload
    payload=$(python3 -c "
import json
import sys
data = {
    'workspace': '$workspace',
    'project': '$project', 
    'thread_id': '$thread_id',
    'message': '''$message''',
    'type': 'info',
    'metadata': {'format': '$format', 'priority': '$priority'}
}
print(json.dumps(data))
" 2>/dev/null)

    if [[ $? -ne 0 ]]; then
        echo "Error: Failed to create message payload" >&2
        return 1
    fi

    # Send to root messaging app
    local response
    response=$(curl -s -X POST http://localhost/api/v1/messages/agent-response \
        -H "Host: silica-messaging" \
        -H "Content-Type: application/json" \
        -d "$payload")

    # Check response
    if [[ $? -eq 0 ]]; then
        local status
        status=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('status', 'unknown'))" 2>/dev/null)
        if [[ "$status" == "received" ]]; then
            echo "Message sent successfully" >&2
        else
            echo "Warning: Message may not have been received properly" >&2
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
    echo "Current Thread: ${SILICA_THREAD_ID:-'not set'}"
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
}

# Export status function too
export -f silica-msg-status

# Set up environment variables if not already set
# These should be set by the workspace creation process
if [[ -z "$SILICA_WORKSPACE" ]] && [[ -n "$PWD" ]]; then
    # Try to infer from current directory if possible
    # This is a fallback - normally these should be explicitly set
    if [[ "$PWD" =~ /([^/]+)$ ]]; then
        echo "Warning: SILICA_WORKSPACE not set, inferring from PWD" >&2
    fi
fi

# Create default participant ID if workspace and project are available
if [[ -n "$SILICA_WORKSPACE" ]] && [[ -n "$SILICA_PROJECT" ]]; then
    export SILICA_PARTICIPANT="${SILICA_WORKSPACE}-${SILICA_PROJECT}"
fi