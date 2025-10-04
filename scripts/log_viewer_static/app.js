let logs = [];
let selectedIndex = null;
let currentView = 'rendered';

// Load logs via API
async function loadLogs() {
    try {
        const response = await fetch('/api/logs');
        logs = await response.json();
        initializeUI();
    } catch (error) {
        console.error('Failed to load logs:', error);
        document.getElementById('detail-view').innerHTML = '<h2>Error loading logs</h2><p>' + error.message + '</p>';
    }
}

function initializeUI() {
    // Build log list
    const logList = document.getElementById('log-list');
    logList.innerHTML = '';
    
    logs.forEach((log, index) => {
        const entry = document.createElement('div');
        entry.className = 'log-entry';
        entry.setAttribute('data-index', index);
        entry.setAttribute('data-type', log.type || 'unknown');
        entry.onclick = () => selectLog(index);
        
        const logType = log.type || 'unknown';
        const timestamp = log.timestamp || '';
        const model = log.model || '';
        const toolName = log.tool_name || '';
        
        entry.innerHTML = `
            <div>
                <span class="log-type type-${logType}">${logType}</span>
            </div>
            <div class="timestamp">${timestamp}</div>
            ${model ? `<div class="model-name">${model}</div>` : ''}
            ${toolName ? `<div class="model-name">${toolName}</div>` : ''}
        `;
        
        logList.appendChild(entry);
    });
    
    // Update stats
    const requestCount = logs.filter(log => log.type === 'request').length;
    const responseCount = logs.filter(log => log.type === 'response').length;
    
    document.getElementById('total-count').textContent = logs.length;
    document.getElementById('request-count').textContent = requestCount;
    document.getElementById('response-count').textContent = responseCount;
    
    // Select first entry by default
    if (logs.length > 0) {
        selectLog(0);
    }
}

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
            await loadLogs();
        }
    } catch (error) {
        console.error('Failed to refresh:', error);
    }
}

// Initialize on page load
loadLogs();

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
