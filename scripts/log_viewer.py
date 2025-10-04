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

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

# Global storage for logs
LOGS: List[Dict[str, Any]] = []
LOG_FILE: Path = None

app = FastAPI(title="Log Viewer", description="Request/Response Log Viewer")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Request/Response Log Viewer</title>
    <!-- Include marked.js for markdown rendering -->
    <script src="https://cdn.jsdelivr.net/npm/marked@11.1.1/marked.min.js"></script>
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
            white-space: pre-wrap;
            word-wrap: break-word;
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
        h3 {
            color: #4ec9b0;
            margin-top: 24px;
            margin-bottom: 12px;
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
        .refresh-btn, .view-toggle-btn {
            background: #0e639c;
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 3px;
            cursor: pointer;
            font-size: 12px;
            margin-right: 8px;
        }
        .refresh-btn:hover, .view-toggle-btn:hover {
            background: #1177bb;
        }
        .view-toggle-btn.active {
            background: #1177bb;
        }
        .view-toggle-group {
            margin-bottom: 16px;
        }
        .view-section {
            display: none;
            margin-bottom: 24px;
        }
        .view-section.active {
            display: block;
        }
        .field {
            margin-bottom: 16px;
        }
        .field-label {
            color: #4ec9b0;
            font-weight: 600;
            margin-bottom: 4px;
        }
        .field-value {
            background: #2d2d30;
            padding: 12px;
            border-radius: 4px;
            border: 1px solid #3e3e42;
        }
        .field-value.text {
            white-space: pre-wrap;
            word-wrap: break-word;
            font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
            font-size: 13px;
            line-height: 1.6;
        }
        .rendered-content {
            line-height: 1.6;
        }
        .rendered-content p {
            margin: 0.5em 0;
        }
        .rendered-content code {
            background: #1e1e1e;
            padding: 2px 6px;
            border-radius: 3px;
            font-family: 'Monaco', 'Menlo', 'Consolas', monospace;
            font-size: 13px;
        }
        .rendered-content pre {
            margin: 0;
        }
        .rendered-content pre code {
            display: block;
            padding: 12px;
        }
        .array-item {
            background: #2d2d30;
            padding: 12px;
            border-radius: 4px;
            border: 1px solid #3e3e42;
            margin-bottom: 8px;
        }
        .array-item-header {
            color: #858585;
            font-size: 11px;
            font-weight: 600;
            margin-bottom: 8px;
        }
        .collapsible {
            cursor: pointer;
            user-select: none;
        }
        .collapsible:before {
            content: '▼ ';
            display: inline-block;
            transition: transform 0.2s;
        }
        .collapsible.collapsed:before {
            transform: rotate(-90deg);
        }
        .collapsible-content {
            margin-top: 8px;
        }
        .collapsible-content.collapsed {
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="sidebar">
            <div class="stats">
                <div class="stat-item">
                    <span class="stat-label">Total:</span>
                    <span class="stat-value" id="total-count">__TOTAL__</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Requests:</span>
                    <span class="stat-value" id="request-count">__REQUEST_COUNT__</span>
                </div>
                <div class="stat-item">
                    <span class="stat-label">Responses:</span>
                    <span class="stat-value" id="response-count">__RESPONSE_COUNT__</span>
                </div>
                <button class="refresh-btn" onclick="refreshLogs()">Refresh</button>
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
                __LOG_LIST__
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
        const logs = __LOGS_JSON__;
        let selectedIndex = null;
        let currentView = 'rendered';
        
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
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        function renderField(label, value, isMarkdown = false) {
            if (value === null || value === undefined) {
                return '';
            }
            
            let html = '<div class="field">';
            html += '<div class="field-label">' + escapeHtml(label) + '</div>';
            
            if (typeof value === 'object' && !Array.isArray(value)) {
                html += '<div class="field-value"><pre>' + syntaxHighlight(value) + '</pre></div>';
            } else if (Array.isArray(value)) {
                html += '<div class="field-value">';
                value.forEach((item, idx) => {
                    html += '<div class="array-item">';
                    html += '<div class="array-item-header">Item ' + (idx + 1) + '</div>';
                    if (typeof item === 'object') {
                        html += '<pre>' + syntaxHighlight(item) + '</pre>';
                    } else {
                        html += '<div class="field-value text">' + escapeHtml(String(item)) + '</div>';
                    }
                    html += '</div>';
                });
                html += '</div>';
            } else if (typeof value === 'string') {
                if (isMarkdown && value.length > 50) {
                    // Render as markdown if it looks like it might contain markdown
                    html += '<div class="field-value rendered-content">' + marked.parse(value) + '</div>';
                } else {
                    html += '<div class="field-value text">' + escapeHtml(value) + '</div>';
                }
            } else {
                html += '<div class="field-value text">' + escapeHtml(String(value)) + '</div>';
            }
            
            html += '</div>';
            return html;
        }
        
        function renderMessages(messages) {
            if (!messages || !Array.isArray(messages)) return '';
            
            let html = '<div class="field">';
            html += '<div class="field-label collapsible" onclick="toggleCollapse(this)">Messages (' + messages.length + ')</div>';
            html += '<div class="field-value collapsible-content">';
            
            messages.forEach((msg, idx) => {
                html += '<div class="array-item">';
                html += '<div class="array-item-header">Message ' + (idx + 1) + ' - ' + escapeHtml(msg.role || 'unknown') + '</div>';
                
                if (typeof msg.content === 'string') {
                    html += '<div class="field-value text">' + escapeHtml(msg.content) + '</div>';
                } else if (Array.isArray(msg.content)) {
                    msg.content.forEach((block, blockIdx) => {
                        if (block.type === 'text' && block.text) {
                            html += '<div style="margin-top: 8px;">';
                            html += '<div style="font-size: 11px; color: #858585; margin-bottom: 4px;">Text Block ' + (blockIdx + 1) + '</div>';
                            html += '<div class="field-value text">' + escapeHtml(block.text) + '</div>';
                            html += '</div>';
                        } else {
                            html += '<div style="margin-top: 8px;">';
                            html += '<pre>' + syntaxHighlight(block) + '</pre>';
                            html += '</div>';
                        }
                    });
                }
                
                html += '</div>';
            });
            
            html += '</div></div>';
            return html;
        }
        
        function renderContent(content) {
            if (!content || !Array.isArray(content)) return '';
            
            let html = '<div class="field">';
            html += '<div class="field-label">Content</div>';
            html += '<div class="field-value">';
            
            content.forEach((block, idx) => {
                html += '<div class="array-item">';
                
                if (block.type === 'text' && block.text) {
                    html += '<div class="array-item-header">Text Block ' + (idx + 1) + '</div>';
                    html += '<div class="field-value text">' + escapeHtml(block.text) + '</div>';
                } else if (block.type === 'thinking' && block.thinking) {
                    html += '<div class="array-item-header">Thinking Block ' + (idx + 1) + '</div>';
                    html += '<div class="field-value rendered-content">' + marked.parse(block.thinking) + '</div>';
                } else if (block.type === 'tool_use') {
                    html += '<div class="array-item-header">Tool Use: ' + escapeHtml(block.name || 'unknown') + '</div>';
                    html += '<pre>' + syntaxHighlight(block) + '</pre>';
                } else {
                    html += '<div class="array-item-header">Block ' + (idx + 1) + '</div>';
                    html += '<pre>' + syntaxHighlight(block) + '</pre>';
                }
                
                html += '</div>';
            });
            
            html += '</div></div>';
            return html;
        }
        
        function toggleCollapse(element) {
            element.classList.toggle('collapsed');
            const content = element.nextElementSibling;
            if (content && content.classList.contains('collapsible-content')) {
                content.classList.toggle('collapsed');
            }
        }
        
        function renderLogEntry(log) {
            let html = '';
            
            // Always show basic fields
            if (log.timestamp) html += renderField('Timestamp', log.timestamp);
            if (log.model) html += renderField('Model', log.model);
            if (log.tool_name) html += renderField('Tool Name', log.tool_name);
            if (log.error_type) html += renderField('Error Type', log.error_type);
            if (log.error_message) html += renderField('Error Message', log.error_message);
            
            // Type-specific rendering
            if (log.type === 'request') {
                if (log.max_tokens) html += renderField('Max Tokens', log.max_tokens);
                if (log.system) html += renderField('System', log.system);
                if (log.messages) html += renderMessages(log.messages);
                if (log.thinking) html += renderField('Thinking Config', log.thinking);
            } else if (log.type === 'response') {
                if (log.message_id) html += renderField('Message ID', log.message_id);
                if (log.stop_reason) html += renderField('Stop Reason', log.stop_reason);
                if (log.content) html += renderContent(log.content);
                if (log.usage) html += renderField('Usage', log.usage);
                if (log.thinking_content) html += renderField('Thinking Content', log.thinking_content, true);
            } else if (log.type === 'tool_execution') {
                if (log.input) html += renderField('Input', log.input);
                if (log.result) {
                    const result = log.result;
                    if (result.content && typeof result.content === 'string') {
                        html += renderField('Result Content', result.content);
                    } else {
                        html += renderField('Result', result);
                    }
                }
            } else if (log.type === 'error') {
                if (log.context) html += renderField('Context', log.context);
            }
            
            return html;
        }
        
        function selectLog(index) {
            // Update selection in sidebar
            document.querySelectorAll('.log-entry').forEach(el => {
                el.classList.remove('selected');
            });
            const selectedEntry = document.querySelector(`[data-index="${index}"]`);
            if (selectedEntry) {
                selectedEntry.classList.add('selected');
            }
            
            // Show detail
            const log = logs[index];
            const detailView = document.getElementById('detail-view');
            
            let html = '<h2>' + log.type.replace('_', ' ').toUpperCase() + '</h2>';
            
            // View toggle buttons
            html += '<div class="view-toggle-group">';
            html += '<button class="view-toggle-btn ' + (currentView === 'rendered' ? 'active' : '') + '" onclick="switchView(\'rendered\')">Rendered</button>';
            html += '<button class="view-toggle-btn ' + (currentView === 'raw' ? 'active' : '') + '" onclick="switchView(\'raw\')">Raw JSON</button>';
            html += '</div>';
            
            // Rendered view
            html += '<div class="view-section ' + (currentView === 'rendered' ? 'active' : '') + '" id="rendered-view">';
            html += renderLogEntry(log);
            html += '</div>';
            
            // Raw JSON view
            html += '<div class="view-section ' + (currentView === 'raw' ? 'active' : '') + '" id="raw-view">';
            html += '<pre>' + syntaxHighlight(log) + '</pre>';
            html += '</div>';
            
            detailView.innerHTML = html;
            selectedIndex = index;
        }
        
        function switchView(view) {
            currentView = view;
            if (selectedIndex !== null) {
                selectLog(selectedIndex);
            }
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
        
        async function refreshLogs() {
            try {
                const response = await fetch('/api/refresh');
                const data = await response.json();
                if (data.status === 'ok') {
                    window.location.reload();
                }
            } catch (error) {
                console.error('Failed to refresh:', error);
            }
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
                    const nextEntry = document.querySelector(`[data-index="${next}"]`);
                    if (nextEntry) {
                        nextEntry.scrollIntoView({ block: 'nearest' });
                    }
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                const prev = selectedIndex - 1;
                if (prev >= 0) {
                    selectLog(prev);
                    const prevEntry = document.querySelector(`[data-index="${prev}"]`);
                    if (prevEntry) {
                        prevEntry.scrollIntoView({ block: 'nearest' });
                    }
                }
            } else if (e.key === 'r' && !e.ctrlKey && !e.metaKey) {
                // 'r' key to switch to rendered view
                switchView('rendered');
            } else if (e.key === 'j' && !e.ctrlKey && !e.metaKey) {
                // 'j' key to switch to raw JSON view
                switchView('raw');
            }
        });
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index():
    """Render the log viewer."""
    # Build log list HTML
    log_list_html = []
    for i, log in enumerate(LOGS):
        log_type = log.get("type", "unknown")
        timestamp = log.get("timestamp", "")
        model = log.get("model", "")
        tool_name = log.get("tool_name", "")

        entry_html = f"""
        <div class="log-entry" data-index="{i}" data-type="{log_type}" onclick="selectLog({i})">
            <div>
                <span class="log-type type-{log_type}">{log_type}</span>
            </div>
            <div class="timestamp">{timestamp}</div>
        """

        if model:
            entry_html += f'<div class="model-name">{model}</div>'
        if tool_name:
            entry_html += f'<div class="model-name">{tool_name}</div>'

        entry_html += "</div>"
        log_list_html.append(entry_html)

    # Calculate stats
    total_count = len(LOGS)
    request_count = sum(1 for log in LOGS if log.get("type") == "request")
    response_count = sum(1 for log in LOGS if log.get("type") == "response")

    # Build final HTML
    html = HTML_TEMPLATE
    html = html.replace("__TOTAL__", str(total_count))
    html = html.replace("__REQUEST_COUNT__", str(request_count))
    html = html.replace("__RESPONSE_COUNT__", str(response_count))
    html = html.replace("__LOG_LIST__", "\n".join(log_list_html))
    html = html.replace("__LOGS_JSON__", json.dumps(LOGS))

    return html


@app.get("/api/refresh")
async def refresh():
    """Reload logs from file."""
    load_logs()
    return {"status": "ok", "count": len(LOGS)}


@app.get("/api/logs")
async def get_logs():
    """Get logs as JSON."""
    return LOGS


@app.get("/api/stats")
async def get_stats():
    """Get log statistics."""
    stats = {
        "total": len(LOGS),
        "by_type": {},
    }

    for log in LOGS:
        log_type = log.get("type", "unknown")
        stats["by_type"][log_type] = stats["by_type"].get(log_type, 0) + 1

    return stats


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

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
