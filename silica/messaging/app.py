#!/usr/bin/env python3
"""
Silica Messaging App - Root messaging hub for agent communication

This Flask application serves as the central messaging hub for Silica workspaces.
It handles global thread management, message routing with participant fan-out,
and provides both API and web interfaces.
"""

import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, Response
import requests
from typing import Dict, List, Optional
import filelock

app = Flask(__name__)

# Configuration
DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/silica-messaging"))
THREADS_DIR = DATA_DIR / "threads"
MESSAGES_DIR = DATA_DIR / "messages"

# Ensure directories exist
THREADS_DIR.mkdir(parents=True, exist_ok=True)
MESSAGES_DIR.mkdir(parents=True, exist_ok=True)


class ThreadStorage:
    """File-based storage for global threads and messages with participant management"""

    @staticmethod
    def _get_thread_file(thread_id: str) -> Path:
        """Get the file path for a thread"""
        return THREADS_DIR / f"{thread_id}.json"

    @staticmethod
    def _get_thread_lock(thread_id: str) -> filelock.FileLock:
        """Get a file lock for thread operations"""
        lock_file = THREADS_DIR / f"{thread_id}.lock"
        return filelock.FileLock(lock_file)

    @staticmethod
    def thread_exists(thread_id: str) -> bool:
        """Check if a thread exists"""
        return ThreadStorage._get_thread_file(thread_id).exists()

    @staticmethod
    def create_thread(
        thread_id: str,
        title: Optional[str] = None,
        initial_participants: Optional[List[str]] = None,
    ) -> Dict:
        """Create a new global thread"""
        thread_file = ThreadStorage._get_thread_file(thread_id)

        if thread_file.exists():
            # Thread already exists, return existing
            with open(thread_file, "r") as f:
                return json.load(f)

        thread = {
            "thread_id": thread_id,
            "title": title or f"Thread {thread_id}",
            "participants": initial_participants or [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "active",
        }

        with ThreadStorage._get_thread_lock(thread_id):
            with open(thread_file, "w") as f:
                json.dump(thread, f, indent=2)

        return thread

    @staticmethod
    def get_thread(thread_id: str) -> Optional[Dict]:
        """Retrieve a specific thread"""
        thread_file = ThreadStorage._get_thread_file(thread_id)

        if not thread_file.exists():
            return None

        with open(thread_file, "r") as f:
            return json.load(f)

    @staticmethod
    def update_thread(thread_id: str, updates: Dict) -> bool:
        """Update thread properties"""
        thread_file = ThreadStorage._get_thread_file(thread_id)

        if not thread_file.exists():
            return False

        with ThreadStorage._get_thread_lock(thread_id):
            with open(thread_file, "r") as f:
                thread = json.load(f)

            thread.update(updates)
            thread["updated_at"] = datetime.now().isoformat()

            with open(thread_file, "w") as f:
                json.dump(thread, f, indent=2)

        return True

    @staticmethod
    def add_participant(thread_id: str, participant: str) -> bool:
        """Add a participant to a thread"""
        thread = ThreadStorage.get_thread(thread_id)
        if not thread:
            return False

        if participant not in thread["participants"]:
            thread["participants"].append(participant)
            return ThreadStorage.update_thread(
                thread_id, {"participants": thread["participants"]}
            )

        return True

    @staticmethod
    def remove_participant(thread_id: str, participant: str) -> bool:
        """Remove a participant from a thread"""
        thread = ThreadStorage.get_thread(thread_id)
        if not thread:
            return False

        if participant in thread["participants"]:
            thread["participants"].remove(participant)
            return ThreadStorage.update_thread(
                thread_id, {"participants": thread["participants"]}
            )

        return True

    @staticmethod
    def list_all_threads() -> List[Dict]:
        """List all global threads"""
        threads = []

        for thread_file in THREADS_DIR.glob("*.json"):
            if not thread_file.name.endswith(".lock"):
                with open(thread_file, "r") as f:
                    threads.append(json.load(f))

        # Sort by updated_at descending
        threads.sort(
            key=lambda x: x.get("updated_at", x.get("created_at", "")), reverse=True
        )
        return threads

    @staticmethod
    def save_message(thread_id: str, message: Dict) -> None:
        """Save a message to a thread"""
        thread_messages_dir = MESSAGES_DIR / thread_id
        thread_messages_dir.mkdir(parents=True, exist_ok=True)

        message_file = thread_messages_dir / f"{message['message_id']}.json"
        with open(message_file, "w") as f:
            json.dump(message, f, indent=2)

        # Update thread timestamp
        ThreadStorage.update_thread(thread_id, {})  # Just to update timestamp

    @staticmethod
    def get_messages(thread_id: str) -> List[Dict]:
        """Get all messages for a thread"""
        thread_messages_dir = MESSAGES_DIR / thread_id

        if not thread_messages_dir.exists():
            return []

        messages = []
        for message_file in thread_messages_dir.glob("*.json"):
            with open(message_file, "r") as f:
                messages.append(json.load(f))

        # Sort by timestamp ascending
        messages.sort(key=lambda x: x["timestamp"])
        return messages


def ensure_thread_with_participants(
    thread_id: str, sender: str, title: Optional[str] = None
) -> Dict:
    """Ensure thread exists and sender is a participant"""
    thread = ThreadStorage.get_thread(thread_id)

    if not thread:
        # Implicitly create thread
        thread = ThreadStorage.create_thread(thread_id, title, [sender])
    else:
        # Ensure sender is a participant
        ThreadStorage.add_participant(thread_id, sender)

    return ThreadStorage.get_thread(thread_id)


def fan_out_message(thread_id: str, message: Dict) -> List[str]:
    """Fan out message to all participants in a thread"""
    thread = ThreadStorage.get_thread(thread_id)
    if not thread:
        return []

    delivery_statuses = []

    for participant in thread["participants"]:
        if participant == message["sender"]:
            # Don't send message back to sender
            continue

        if participant == "human":
            # Human participant - no delivery needed for now
            # (web interface polls for new messages)
            delivery_statuses.append(f"{participant}:queued")
        else:
            # Agent participant - forward to agent receiver
            status = forward_to_agent_participant(participant, thread_id, message)
            delivery_statuses.append(f"{participant}:{status}")

    return delivery_statuses


def forward_to_agent_participant(
    participant: str, thread_id: str, message: Dict
) -> str:
    """Forward message to a specific agent participant"""
    try:
        # Participant format is "{workspace}-{project}"
        agent_host = participant

        response = requests.post(
            "http://localhost/api/v1/agent/receive",
            headers={
                "Host": agent_host,
                "X-Thread-ID": thread_id,
                "X-Message-ID": message["message_id"],
                "X-Sender": message["sender"],
                "Content-Type": "application/json",
            },
            json={
                "message": message["message"],
                "thread_id": thread_id,
                "sender": message["sender"],
                "metadata": message.get("metadata", {}),
            },
            timeout=10,
        )

        if response.status_code == 200:
            return "delivered"
        else:
            return "failed"
    except requests.RequestException:
        return "failed"


# API Routes


@app.route("/health")
def health_check():
    """Health check endpoint"""
    return jsonify(
        {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "data_dir": str(DATA_DIR),
        }
    )


@app.route("/api/v1/threads", methods=["GET"])
def list_threads():
    """List all global threads"""
    threads = ThreadStorage.list_all_threads()
    return jsonify({"threads": threads, "total": len(threads)})


@app.route("/api/v1/threads/<thread_id>", methods=["GET"])
def get_thread(thread_id):
    """Get a specific thread"""
    thread = ThreadStorage.get_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404

    return jsonify(thread)


@app.route("/api/v1/threads/<thread_id>/participants", methods=["GET"])
def get_participants(thread_id):
    """Get participants for a thread"""
    thread = ThreadStorage.get_thread(thread_id)
    if not thread:
        return jsonify({"error": "Thread not found"}), 404

    return jsonify({"participants": thread.get("participants", [])})


@app.route("/api/v1/threads/<thread_id>/participants", methods=["POST"])
def add_participant(thread_id):
    """Add a participant to a thread"""
    data = request.get_json()
    participant = data.get("participant")

    if not participant:
        return jsonify({"error": "participant is required"}), 400

    if not ThreadStorage.thread_exists(thread_id):
        return jsonify({"error": "Thread not found"}), 404

    success = ThreadStorage.add_participant(thread_id, participant)
    if success:
        return jsonify({"status": "added", "participant": participant})
    else:
        return jsonify({"error": "Failed to add participant"}), 500


@app.route("/api/v1/threads/<thread_id>/messages", methods=["GET"])
def get_messages(thread_id):
    """Get messages for a thread"""
    if not ThreadStorage.thread_exists(thread_id):
        return jsonify({"error": "Thread not found"}), 404

    messages = ThreadStorage.get_messages(thread_id)
    return jsonify({"messages": messages, "count": len(messages)})


@app.route("/api/v1/messages/send", methods=["POST"])
def send_message():
    """Send message (with implicit thread creation and participant fan-out)"""
    data = request.get_json()

    thread_id = data.get("thread_id")
    message_content = data.get("message")
    sender = data.get("sender", "human")  # Default to human, but allow agents
    title = data.get("title")  # Optional title for new threads
    metadata = data.get("metadata", {})

    if not all([thread_id, message_content]):
        return jsonify({"error": "thread_id and message are required"}), 400

    # Ensure thread exists and sender is participant
    ensure_thread_with_participants(thread_id, sender, title)

    # Create message record
    message = {
        "message_id": str(uuid.uuid4()),
        "thread_id": thread_id,
        "sender": sender,
        "message": message_content,
        "timestamp": datetime.now().isoformat(),
        "metadata": metadata,
    }

    # Save message
    ThreadStorage.save_message(thread_id, message)

    # Fan out to all participants
    delivery_statuses = fan_out_message(thread_id, message)

    return jsonify(
        {
            "message_id": message["message_id"],
            "thread_id": thread_id,
            "delivery_statuses": delivery_statuses,
            "timestamp": message["timestamp"],
        }
    )


@app.route("/api/v1/messages/agent-response", methods=["POST"])
def receive_agent_response():
    """Receive message from agent (legacy endpoint for backward compatibility)"""
    data = request.get_json()

    # Extract agent info for sender
    workspace = data.get("workspace")
    project = data.get("project")
    thread_id = data.get("thread_id")
    message_content = data.get("message")
    message_type = data.get("type", "info")

    if not all([workspace, project, thread_id, message_content]):
        return jsonify(
            {"error": "workspace, project, thread_id, and message are required"}
        ), 400

    # Use the new send_message endpoint internally
    sender = f"{workspace}-{project}"

    response_data = {
        "thread_id": thread_id,
        "message": message_content,
        "sender": sender,
        "metadata": {"type": message_type},
    }

    # Call the send_message logic directly
    request.json = response_data
    return send_message()


@app.route("/api/v1/workspaces/status")
def workspace_status():
    """List active workspaces with messaging enabled"""
    workspaces = {}

    # Analyze all threads to extract workspace information
    threads = ThreadStorage.list_all_threads()

    for thread in threads:
        for participant in thread.get("participants", []):
            if participant != "human" and "-" in participant:
                # Agent participant
                workspace_name = participant
                if workspace_name not in workspaces:
                    workspaces[workspace_name] = {
                        "name": workspace_name,
                        "connected": True,  # Assume connected for now
                        "active_threads": 0,
                    }
                workspaces[workspace_name]["active_threads"] += 1

    return jsonify({"workspaces": list(workspaces.values())})


# HTTP Proxy for agent endpoints
@app.route(
    "/proxy/<workspace_project>/<path:agent_path>",
    methods=["GET", "POST", "PUT", "DELETE"],
)
def proxy_to_agent(workspace_project, agent_path):
    """Proxy requests to agent workspace endpoints"""
    try:
        # Forward request to localhost with proper Host header
        agent_host = workspace_project
        url = f"http://localhost/{agent_path}"

        # Prepare headers
        headers = dict(request.headers)
        headers["Host"] = agent_host

        # Forward request based on method
        if request.method == "GET":
            response = requests.get(
                url, headers=headers, params=request.args, stream=True, timeout=30
            )
        elif request.method == "POST":
            response = requests.post(
                url, headers=headers, json=request.get_json(), stream=True, timeout=30
            )
        elif request.method == "PUT":
            response = requests.put(
                url, headers=headers, json=request.get_json(), stream=True, timeout=30
            )
        elif request.method == "DELETE":
            response = requests.delete(url, headers=headers, stream=True, timeout=30)
        else:
            # Handle other methods
            response = requests.request(
                request.method,
                url,
                headers=headers,
                data=request.get_data(),
                stream=True,
                timeout=30,
            )

        # Stream response back
        return Response(
            response.iter_content(chunk_size=1024),
            status=response.status_code,
            headers=dict(response.headers),
        )
    except requests.RequestException as e:
        return jsonify({"error": f"Proxy error: {str(e)}"}), 502


# Pure CSS-based web interface
WEB_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Silica Messaging</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/purecss@3.0.0/build/pure-min.css">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/purecss@3.0.0/build/grids-responsive-min.css">
    <style>
        .email-container { min-height: 100vh; }
        .email-nav { background: #f7f7f7; padding: 1em; }
        .email-list { background: #fff; border-right: 1px solid #ddd; padding: 0; overflow-y: auto; }
        .email-content { background: #fff; padding: 1em; overflow-y: auto; }
        .thread-item { padding: 1em; border-bottom: 1px solid #eee; cursor: pointer; }
        .thread-item:hover, .thread-item.active { background-color: #e3f2fd; }
        .message { padding: 1em; margin-bottom: 1em; border-radius: 5px; }
        .message.human { background-color: #f3e5f5; border-left: 3px solid #9c27b0; }
        .message.agent { background-color: #e8f5e8; border-left: 3px solid #4caf50; }
        .message-sender { font-weight: bold; margin-bottom: 0.5em; }
        .message-time { font-size: 0.8em; color: #666; }
        .message-content { margin: 0.5em 0; }
        .message-form { margin-top: 1em; }
        .thread-header { padding: 1em; border-bottom: 1px solid #ddd; background: #f9f9f9; }
        .new-thread-form { padding: 1em; border-bottom: 1px solid #ddd; }
        .status-bar { background: #2196f3; color: white; padding: 0.5em; text-align: center; }
    </style>
</head>
<body>
    <div class="pure-g email-container">
        <!-- Navigation -->
        <div class="pure-u-1">
            <div class="status-bar">
                <strong>Silica Messaging</strong> - Global Thread Communication
                <span id="statusText" style="margin-left: 1em;">Loading...</span>
            </div>
        </div>
        
        <!-- Thread List -->
        <div class="pure-u-1 pure-u-md-1-3">
            <div class="email-list">
                <div class="new-thread-form">
                    <form class="pure-form" onsubmit="createNewThread(event)">
                        <input type="text" id="newThreadId" placeholder="Thread ID" class="pure-input-1" required>
                        <input type="text" id="newThreadTitle" placeholder="Title (optional)" class="pure-input-1">
                        <button type="submit" class="pure-button pure-button-primary pure-input-1">New Thread</button>
                    </form>
                </div>
                <div id="threadList"></div>
            </div>
        </div>
        
        <!-- Message Area -->
        <div class="pure-u-1 pure-u-md-2-3">
            <div class="email-content">
                <div class="thread-header" id="threadHeader" style="display: none;">
                    <h3 id="threadTitle">Select a thread</h3>
                    <div id="threadParticipants"></div>
                </div>
                
                <div id="messageList"></div>
                
                <div class="message-form" id="messageForm" style="display: none;">
                    <form class="pure-form" onsubmit="sendMessage(event)">
                        <textarea id="messageInput" placeholder="Type your message..." 
                                  class="pure-input-1" rows="3" required></textarea>
                        <br>
                        <button type="submit" class="pure-button pure-button-primary">Send Message</button>
                        <label style="margin-left: 1em;">
                            <input type="text" id="senderInput" placeholder="Sender (default: human)" 
                                   class="pure-input-1-3" value="human">
                        </label>
                    </form>
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentThreadId = '';
        let lastMessageCount = 0;
        
        // Load threads on page load
        function loadThreads() {
            fetch('/api/v1/threads')
                .then(r => r.json())
                .then(data => {
                    const threadList = document.getElementById('threadList');
                    threadList.innerHTML = '';
                    
                    document.getElementById('statusText').textContent = 
                        `${data.threads.length} threads available`;
                    
                    data.threads.forEach(thread => {
                        const div = document.createElement('div');
                        div.className = 'thread-item';
                        if (thread.thread_id === currentThreadId) {
                            div.classList.add('active');
                        }
                        div.onclick = () => selectThread(thread.thread_id, thread.title);
                        
                        div.innerHTML = `
                            <strong>${thread.title}</strong><br>
                            <small>ID: ${thread.thread_id}</small><br>
                            <small>${thread.participants.length} participant(s)</small>
                        `;
                        threadList.appendChild(div);
                    });
                })
                .catch(err => {
                    document.getElementById('statusText').textContent = 'Error loading threads';
                    console.error('Error loading threads:', err);
                });
        }
        
        function selectThread(threadId, title) {
            currentThreadId = threadId;
            document.getElementById('threadTitle').textContent = title;
            document.getElementById('threadHeader').style.display = 'block';
            document.getElementById('messageForm').style.display = 'block';
            
            // Update active thread highlighting
            document.querySelectorAll('.thread-item').forEach(item => {
                item.classList.remove('active');
            });
            event.target.closest('.thread-item').classList.add('active');
            
            loadMessages();
            loadParticipants();
        }
        
        function loadMessages() {
            if (!currentThreadId) return;
            
            fetch(`/api/v1/threads/${currentThreadId}/messages`)
                .then(r => r.json())
                .then(data => {
                    const messageList = document.getElementById('messageList');
                    
                    // Only update if message count changed
                    if (data.messages.length !== lastMessageCount) {
                        messageList.innerHTML = '';
                        lastMessageCount = data.messages.length;
                        
                        data.messages.forEach(msg => {
                            const div = document.createElement('div');
                            const isHuman = msg.sender === 'human';
                            div.className = `message ${isHuman ? 'human' : 'agent'}`;
                            
                            div.innerHTML = `
                                <div class="message-sender">${msg.sender}</div>
                                <div class="message-content">${msg.message}</div>
                                <div class="message-time">${new Date(msg.timestamp).toLocaleString()}</div>
                            `;
                            messageList.appendChild(div);
                        });
                        
                        // Scroll to bottom
                        messageList.scrollTop = messageList.scrollHeight;
                    }
                })
                .catch(err => console.error('Error loading messages:', err));
        }
        
        function loadParticipants() {
            if (!currentThreadId) return;
            
            fetch(`/api/v1/threads/${currentThreadId}/participants`)
                .then(r => r.json())
                .then(data => {
                    const participantsDiv = document.getElementById('threadParticipants');
                    participantsDiv.innerHTML = `
                        <small><strong>Participants:</strong> ${data.participants.join(', ')}</small>
                    `;
                })
                .catch(err => console.error('Error loading participants:', err));
        }
        
        function sendMessage(event) {
            event.preventDefault();
            
            const input = document.getElementById('messageInput');
            const senderInput = document.getElementById('senderInput');
            const message = input.value.trim();
            const sender = senderInput.value.trim() || 'human';
            
            if (!message || !currentThreadId) return;
            
            fetch('/api/v1/messages/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    thread_id: currentThreadId,
                    message: message,
                    sender: sender
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.message_id) {
                    input.value = '';
                    loadMessages(); // Refresh messages
                    loadThreads(); // Refresh thread list
                }
            })
            .catch(err => console.error('Error sending message:', err));
        }
        
        function createNewThread(event) {
            event.preventDefault();
            
            const threadIdInput = document.getElementById('newThreadId');
            const titleInput = document.getElementById('newThreadTitle');
            
            const threadId = threadIdInput.value.trim();
            const title = titleInput.value.trim() || threadId;
            
            if (!threadId) return;
            
            // Send a message to create the thread implicitly
            fetch('/api/v1/messages/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    thread_id: threadId,
                    message: `Thread "${title}" created`,
                    sender: 'human',
                    title: title
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.message_id) {
                    threadIdInput.value = '';
                    titleInput.value = '';
                    loadThreads();
                    selectThread(threadId, title);
                }
            })
            .catch(err => console.error('Error creating thread:', err));
        }
        
        // Auto-refresh
        setInterval(() => {
            loadMessages();
        }, 3000);
        
        setInterval(() => {
            loadThreads();
        }, 10000);
        
        // Initial load
        loadThreads();
    </script>
</body>
</html>
"""


@app.route("/")
def web_interface():
    """Serve the web interface"""
    return render_template_string(WEB_TEMPLATE)


if __name__ == "__main__":
    import sys

    # Parse command line arguments for port
    port = int(os.environ.get("PORT", 5000))

    # Check for --port argument
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv):
            if arg == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
                break

    app.run(host="0.0.0.0", port=port, debug=False)
