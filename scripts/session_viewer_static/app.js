// Session Viewer Application

// State
let currentPersona = null;
let currentSession = null;
let currentSessionData = null;
let currentTurn = -1; // -1 means show all
let totalTurns = 0;
let tools = [];
let rootDir = null;

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
        
        const response = await fetch(`/api/sessions?persona=${encodeURIComponent(persona)}`);
        const data = await response.json();
        
        sessionList.innerHTML = '';
        
        if (data.sessions.length === 0) {
            sessionList.innerHTML = '<div class="text-gray-500 text-sm">No sessions found</div>';
            return;
        }
        
        data.sessions.forEach(session => {
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
            const matchingSession = data.sessions.find(s => 
                s.session_id === window.initialSessionId || 
                s.session_id.startsWith(window.initialSessionId)
            );
            if (matchingSession) {
                loadSession(matchingSession.persona, matchingSession.session_id);
            }
            window.initialSessionId = null;
        }
    } catch (e) {
        console.error('Failed to load sessions:', e);
        sessionList.innerHTML = '<div class="text-red-500 text-sm">Error loading sessions</div>';
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

// Expose functions for inline handlers
window.toggleToolSchema = toggleToolSchema;
window.showFileMention = showFileMention;
window.loadSubagent = loadSubagent;
