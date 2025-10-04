#!/usr/bin/env python3
"""Simple web-based log viewer for request/response logs.

Usage:
    python scripts/log_viewer.py requests.jsonl
    # Then open http://localhost:8000
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any

from flask import Flask, render_template_string

app = Flask(__name__)

# Global storage for logs
LOGS: List[Dict[str, Any]] = []
LOG_FILE: Path = None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Request/Response Log Viewer</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            margin: 0;
            padding: 0;
            background: #1e1e1e;
            color: #d4d4d4;
        }
        .container {
            display: flex;
            height: 100vh;
        }
        .sidebar {
            width: 300px;
            background: #252526;
            overflow-y: auto;
            border-right: 1px solid #3e3e42;
        }
        .content {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
        }
        .log-entry {
            padding: 12px;
            border-bottom: 1px solid #3e3e42;
            cursor: pointer;
            transition: background 0.2s;
        }
        .log-entry:hover {
            background: #2d2d30;
        }
        .log-entry.selected {
            background: #094771;
        }
        .log-type {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            margin-right: 8px;
        }
        .type-request { background: #0e639c; }
        .type-response { background: #0f7b0f; }
        .type-tool_execution { background: #9f0f9f; }
        .type-error { background: #9f0f0f; }
        .timestamp {
            font-size: 11px;
            color: #858585;
        }
        .model-name {
            font-size: 12px;
            color: #4ec9b0;
            margin-top: 4px;
        }
        pre {
            background: #1e1e1e;
            padding: 16px;
            border-radius: 4px;
            overflow-x: auto;
            border: 1px solid #3e3e42;
        }
        .json-key { color: #9cdcfe; }
        .json-string { color: #ce9178; }
        .json-number { color: #b5cea8; }
        .json-boolean { color: #569cd6; }
        .json-null { color: #569cd6; }
        h2 {
            margin-top: 0;
            color: #4ec9b0;
        }
        .filters {
            padding: 12px;
            background: #2d2d30;
            border-bottom: 1px solid #3e3e42;
        }
        .filters select, .filters input {
            background: #3c3c3c;
            border: 1px solid #3e3e42;
            color: #d4d4d4;
            padding: 6px;
            border-radius: 3px;
            margin-right: 8px;
        }
        .stats {
            padding: 12px;
            background: #252526;
            border-bottom: 1px solid #3e3e42;
            font-size: 12px;
        }
        .stat-item {
            display: inline-block;
            margin-right: 16px;
        }
        .stat-label {
            color: #858585;
        }
        .stat-value {
            color: #4ec9b0;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <div class="stats">
                <div class="stat-item">
                    <span class="stat-label">Total:</span>
                    <span class="stat-value" id="total-count">{{ logs|length }}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Requests:</span>
                    <span class="stat-value">{{ logs|selectattr('type', 'equalto', 'request')|list|length }}</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Responses:</span>
                    <span class="stat-value">{{ logs|selectattr('type', 'equalto', 'response')|list|length }}</span>
                </div>
            </div>
            <div class="filters">
                <select id="type-filter" onchange="filterLogs()">
                    <option value="all">All Types</option>
                    <option value="request">Requests</option>
                    <option value="response">Responses</option>
                    <option value="tool_execution">Tool Executions</option>
                    <option value="error">Errors</option>
                </select>
                <input type="text" id="search" placeholder="Search..." onkeyup="filterLogs()">
            </div>
            <div id="log-list">
                {% for log in logs %}
                <div class="log-entry" data-index="{{ loop.index0 }}" data-type="{{ log.type }}" onclick="selectLog({{ loop.index0 }})">
                    <div>
                        <span class="log-type type-{{ log.type }}">{{ log.type }}</span>
                    </div>
                    <div class="timestamp">{{ log.timestamp }}</div>
                    {% if log.model %}
                    <div class="model-name">{{ log.model }}</div>
                    {% endif %}
                    {% if log.tool_name %}
                    <div class="model-name">{{ log.tool_name }}</div>
                    {% endif %}
                </div>
                {% endfor %}
            </div>
        </div>
        <div class="content">
            <div id="detail-view">
                <h2>Select a log entry</h2>
                <p>Click on an entry in the sidebar to view details.</p>
            </div>
        </div>
    </div>
    
    <script>
        const logs = {{ logs|tojson|safe }};
        let selectedIndex = null;
        
        function syntaxHighlight(json) {
            if (typeof json != 'string') {
                json = JSON.stringify(json, null, 2);
            }
            json = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            return json.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
                var cls = 'json-number';
                if (/^"/.test(match)) {
                    if (/:$/.test(match)) {
                        cls = 'json-key';
                    } else {
                        cls = 'json-string';
                    }
                } else if (/true|false/.test(match)) {
                    cls = 'json-boolean';
                } else if (/null/.test(match)) {
                    cls = 'json-null';
                }
                return '<span class="' + cls + '">' + match + '</span>';
            });
        }
        
        function selectLog(index) {
            // Update selection in sidebar
            document.querySelectorAll('.log-entry').forEach(el => {
                el.classList.remove('selected');
            });
            document.querySelector(`[data-index="${index}"]`).classList.add('selected');
            
            // Show detail
            const log = logs[index];
            const detailView = document.getElementById('detail-view');
            
            let html = '<h2>' + log.type.replace('_', ' ').toUpperCase() + '</h2>';
            html += '<pre>' + syntaxHighlight(log) + '</pre>';
            
            detailView.innerHTML = html;
            selectedIndex = index;
        }
        
        function filterLogs() {
            const typeFilter = document.getElementById('type-filter').value;
            const searchText = document.getElementById('search').value.toLowerCase();
            
            let visibleCount = 0;
            document.querySelectorAll('.log-entry').forEach(el => {
                const entryType = el.getAttribute('data-type');
                const entryText = el.textContent.toLowerCase();
                
                const typeMatch = typeFilter === 'all' || entryType === typeFilter;
                const searchMatch = searchText === '' || entryText.includes(searchText);
                
                if (typeMatch && searchMatch) {
                    el.style.display = 'block';
                    visibleCount++;
                } else {
                    el.style.display = 'none';
                }
            });
            
            document.getElementById('total-count').textContent = visibleCount;
        }
        
        // Select first entry by default
        if (logs.length > 0) {
            selectLog(0);
        }
        
        // Keyboard navigation
        document.addEventListener('keydown', (e) => {
            if (selectedIndex === null) return;
            
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                const next = selectedIndex + 1;
                if (next < logs.length) {
                    selectLog(next);
                    document.querySelector(`[data-index="${next}"]`).scrollIntoView({ block: 'nearest' });
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                const prev = selectedIndex - 1;
                if (prev >= 0) {
                    selectLog(prev);
                    document.querySelector(`[data-index="${prev}"]`).scrollIntoView({ block: 'nearest' });
                }
            }
        });
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    """Render the log viewer."""
    return render_template_string(HTML_TEMPLATE, logs=LOGS)


@app.route("/refresh")
def refresh():
    """Reload logs from file."""
    load_logs()
    return {"status": "ok", "count": len(LOGS)}


def load_logs():
    """Load logs from the JSON Lines file."""
    global LOGS
    LOGS = []

    if not LOG_FILE.exists():
        print(f"Log file not found: {LOG_FILE}")
        return

    with open(LOG_FILE) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    LOGS.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(f"Failed to parse line: {e}")
                    continue


def main():
    global LOG_FILE

    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    LOG_FILE = Path(sys.argv[1])

    if not LOG_FILE.exists():
        print(f"Error: Log file not found: {LOG_FILE}")
        sys.exit(1)

    print(f"Loading logs from: {LOG_FILE}")
    load_logs()
    print(f"Loaded {len(LOGS)} log entries")

    print("\nStarting web server on http://localhost:8000")
    print("Press Ctrl+C to stop")

    app.run(host="127.0.0.1", port=8000, debug=True)


if __name__ == "__main__":
    main()
