#!/usr/bin/env python3
"""
Silica Messaging App - Root messaging hub for agent communication

This Flask application serves as the central messaging hub for Silica workspaces.
It handles thread management, message routing, and provides both API and web interfaces.
"""

import os
import json
import uuid
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, render_template_string, Response
import requests
from typing import Dict, List, Optional

app = Flask(__name__)

# Configuration
DATA_DIR = Path(os.environ.get("DATA_DIR", "/tmp/silica-messaging"))
THREADS_DIR = DATA_DIR / "threads"
MESSAGES_DIR = DATA_DIR / "messages"

# Ensure directories exist
THREADS_DIR.mkdir(parents=True, exist_ok=True)
MESSAGES_DIR.mkdir(parents=True, exist_ok=True)


class ThreadStorage:
    """File-based storage for threads and messages"""

    @staticmethod
    def _ensure_workspace_dir(workspace: str, project: str) -> Path:
        """Ensure workspace directory exists and return path"""
        workspace_key = f"{workspace}-{project}"
        workspace_dir = THREADS_DIR / workspace_key
        workspace_dir.mkdir(exist_ok=True)
        return workspace_dir

    @staticmethod
    def create_thread(
        workspace: str, project: str, title: str, thread_id: Optional[str] = None
    ) -> Dict:
        """Create a new thread"""
        if not thread_id:
            thread_id = str(uuid.uuid4())

        thread = {
            "thread_id": thread_id,
            "workspace": workspace,
            "project": project,
            "title": title,
            "participants": ["human", f"{workspace}-{project}"],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "active",
        }

        workspace_dir = ThreadStorage._ensure_workspace_dir(workspace, project)
        thread_file = workspace_dir / f"{thread_id}.json"

        with open(thread_file, "w") as f:
            json.dump(thread, f, indent=2)

        return thread

    @staticmethod
    def get_thread(workspace: str, project: str, thread_id: str) -> Optional[Dict]:
        """Retrieve a specific thread"""
        workspace_key = f"{workspace}-{project}"
        thread_file = THREADS_DIR / workspace_key / f"{thread_id}.json"

        if not thread_file.exists():
            return None

        with open(thread_file, "r") as f:
            return json.load(f)

    @staticmethod
    def list_threads(workspace: str, project: str) -> List[Dict]:
        """List all threads for a workspace"""
        workspace_key = f"{workspace}-{project}"
        workspace_dir = THREADS_DIR / workspace_key

        if not workspace_dir.exists():
            return []

        threads = []
        for thread_file in workspace_dir.glob("*.json"):
            with open(thread_file, "r") as f:
                threads.append(json.load(f))

        # Sort by created_at descending
        threads.sort(key=lambda x: x["created_at"], reverse=True)
        return threads

    @staticmethod
    def save_message(
        workspace: str, project: str, thread_id: str, message: Dict
    ) -> None:
        """Save a message to a thread"""
        workspace_key = f"{workspace}-{project}"
        thread_messages_dir = MESSAGES_DIR / workspace_key / thread_id
        thread_messages_dir.mkdir(parents=True, exist_ok=True)

        message_file = thread_messages_dir / f"{message['message_id']}.json"
        with open(message_file, "w") as f:
            json.dump(message, f, indent=2)

        # Update thread timestamp
        thread = ThreadStorage.get_thread(workspace, project, thread_id)
        if thread:
            thread["updated_at"] = datetime.now().isoformat()
            workspace_dir = ThreadStorage._ensure_workspace_dir(workspace, project)
            thread_file = workspace_dir / f"{thread_id}.json"
            with open(thread_file, "w") as f:
                json.dump(thread, f, indent=2)

    @staticmethod
    def get_messages(workspace: str, project: str, thread_id: str) -> List[Dict]:
        """Get all messages for a thread"""
        workspace_key = f"{workspace}-{project}"
        thread_messages_dir = MESSAGES_DIR / workspace_key / thread_id

        if not thread_messages_dir.exists():
            return []

        messages = []
        for message_file in thread_messages_dir.glob("*.json"):
            with open(message_file, "r") as f:
                messages.append(json.load(f))

        # Sort by timestamp ascending
        messages.sort(key=lambda x: x["timestamp"])
        return messages


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


@app.route("/api/v1/threads/create", methods=["POST"])
def create_thread():
    """Create a new thread"""
    data = request.get_json()

    workspace = data.get("workspace")
    project = data.get("project")
    title = data.get("title", "General")
    thread_id = data.get("thread_id")  # Optional - for default threads

    if not workspace or not project:
        return jsonify({"error": "workspace and project are required"}), 400

    thread = ThreadStorage.create_thread(workspace, project, title, thread_id)
    return jsonify(thread), 201


@app.route("/api/v1/threads/<workspace>")
def list_threads(workspace):
    """List threads for a workspace"""
    project = request.args.get("project")
    if not project:
        return jsonify({"error": "project parameter is required"}), 400

    threads = ThreadStorage.list_threads(workspace, project)
    return jsonify({"threads": threads, "total": len(threads)})


@app.route("/api/v1/messages/send", methods=["POST"])
def send_message():
    """Send message from human to agent"""
    data = request.get_json()

    workspace = data.get("workspace")
    project = data.get("project")
    thread_id = data.get("thread_id")
    message_content = data.get("message")
    metadata = data.get("metadata", {})

    if not all([workspace, project, thread_id, message_content]):
        return jsonify(
            {"error": "workspace, project, thread_id, and message are required"}
        ), 400

    # Create message record
    message = {
        "message_id": str(uuid.uuid4()),
        "thread_id": thread_id,
        "sender": "human",
        "message": message_content,
        "timestamp": datetime.now().isoformat(),
        "metadata": metadata,
    }

    # Save message
    ThreadStorage.save_message(workspace, project, thread_id, message)

    # Forward to agent workspace
    status = forward_to_agent(workspace, project, thread_id, message)

    return jsonify(
        {
            "message_id": message["message_id"],
            "status": status,
            "timestamp": message["timestamp"],
        }
    )


@app.route("/api/v1/messages/agent-response", methods=["POST"])
def receive_agent_response():
    """Receive message from agent"""
    data = request.get_json()

    workspace = data.get("workspace")
    project = data.get("project")
    thread_id = data.get("thread_id")
    message_content = data.get("message")
    message_type = data.get("type", "info")

    if not all([workspace, project, thread_id, message_content]):
        return jsonify(
            {"error": "workspace, project, thread_id, and message are required"}
        ), 400

    # Create message record
    message = {
        "message_id": str(uuid.uuid4()),
        "thread_id": thread_id,
        "sender": f"{workspace}-{project}",
        "message": message_content,
        "timestamp": datetime.now().isoformat(),
        "type": message_type,
        "metadata": {},
    }

    # Save message
    ThreadStorage.save_message(workspace, project, thread_id, message)

    return jsonify({"status": "received", "message_id": message["message_id"]})


@app.route("/api/v1/messages/<workspace>/<thread_id>")
def get_messages(workspace, thread_id):
    """Get messages for a thread"""
    project = request.args.get("project")
    if not project:
        return jsonify({"error": "project parameter is required"}), 400

    messages = ThreadStorage.get_messages(workspace, project, thread_id)
    return jsonify({"messages": messages, "count": len(messages)})


@app.route("/api/v1/workspaces/status")
def workspace_status():
    """List active workspaces with messaging enabled"""
    workspaces = []

    if THREADS_DIR.exists():
        for workspace_dir in THREADS_DIR.iterdir():
            if workspace_dir.is_dir():
                workspace_name = workspace_dir.name
                threads = list(workspace_dir.glob("*.json"))
                workspaces.append(
                    {
                        "name": workspace_name,
                        "connected": True,  # Assume connected for now
                        "active_threads": len(threads),
                    }
                )

    return jsonify({"workspaces": workspaces})


# HTTP Proxy for agent endpoints
@app.route("/proxy/<workspace_project>/<path:agent_path>")
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
                url, headers=headers, params=request.args, stream=True
            )
        elif request.method == "POST":
            response = requests.post(
                url, headers=headers, json=request.get_json(), stream=True
            )
        else:
            # Handle other methods as needed
            response = requests.request(
                request.method,
                url,
                headers=headers,
                data=request.get_data(),
                stream=True,
            )

        # Stream response back
        return Response(
            response.iter_content(chunk_size=1024),
            status=response.status_code,
            headers=dict(response.headers),
        )
    except requests.RequestException as e:
        return jsonify({"error": f"Proxy error: {str(e)}"}), 502


def forward_to_agent(
    workspace: str, project: str, thread_id: str, message: Dict
) -> str:
    """Forward message to agent workspace"""
    agent_host = f"{workspace}-{project}"

    try:
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
            timeout=30,
        )

        if response.status_code == 200:
            return "delivered"
        else:
            return "failed"
    except requests.RequestException:
        return "failed"


# Simple web interface
WEB_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Silica Messaging</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { border-bottom: 1px solid #ccc; padding-bottom: 10px; margin-bottom: 20px; }
        .workspace-selector { margin-bottom: 20px; }
        .threads { display: flex; gap: 20px; }
        .thread-list { flex: 1; max-width: 300px; }
        .messages { flex: 2; }
        .thread-item { padding: 10px; border: 1px solid #ddd; margin-bottom: 10px; cursor: pointer; }
        .thread-item.active { background-color: #e3f2fd; }
        .message { padding: 10px; border: 1px solid #eee; margin-bottom: 10px; }
        .message.human { background-color: #f3e5f5; }
        .message.agent { background-color: #e8f5e8; }
        .message-form { margin-top: 20px; }
        .message-input { width: 100%; height: 100px; }
        button { padding: 10px 20px; background-color: #2196f3; color: white; border: none; cursor: pointer; }
        button:hover { background-color: #1976d2; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Silica Messaging</h1>
            <p>Multi-workspace agent communication hub</p>
        </div>
        
        <div class="workspace-selector">
            <label>Workspace: </label>
            <select id="workspaceSelect" onchange="loadWorkspace()">
                <option value="">Select workspace...</option>
            </select>
        </div>
        
        <div class="threads" id="threadsContainer" style="display: none;">
            <div class="thread-list">
                <h3>Threads</h3>
                <button onclick="createNewThread()">New Thread</button>
                <div id="threadList"></div>
            </div>
            
            <div class="messages">
                <h3 id="threadTitle">Select a thread</h3>
                <div id="messageList"></div>
                <div class="message-form" id="messageForm" style="display: none;">
                    <textarea id="messageInput" class="message-input" placeholder="Type your message..."></textarea>
                    <br><br>
                    <button onclick="sendMessage()">Send Message</button>
                </div>
            </div>
        </div>
    </div>

    <script>
        let currentWorkspace = '';
        let currentProject = '';
        let currentThreadId = '';
        
        // Load workspaces on page load
        fetch('/api/v1/workspaces/status')
            .then(r => r.json())
            .then(data => {
                const select = document.getElementById('workspaceSelect');
                data.workspaces.forEach(ws => {
                    const option = document.createElement('option');
                    option.value = ws.name;
                    option.textContent = `${ws.name} (${ws.active_threads} threads)`;
                    select.appendChild(option);
                });
            });
        
        function loadWorkspace() {
            const select = document.getElementById('workspaceSelect');
            const workspaceName = select.value;
            if (!workspaceName) return;
            
            // Parse workspace-project format
            const parts = workspaceName.split('-');
            currentWorkspace = parts[0];
            currentProject = parts.slice(1).join('-');
            
            document.getElementById('threadsContainer').style.display = 'block';
            loadThreads();
        }
        
        function loadThreads() {
            fetch(`/api/v1/threads/${currentWorkspace}?project=${currentProject}`)
                .then(r => r.json())
                .then(data => {
                    const threadList = document.getElementById('threadList');
                    threadList.innerHTML = '';
                    
                    data.threads.forEach(thread => {
                        const div = document.createElement('div');
                        div.className = 'thread-item';
                        div.onclick = () => selectThread(thread.thread_id, thread.title);
                        div.textContent = thread.title;
                        threadList.appendChild(div);
                    });
                });
        }
        
        function selectThread(threadId, title) {
            currentThreadId = threadId;
            document.getElementById('threadTitle').textContent = title;
            document.getElementById('messageForm').style.display = 'block';
            
            // Highlight selected thread
            document.querySelectorAll('.thread-item').forEach(item => {
                item.classList.remove('active');
            });
            event.target.classList.add('active');
            
            loadMessages();
        }
        
        function loadMessages() {
            fetch(`/api/v1/messages/${currentWorkspace}/${currentThreadId}?project=${currentProject}`)
                .then(r => r.json())
                .then(data => {
                    const messageList = document.getElementById('messageList');
                    messageList.innerHTML = '';
                    
                    data.messages.forEach(msg => {
                        const div = document.createElement('div');
                        div.className = `message ${msg.sender === 'human' ? 'human' : 'agent'}`;
                        div.innerHTML = `
                            <strong>${msg.sender}:</strong> ${msg.message}
                            <br><small>${new Date(msg.timestamp).toLocaleString()}</small>
                        `;
                        messageList.appendChild(div);
                    });
                    
                    // Scroll to bottom
                    messageList.scrollTop = messageList.scrollHeight;
                });
        }
        
        function sendMessage() {
            const input = document.getElementById('messageInput');
            const message = input.value.trim();
            if (!message) return;
            
            fetch('/api/v1/messages/send', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    workspace: currentWorkspace,
                    project: currentProject,
                    thread_id: currentThreadId,
                    message: message
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.message_id) {
                    input.value = '';
                    loadMessages(); // Refresh messages
                }
            });
        }
        
        function createNewThread() {
            const title = prompt('Thread title:');
            if (!title) return;
            
            fetch('/api/v1/threads/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    workspace: currentWorkspace,
                    project: currentProject,
                    title: title
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.thread_id) {
                    loadThreads();
                }
            });
        }
        
        // Auto-refresh messages every 5 seconds
        setInterval(() => {
            if (currentThreadId) {
                loadMessages();
            }
        }, 5000);
    </script>
</body>
</html>
"""


@app.route("/")
def web_interface():
    """Serve the web interface"""
    return render_template_string(WEB_TEMPLATE)


if __name__ == "__main__":
    # Ensure default thread creation for known workspaces
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
