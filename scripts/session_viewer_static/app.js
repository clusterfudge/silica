// Session Viewer Application

// State
let currentPersona = null;
let currentSession = null;
let currentSessionData = null;
let currentTurn = -1; // -1 means show all
let totalTurns = 0;
let tools = [];
let rootDir = null;
let launchCwd = null;  // Directory where command was launched
let filterByCwd = true;  // Filter to current directory by default

// DOM Elements
const personaSelect = document.getElementById('persona-select');
const sessionList = document.getElementById('session-list');
const sessionTitle = document.getElementById('session-title');
const sessionMeta = document.getElementById('session-meta');
const messagesContainer = document.getElementById('messages-container');
const playbackControls = document.getElementById('playback-controls');
const currentTurnSpan = document.getElementById('current-turn');
const totalTurnsSpan = document.getElementById('total-turns');
const showAllCheckbox = document.getElementById('show-all');
const subagentPanel = document.getElementById('subagent-panel');
const subagentMessages = document.getElementById('subagent-messages');

// Initialize
document.addEventListener('DOMContentLoaded', async () => {
    await loadConfig();
    await loadPersonas();
    await loadTools();
    setupEventListeners();
});

async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        const config = await response.json();
        if (config.active_persona) {
            currentPersona = config.active_persona;
        }
        if (config.initial_session_id) {
            // Will be loaded after personas are loaded
            window.initialSessionId = config.initial_session_id;
        }
        if (config.launch_cwd) {
            launchCwd = config.launch_cwd;
        }
    } catch (e) {
        console.error('Failed to load config:', e);
    }
}

async function loadPersonas() {
    try {
        const response = await fetch('/api/personas');
        const data = await response.json();
        
        personaSelect.innerHTML = '';
        data.personas.forEach(persona => {
            const option = document.createElement('option');
            option.value = persona.name;
            option.textContent = `${persona.name} (${persona.session_count} sessions)`;
            if (persona.name === currentPersona || persona.name === data.active_persona) {
                option.selected = true;
                currentPersona = persona.name;
            }
            personaSelect.appendChild(option);
        });
        
        if (currentPersona) {
            await loadSessions(currentPersona);
        }
    } catch (e) {
        console.error('Failed to load personas:', e);
        personaSelect.innerHTML = '<option>Error loading personas</option>';
    }
}

async function loadSessions(persona) {
    try {
        sessionList.innerHTML = '<div class="text-gray-500 text-sm">Loading...</div>';
        
        // Build URL with optional root_dir filter
        let url = `/api/sessions?persona=${encodeURIComponent(persona)}`;
        if (filterByCwd && launchCwd) {
            url += `&root_dir=${encodeURIComponent(launchCwd)}`;
        }
        
        const response = await fetch(url);
        const data = await response.json();
        
        // If filtering by cwd returned no results, try without filter
        if (data.sessions.length === 0 && filterByCwd && launchCwd) {
            // Fetch all sessions to check if there are any
            const allResponse = await fetch(`/api/sessions?persona=${encodeURIComponent(persona)}`);
            const allData = await allResponse.json();
            
            if (allData.sessions.length > 0) {
                // There are sessions, just not in cwd - show message and fall back
                sessionList.innerHTML = `<div class="text-yellow-500 text-sm mb-2">No sessions in current directory. Showing all sessions.</div>`;
                filterByCwd = false;
                const cwdCheckbox = document.getElementById('filter-cwd');
                if (cwdCheckbox) cwdCheckbox.checked = false;
                renderSessionList(allData.sessions);
                return;
            }
        }
        
        sessionList.innerHTML = '';
        
        if (data.sessions.length === 0) {
            sessionList.innerHTML = '<div class="text-gray-500 text-sm">No sessions found</div>';
            return;
        }
        
        renderSessionList(data.sessions);
    } catch (e) {
        console.error('Failed to load sessions:', e);
        sessionList.innerHTML = '<div class="text-red-500 text-sm">Error loading sessions</div>';
    }
}

function renderSessionList(sessions) {
    // Clear any previous content except the "no sessions in cwd" message
    const existingMessage = sessionList.querySelector('.text-yellow-500');
    sessionList.innerHTML = '';
    if (existingMessage) {
        sessionList.appendChild(existingMessage);
    }
    
    sessions.forEach(session => {
        const item = document.createElement('div');
        item.className = 'session-item';
        item.dataset.sessionId = session.session_id;
        item.dataset.persona = session.persona;
        
        const date = session.last_updated || session.created_at;
        const dateStr = date ? new Date(date).toLocaleString() : 'Unknown date';
        const shortId = session.session_id.substring(0, 8);
        
        item.innerHTML = `
            <div class="session-item-id">${shortId}...</div>
            <div class="session-item-date">${dateStr}</div>
            <div class="session-item-meta">
                ${session.message_count} msgs
                ${session.subagent_count > 0 ? `• ${session.subagent_count} subagents` : ''}
                ${session.has_active_plan ? '• 📋 plan' : ''}
            </div>
        `;
        
        item.addEventListener('click', () => loadSession(session.persona, session.session_id));
        sessionList.appendChild(item);
    });
    
    // Load initial session if specified
    if (window.initialSessionId) {
        const matchingSession = sessions.find(s => 
            s.session_id === window.initialSessionId || 
            s.session_id.startsWith(window.initialSessionId)
        );
        if (matchingSession) {
            loadSession(matchingSession.persona, matchingSession.session_id);
        }
        window.initialSessionId = null;
    }
}

async function loadSession(persona, sessionId) {
    try {
        // Update active state in list
        document.querySelectorAll('.session-item').forEach(item => {
            item.classList.toggle('active', item.dataset.sessionId === sessionId);
        });
        
        const response = await fetch(`/api/session/${encodeURIComponent(persona)}/${encodeURIComponent(sessionId)}`);
        const data = await response.json();
        
        currentSession = sessionId;
        currentSessionData = data;
        rootDir = data.session.metadata?.root_dir;
        
        // Update header
        sessionTitle.textContent = `Session ${sessionId.substring(0, 8)}...`;
        const meta = data.session.metadata || {};
        sessionMeta.textContent = `${data.session.messages?.length || 0} messages • ${meta.root_dir || 'Unknown location'}`;
        
        // Calculate turns (user messages)
        totalTurns = data.session.messages?.filter(m => m.role === 'user').length || 0;
        totalTurnsSpan.textContent = totalTurns;
        currentTurn = -1; // Show all
        currentTurnSpan.textContent = 'All';
        showAllCheckbox.checked = true;
        
        // Show playback controls
        playbackControls.style.display = 'flex';
        
        // Update system prompt sections
        updateSystemPromptSections(data);
        
        // Render messages
        renderMessages(data.session.messages, data.subagent_files);
        
        // Close subagent panel if open
        closeSubagentPanel();
        
        // Close metrics panel if open
        closeMetricsPanel();
        
        // Check for plan metrics
        loadPlanMetrics();
        
    } catch (e) {
        console.error('Failed to load session:', e);
        messagesContainer.innerHTML = '<div class="text-red-500 p-4">Error loading session</div>';
    }
}

async function loadTools() {
    try {
        const response = await fetch('/api/tools');
        const data = await response.json();
        tools = data.tools || [];
        renderToolsSection();
    } catch (e) {
        console.error('Failed to load tools:', e);
    }
}

function updateSystemPromptSections(data) {
    // Persona section
    const personaContent = document.getElementById('section-persona');
    if (data.persona_md) {
        personaContent.textContent = data.persona_md;
    } else {
        personaContent.textContent = '(No persona.md found)';
    }
    
    // Sandbox section - extract from metadata
    const sandboxContent = document.getElementById('section-sandbox');
    const rootDir = data.session.metadata?.root_dir;
    if (rootDir) {
        sandboxContent.textContent = `Root: ${rootDir}\n\n(Sandbox contents not stored in session)`;
    } else {
        sandboxContent.textContent = '(No sandbox info available)';
    }
    
    // Memory section
    const memoryContent = document.getElementById('section-memory');
    memoryContent.textContent = '(Memory topics not stored in session)';
    
    // Tools section is rendered separately
}

function renderToolsSection() {
    const toolsContent = document.getElementById('section-tools');
    
    if (tools.length === 0) {
        toolsContent.innerHTML = '<div class="text-gray-500">No tools loaded</div>';
        return;
    }
    
    toolsContent.innerHTML = tools.map(tool => `
        <div class="tool-schema-item" onclick="toggleToolSchema(this)">
            <div class="tool-schema-name">${escapeHtml(tool.name)}</div>
            <div class="tool-schema-desc">${escapeHtml(tool.description?.substring(0, 100) || '')}</div>
            <div class="tool-schema-details">
                <pre>${escapeHtml(JSON.stringify(tool.input_schema, null, 2))}</pre>
            </div>
        </div>
    `).join('');
}

function toggleToolSchema(element) {
    element.classList.toggle('expanded');
}

function renderMessages(messages, subagentFiles) {
    if (!messages || messages.length === 0) {
        messagesContainer.innerHTML = '<div class="text-gray-500 text-center py-8">No messages in this session</div>';
        return;
    }
    
    // Filter messages based on current turn
    let displayMessages = messages;
    if (currentTurn >= 0) {
        // Find the index of the Nth user message
        let userCount = 0;
        let cutoffIndex = messages.length;
        for (let i = 0; i < messages.length; i++) {
            if (messages[i].role === 'user') {
                userCount++;
                if (userCount > currentTurn) {
                    cutoffIndex = i;
                    break;
                }
            }
        }
        displayMessages = messages.slice(0, cutoffIndex);
    }
    
    messagesContainer.innerHTML = displayMessages.map((msg, idx) => 
        renderMessage(msg, idx, subagentFiles)
    ).join('');
    
    // Apply syntax highlighting
    document.querySelectorAll('pre code').forEach(block => {
        hljs.highlightElement(block);
    });
    
    // Scroll to bottom if showing all
    if (currentTurn < 0) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

function renderMessage(msg, index, subagentFiles) {
    const roleClass = `message-${msg.role}`;
    const content = renderMessageContent(msg.content, subagentFiles);
    
    return `
        <div class="message ${roleClass}" data-index="${index}">
            <div class="message-header">
                <span class="message-role">${msg.role}</span>
            </div>
            <div class="message-content">${content}</div>
        </div>
    `;
}

function renderMessageContent(content, subagentFiles) {
    if (typeof content === 'string') {
        return renderTextContent(content);
    }
    
    if (Array.isArray(content)) {
        return content.map(block => renderContentBlock(block, subagentFiles)).join('');
    }
    
    return '<span class="text-gray-500">(Unknown content format)</span>';
}

function renderContentBlock(block, subagentFiles) {
    if (!block || !block.type) {
        return '';
    }
    
    switch (block.type) {
        case 'text':
            return renderTextContent(block.text || '');
            
        case 'tool_use':
            return renderToolUse(block, subagentFiles);
            
        case 'tool_result':
            return renderToolResult(block);
            
        case 'thinking':
            return renderThinking(block);
            
        default:
            return `<div class="text-gray-500">(Unknown block type: ${block.type})</div>`;
    }
}

function renderTextContent(text) {
    // Check for @file mentions
    const fileMentionRegex = /@([^\s@]+\.[a-zA-Z0-9]+)/g;
    let result = escapeHtml(text);
    
    // Detect code blocks and apply highlighting
    result = result.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        const language = lang || 'plaintext';
        return `<pre><code class="language-${language}">${code}</code></pre>`;
    });
    
    // Highlight @file mentions
    result = result.replace(/@([^\s@&lt;]+\.[a-zA-Z0-9]+)/g, (match, path) => {
        return `<span class="file-mention-inline cursor-pointer text-teal-400 hover:underline" onclick="showFileMention('${path}')" title="Click to view file">@${path}</span>`;
    });
    
    return result;
}

function renderToolUse(block, subagentFiles) {
    const isAgent = block.name === 'agent';
    const hasSubagent = subagentFiles && subagentFiles[block.id];
    
    let subagentLink = '';
    if (isAgent && hasSubagent) {
        subagentLink = `<span class="subagent-link ml-2" onclick="loadSubagent('${block.id}')">[View sub-agent session]</span>`;
    }
    
    const inputStr = JSON.stringify(block.input, null, 2);
    
    return `
        <div class="tool-use">
            <div class="flex items-center">
                <span class="tool-name">${escapeHtml(block.name)}</span>
                ${subagentLink}
            </div>
            <div class="tool-input"><pre>${escapeHtml(inputStr)}</pre></div>
        </div>
    `;
}

function renderToolResult(block) {
    let content = block.content;
    
    if (typeof content === 'string') {
        content = escapeHtml(content);
    } else if (Array.isArray(content)) {
        content = content.map(c => {
            if (c.type === 'text') return escapeHtml(c.text);
            return JSON.stringify(c);
        }).join('\n');
    } else {
        content = JSON.stringify(content, null, 2);
    }
    
    // Truncate very long results
    const maxLength = 5000;
    if (content.length > maxLength) {
        content = content.substring(0, maxLength) + '\n... (truncated)';
    }
    
    return `
        <div class="tool-result">
            <div class="text-xs text-gray-400 mb-1">Tool Result ${block.is_error ? '(error)' : ''}</div>
            <pre class="text-xs overflow-x-auto">${content}</pre>
        </div>
    `;
}

function renderThinking(block) {
    return `
        <div class="thinking-block">
            <div class="thinking-label">💭 Thinking</div>
            <div>${escapeHtml(block.thinking || '')}</div>
        </div>
    `;
}

async function showFileMention(path) {
    try {
        const url = `/api/file?path=${encodeURIComponent(path)}${rootDir ? `&root_dir=${encodeURIComponent(rootDir)}` : ''}`;
        const response = await fetch(url);
        const data = await response.json();
        
        if (data.exists && data.content) {
            // Show in a modal or expand inline
            alert(`File: ${data.path}\n\n${data.content.substring(0, 1000)}${data.content.length > 1000 ? '\n...(truncated)' : ''}`);
        } else {
            alert(`File not found: ${path}`);
        }
    } catch (e) {
        console.error('Failed to load file:', e);
        alert(`Error loading file: ${e.message}`);
    }
}

async function loadSubagent(toolId) {
    if (!currentSession || !currentPersona) return;
    
    try {
        const response = await fetch(`/api/session/${encodeURIComponent(currentPersona)}/${encodeURIComponent(currentSession)}/subagent/${encodeURIComponent(toolId)}`);
        const data = await response.json();
        
        subagentPanel.classList.remove('hidden');
        subagentMessages.innerHTML = data.session.messages?.map((msg, idx) => 
            renderMessage(msg, idx, {})
        ).join('') || '<div class="text-gray-500">No messages</div>';
        
        // Apply syntax highlighting
        subagentPanel.querySelectorAll('pre code').forEach(block => {
            hljs.highlightElement(block);
        });
        
    } catch (e) {
        console.error('Failed to load subagent:', e);
        subagentMessages.innerHTML = '<div class="text-red-500">Error loading sub-agent session</div>';
    }
}

function closeSubagentPanel() {
    subagentPanel.classList.add('hidden');
    subagentMessages.innerHTML = '';
}

function setupEventListeners() {
    // Persona select
    personaSelect.addEventListener('change', (e) => {
        currentPersona = e.target.value;
        loadSessions(currentPersona);
    });
    
    // CWD filter checkbox
    const cwdCheckbox = document.getElementById('filter-cwd');
    if (cwdCheckbox) {
        cwdCheckbox.addEventListener('change', (e) => {
            filterByCwd = e.target.checked;
            if (currentPersona) {
                loadSessions(currentPersona);
            }
        });
    }
    
    // Playback controls
    document.getElementById('btn-first').addEventListener('click', () => goToTurn(1));
    document.getElementById('btn-prev').addEventListener('click', () => goToTurn(Math.max(1, currentTurn - 1)));
    document.getElementById('btn-next').addEventListener('click', () => goToTurn(Math.min(totalTurns, currentTurn + 1)));
    document.getElementById('btn-last').addEventListener('click', () => goToTurn(totalTurns));
    
    showAllCheckbox.addEventListener('change', (e) => {
        if (e.target.checked) {
            currentTurn = -1;
            currentTurnSpan.textContent = 'All';
        } else {
            currentTurn = totalTurns;
            currentTurnSpan.textContent = currentTurn;
        }
        if (currentSessionData) {
            renderMessages(currentSessionData.session.messages, currentSessionData.subagent_files);
        }
    });
    
    // Close subagent panel
    document.getElementById('close-subagent').addEventListener('click', closeSubagentPanel);
    
    // Collapsible sections
    document.querySelectorAll('.section-toggle').forEach(toggle => {
        toggle.addEventListener('click', () => {
            toggle.classList.toggle('expanded');
            const content = toggle.nextElementSibling;
            content.classList.toggle('hidden');
        });
    });
}

function goToTurn(turn) {
    if (turn < 1 || turn > totalTurns) return;
    
    currentTurn = turn;
    currentTurnSpan.textContent = turn;
    showAllCheckbox.checked = false;
    
    if (currentSessionData) {
        renderMessages(currentSessionData.session.messages, currentSessionData.subagent_files);
    }
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Metrics panel functions
const metricsPanel = document.getElementById('metrics-panel');
const metricsContent = document.getElementById('metrics-content');
const btnShowMetrics = document.getElementById('btn-show-metrics');

async function loadPlanMetrics() {
    if (!currentSession || !currentPersona) return;
    
    try {
        const response = await fetch(`/api/session/${encodeURIComponent(currentPersona)}/${encodeURIComponent(currentSession)}/plan-metrics`);
        const data = await response.json();
        
        if (data.has_plan && data.metrics) {
            btnShowMetrics.classList.remove('hidden');
            btnShowMetrics.onclick = () => showMetricsPanel(data);
        } else {
            btnShowMetrics.classList.add('hidden');
        }
    } catch (e) {
        console.error('Failed to load plan metrics:', e);
        btnShowMetrics.classList.add('hidden');
    }
}

function showMetricsPanel(data) {
    metricsPanel.classList.remove('hidden');
    
    const { plan_id, plan_title, plan_status, metrics } = data;
    const { definitions, snapshots, execution_started_at } = metrics;
    
    let html = `
        <div class="mb-4">
            <h3 class="text-lg font-semibold">${escapeHtml(plan_title)}</h3>
            <p class="text-sm text-gray-400">Plan ID: ${plan_id} • Status: ${plan_status}</p>
        </div>
    `;
    
    // Metric definitions
    html += `<div class="mb-4">
        <h4 class="text-sm font-medium text-gray-400 mb-2">Tracked Metrics</h4>
        <div class="space-y-1">`;
    
    definitions.forEach(def => {
        const dirIcon = def.direction === 'up' ? '↑' : '↓';
        const validated = def.validated ? '✓' : '⚠️';
        const target = def.target_value !== null ? `, target: ${def.target_value}` : '';
        html += `<div class="text-sm"><span class="font-mono">${escapeHtml(def.name)}</span> ${dirIcon} (${def.metric_type}${target}) ${validated}</div>`;
    });
    html += `</div></div>`;
    
    // Snapshots summary
    if (snapshots && snapshots.length > 0) {
        html += `<div class="mb-4">
            <h4 class="text-sm font-medium text-gray-400 mb-2">Snapshots (${snapshots.length})</h4>
            <div class="overflow-x-auto">
                <table class="w-full text-sm">
                    <thead>
                        <tr class="border-b border-gray-700">
                            <th class="text-left py-1 px-2">Trigger</th>
                            <th class="text-left py-1 px-2">Time</th>
                            <th class="text-left py-1 px-2">Cost</th>`;
        
        // Add columns for each metric
        definitions.filter(d => d.validated).forEach(def => {
            html += `<th class="text-left py-1 px-2">${escapeHtml(def.name)}</th>`;
        });
        
        html += `</tr></thead><tbody>`;
        
        snapshots.forEach((snap, idx) => {
            const mins = Math.floor(snap.wall_clock_seconds / 60);
            const secs = Math.floor(snap.wall_clock_seconds % 60);
            const cost = snap.cost_dollars < 1 ? `$${snap.cost_dollars.toFixed(4)}` : `$${snap.cost_dollars.toFixed(2)}`;
            
            html += `<tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
                <td class="py-1 px-2 font-mono text-xs">${escapeHtml(snap.trigger)}</td>
                <td class="py-1 px-2">${mins}m ${secs}s</td>
                <td class="py-1 px-2">${cost}</td>`;
            
            definitions.filter(d => d.validated).forEach(def => {
                const val = snap.metrics[def.name];
                const prevSnap = idx > 0 ? snapshots[idx - 1] : null;
                const prevVal = prevSnap ? prevSnap.metrics[def.name] : null;
                
                let delta = '';
                if (prevVal !== null && val !== undefined) {
                    const diff = val - prevVal;
                    if (diff !== 0) {
                        const sign = diff > 0 ? '+' : '';
                        const isRegression = (def.direction === 'up' && diff < 0) || (def.direction === 'down' && diff > 0);
                        delta = `<span class="${isRegression ? 'text-red-400' : 'text-green-400'}">(${sign}${diff})</span>`;
                    }
                }
                
                html += `<td class="py-1 px-2">${val !== undefined ? val : '-'} ${delta}</td>`;
            });
            
            html += `</tr>`;
        });
        
        html += `</tbody></table></div></div>`;
        
        // Simple chart visualization using CSS bars
        const validatedDefs = definitions.filter(d => d.validated);
        if (validatedDefs.length > 0 && snapshots.length > 1) {
            html += `<div class="mb-4">
                <h4 class="text-sm font-medium text-gray-400 mb-2">Progress Charts</h4>`;
            
            validatedDefs.forEach(def => {
                const values = snapshots.map(s => s.metrics[def.name]).filter(v => v !== undefined);
                if (values.length < 2) return;
                
                const min = Math.min(...values);
                const max = Math.max(...values);
                const range = max - min || 1;
                const target = def.target_value;
                
                html += `<div class="mb-3">
                    <div class="text-xs text-gray-400 mb-1">${escapeHtml(def.name)} ${def.direction === 'up' ? '↑' : '↓'}</div>
                    <div class="flex items-end h-16 gap-1 bg-gray-800 rounded p-2">`;
                
                values.forEach((val, i) => {
                    const height = ((val - min) / range) * 100;
                    const isLast = i === values.length - 1;
                    const color = isLast ? 'bg-blue-500' : 'bg-gray-600';
                    html += `<div class="${color} rounded-t" style="width: ${100 / values.length}%; height: ${Math.max(5, height)}%;" title="${val}"></div>`;
                });
                
                html += `</div>
                    <div class="flex justify-between text-xs text-gray-500">
                        <span>Start: ${values[0]}</span>
                        <span>Current: ${values[values.length - 1]}</span>
                        ${target !== null ? `<span>Target: ${target}</span>` : ''}
                    </div>
                </div>`;
            });
            
            html += `</div>`;
        }
        
        // Cost chart
        if (snapshots.length > 1) {
            const costs = snapshots.map(s => s.cost_dollars);
            const maxCost = Math.max(...costs);
            
            html += `<div class="mb-4">
                <h4 class="text-sm font-medium text-gray-400 mb-2">Cost Over Time</h4>
                <div class="flex items-end h-16 gap-1 bg-gray-800 rounded p-2">`;
            
            costs.forEach((cost, i) => {
                const height = maxCost > 0 ? (cost / maxCost) * 100 : 0;
                const isLast = i === costs.length - 1;
                const color = isLast ? 'bg-green-500' : 'bg-gray-600';
                html += `<div class="${color} rounded-t" style="width: ${100 / costs.length}%; height: ${Math.max(5, height)}%;" title="$${cost.toFixed(4)}"></div>`;
            });
            
            html += `</div>
                <div class="flex justify-between text-xs text-gray-500">
                    <span>Start: $${costs[0].toFixed(4)}</span>
                    <span>Current: $${costs[costs.length - 1].toFixed(4)}</span>
                </div>
            </div>`;
        }
    } else {
        html += `<div class="text-gray-500 text-sm">No snapshots captured yet.</div>`;
    }
    
    metricsContent.innerHTML = html;
}

function closeMetricsPanel() {
    metricsPanel.classList.add('hidden');
    metricsContent.innerHTML = '';
}

// Add close button handler
document.getElementById('close-metrics')?.addEventListener('click', closeMetricsPanel);

// Expose functions for inline handlers
window.toggleToolSchema = toggleToolSchema;
window.showFileMention = showFileMention;
window.loadSubagent = loadSubagent;
window.showMetricsPanel = showMetricsPanel;
