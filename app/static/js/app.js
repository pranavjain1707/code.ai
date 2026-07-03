// Main Application Controller for Local AI Chatbot (Docker)

let activeConversationId = null;
let currentTheme = 'dark';
let activeModel = 'llama3';
let modelsList = [];
let userPreferences = {};

// Initialize Markdown Parser with Syntax Highlighting and Copy Button
const md = window.markdownit({
    html: false,
    linkify: true,
    typographer: true,
    highlight: function (str, lang) {
        const language = lang || 'code';
        let highlighted = md.utils.escapeHtml(str);
        if (lang && hljs.getLanguage(lang)) {
            try {
                highlighted = hljs.highlight(str, { language: lang, ignoreIllegals: true }).value;
            } catch (__) {}
        }
        return `<pre class="hljs">` +
               `<div class="code-header">` +
                 `<span>${language.toUpperCase()}</span>` +
                 `<button class="btn-copy-code" onclick="copyCode(this)"><i class="fa-regular fa-copy me-1"></i>Copy</button>` +
               `</div>` +
               `<code>${highlighted}</code>` +
               `</pre>`;
    }
});

// Math render helper using KaTeX
function renderMarkdownWithMath(text) {
    if (!text) return "";
    
    // Replace block math $$equations$$
    let formatted = text.replace(/\$\$([\s\S]+?)\$\$/g, (match, eq) => {
        try {
            return '<div class="math-block text-center my-3">' + katex.renderToString(eq, { displayMode: true, throwOnError: false }) + '</div>';
        } catch (e) {
            return match;
        }
    });

    // Replace inline math $equations$
    formatted = formatted.replace(/\$([^\$\n]+?)\$/g, (match, eq) => {
        try {
            return '<span class="math-inline">' + katex.renderToString(eq, { displayMode: false, throwOnError: false }) + '</span>';
        } catch (e) {
            return match;
        }
    });

    return md.render(formatted);
}

// Global Clipboard copy code helper
window.copyCode = function(button) {
    const pre = button.closest('pre');
    const code = pre.querySelector('code');
    navigator.clipboard.writeText(code.innerText).then(() => {
        button.innerHTML = '<i class="fa-solid fa-check me-1"></i>Copied';
        setTimeout(() => {
            button.innerHTML = '<i class="fa-regular fa-copy me-1"></i>Copy';
        }, 2000);
    });
};

// Build request headers — only include Authorization if a token is stored.
// Sending 'Bearer null' would override the server's HTTPOnly cookie fallback
// and cause a 401 even when the session cookie is perfectly valid.
function getHeaders() {
    const token = localStorage.getItem('access_token');
    const headers = { 'Content-Type': 'application/json' };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
}

async function verifyAuth() {
    // Do NOT pre-check localStorage before hitting the API.
    // The server accepts auth via Bearer token (localStorage) OR HTTPOnly cookie.
    // Pre-checking localStorage causes an infinite redirect loop:
    //   / (cookie ok) -> JS sees no localStorage -> /auth -> cookie ok -> / -> ...
    try {
        const response = await fetch('/profile', { headers: getHeaders() });
        if (!response.ok) {
            localStorage.removeItem('access_token');
            window.location.href = '/auth';
            return false;
        }
        const data = await response.json();
        setupUserInfo(data.profile, data.usage_stats);
        return true;
    } catch (e) {
        localStorage.removeItem('access_token');
        window.location.href = '/auth';
        return false;
    }
}

// Populate user information in the footer/modal
function setupUserInfo(profile, stats) {
    const username = profile.username || 'User';
    const email = profile.email || '';
    
    document.getElementById('footerUsername').textContent = username;
    document.getElementById('footerEmail').textContent = email;
    document.getElementById('footerUserAvatar').textContent = username.charAt(0).toUpperCase();
    
    // Modal fields
    document.getElementById('modalUsername').textContent = username;
    document.getElementById('modalEmail').textContent = email;
    document.getElementById('modalAvatar').textContent = username.charAt(0).toUpperCase();
    document.getElementById('editUsername').value = username;
    
    // Analytics
    document.getElementById('statRequests').textContent = stats.request_count || 0;
    document.getElementById('statCost').textContent = `$${(stats.total_cost || 0).toFixed(4)}`;
    document.getElementById('statTokens').textContent = stats.total_tokens || 0;
}

// Fetch all available models from backend
async function fetchModels() {
    try {
        const response = await fetch('/models', { headers: getHeaders() });
        if (response.ok) {
            const data = await response.json();
            modelsList = data.models;
            populateModelsDropdowns();
        }
    } catch (e) {
        console.error("Failed to load models", e);
    }
}

function populateModelsDropdowns() {
    const selector = document.getElementById('modelSelectorDropdown');
    const settingsSelector = document.getElementById('settingsDefaultModel');
    
    selector.innerHTML = '';
    settingsSelector.innerHTML = '';
    
    let isModelAvailable = false;
    modelsList.forEach(m => {
        const opt1 = document.createElement('option');
        opt1.value = m.id;
        opt1.textContent = m.name;
        if (m.id === activeModel) {
            opt1.selected = true;
            isModelAvailable = true;
        }
        selector.appendChild(opt1);
        
        const opt2 = document.createElement('option');
        opt2.value = m.id;
        opt2.textContent = m.name;
        if (m.id === activeModel) opt2.selected = true;
        settingsSelector.appendChild(opt2);
    });
    
    // Fallback to the first available model if the active model isn't supported/available
    if (!isModelAvailable && modelsList.length > 0) {
        activeModel = modelsList[0].id;
        selector.value = activeModel;
        settingsSelector.value = activeModel;
    }
    
    document.getElementById('activeChatModelText').textContent = activeModel;
}

// Load user preferences settings
async function loadPreferences() {
    try {
        const response = await fetch('/settings', { headers: getHeaders() });
        if (response.ok) {
            const data = await response.json();
            userPreferences = data.settings;
            
            // Set defaults
            activeModel = userPreferences.default_model || 'google/gemini-2.5-flash';
            currentTheme = userPreferences.theme || 'dark';
            document.documentElement.setAttribute('data-theme', currentTheme);
            
            // Sync settings forms
            document.getElementById('settingsSystemPrompt').value = userPreferences.system_prompt || '';
            document.getElementById('settingsDefaultModel').value = activeModel;
            document.getElementById('modelSelectorDropdown').value = activeModel;
            
            if (currentTheme === 'light') {
                document.getElementById('themeRadioLight').checked = true;
                document.getElementById('themeToggleBtn').innerHTML = '<i class="fa-solid fa-sun"></i>';
            } else {
                document.getElementById('themeRadioDark').checked = true;
                document.getElementById('themeToggleBtn').innerHTML = '<i class="fa-solid fa-moon"></i>';
            }
        }
    } catch (e) {
        console.error("Preferences load error", e);
    }
}

// Fetch Conversations list
async function loadConversations(searchQuery = '') {
    const url = searchQuery ? `/history?q=${encodeURIComponent(searchQuery)}` : '/conversation';
    try {
        const response = await fetch(url, { headers: getHeaders() });
        if (response.ok) {
            const data = await response.json();
            renderConversationsList(data.conversations);
        }
    } catch (e) {
        console.error("Conversations load error", e);
    }
}

function renderConversationsList(conversations) {
    const container = document.getElementById('conversationsContainer');
    container.innerHTML = '';
    
    if (!conversations || conversations.length === 0) {
        container.innerHTML = '<div class="text-center theme-text-muted py-4 small">No chats found</div>';
        return;
    }
    
    conversations.forEach(c => {
        const div = document.createElement('div');
        div.className = `nav-item-chat ${c.id === activeConversationId ? 'active' : ''}`;
        div.dataset.id = c.id;
        
        // Pinned class prefix indicator if pinned
        const pinIcon = c.is_pinned ? '<i class="fa-solid fa-thumbtack text-accent small me-1" style="color: var(--accent-secondary)"></i>' : '';
        
        div.innerHTML = `
            <div class="chat-title-container" onclick="selectConversation('${c.id}')">
                <i class="fa-regular fa-comment"></i>
                <div class="chat-title-text">${pinIcon}${c.title}</div>
            </div>
            <div class="chat-item-actions">
                <button class="action-btn-mini" onclick="togglePinConversation('${c.id}', ${c.is_pinned})" title="${c.is_pinned ? 'Unpin' : 'Pin'}">
                    <i class="fa-solid fa-thumbtack"></i>
                </button>
                <button class="action-btn-mini" onclick="renameConversationPrompt('${c.id}', '${c.title}')" title="Rename">
                    <i class="fa-solid fa-pen"></i>
                </button>
                <button class="action-btn-mini" onclick="deleteConversation('${c.id}')" title="Delete">
                    <i class="fa-solid fa-trash text-danger"></i>
                </button>
            </div>
        `;
        container.appendChild(div);
    });
}

// Select Conversation and load messages
async function selectConversation(id) {
    activeConversationId = id;
    document.getElementById('emptyChatWelcome').classList.add('d-none');
    
    // Highlight in list
    document.querySelectorAll('.nav-item-chat').forEach(el => {
        el.classList.remove('active');
        if (el.dataset.id === id) el.classList.add('active');
    });
    
    try {
        const response = await fetch(`/conversation/${id}`, { headers: getHeaders() });
        if (response.ok) {
            const data = await response.json();
            document.getElementById('activeChatTitle').textContent = data.conversation.title;
            activeModel = data.conversation.model;
            // Fallback if the loaded conversation's model is not available in the current mode
            const isModelAvailable = modelsList.some(m => m.id === activeModel);
            if (!isModelAvailable && modelsList.length > 0) {
                activeModel = modelsList[0].id;
            }
            document.getElementById('modelSelectorDropdown').value = activeModel;
            document.getElementById('activeChatModelText').textContent = activeModel;
            
            renderMessages(data.messages);
        }
    } catch (e) {
        console.error("Failed to load conversation details", e);
    }
}

// Render Messages inside the central window
function renderMessages(messages) {
    const container = document.getElementById('chatMessages');
    container.innerHTML = '';
    
    if (!messages || messages.length === 0) {
        return;
    }
    
    messages.forEach(msg => {
        appendMessageBubble(msg.role, msg.content, msg.id, msg.response_time, msg.token_usage, msg.reasoning);
    });
    
    scrollToBottom();
}

function appendMessageBubble(role, content, msgId = null, duration = null, tokens = null, reasoning = null) {
    const container = document.getElementById('chatMessages');
    const wrapper = document.createElement('div');
    const isUser = role === 'user';
    wrapper.className = `message-wrapper ${isUser ? 'user-msg' : 'bot-msg'}`;
    
    const avatarChar = isUser ? 'U' : 'AI';
    
    let metaHTML = '';
    if (!isUser && (duration || tokens)) {
        const latency = duration ? `${duration.toFixed(2)}s` : '';
        const tok = tokens ? `${tokens.total_tokens || 0} tokens` : '';
        metaHTML = `<div class="message-metadata">${latency} ${latency && tok ? '•' : ''} ${tok}</div>`;
    }
    
    // Collapsible reasoning details block
    let reasoningHTML = '';
    if (!isUser && reasoning) {
        reasoningHTML = `
            <details class="thinking-block" open>
                <summary><i class="fa-solid fa-brain me-1"></i> Thinking Process</summary>
                <div class="thinking-content">${md.utils.escapeHtml(reasoning)}</div>
            </details>
        `;
    }
    
    // Message Action Overlay (Copy, Favorite, Regenerate)
    let actionHTML = '';
    if (msgId) {
        actionHTML = `
            <div class="message-actions">
                <button class="action-btn-mini" onclick="copyMessageText('${msgId}')" title="Copy Text"><i class="fa-regular fa-copy"></i></button>
                <button class="action-btn-mini" onclick="toggleFavoriteMessage('${msgId}')" title="Favorite"><i class="fa-regular fa-star"></i></button>
            </div>
        `;
    }
    
    wrapper.innerHTML = `
        <div class="message-avatar">${avatarChar}</div>
        <div class="message-bubble position-relative">
            ${reasoningHTML}
            <div class="message-text-content">${isUser ? md.utils.escapeHtml(content) : renderMarkdownWithMath(content)}</div>
            ${metaHTML}
            ${actionHTML}
        </div>
    `;
    
    container.appendChild(wrapper);
}

// Copy full response bubble text
window.copyMessageText = function(msgId) {
    // Find the bubble matching action
    // In production we can copy from original data or target element
    const eventBtn = event.currentTarget;
    const bubble = eventBtn.closest('.message-bubble');
    const textEl = bubble.querySelector('.message-text-content');
    
    navigator.clipboard.writeText(textEl.innerText).then(() => {
        eventBtn.innerHTML = '<i class="fa-solid fa-check"></i>';
        setTimeout(() => {
            eventBtn.innerHTML = '<i class="fa-regular fa-copy"></i>';
        }, 2000);
    });
};

// Toggle favorite message
window.toggleFavoriteMessage = async function(msgId) {
    const eventBtn = event.currentTarget;
    try {
        const response = await fetch(`/conversation/favorite?message_id=${msgId}`, {
            method: 'POST',
            headers: getHeaders()
        });
        if (response.ok) {
            const data = await response.json();
            if (data.data.status === 'added') {
                eventBtn.innerHTML = '<i class="fa-solid fa-star text-warning"></i>';
                alert("Message added to saved favorites!");
            } else {
                eventBtn.innerHTML = '<i class="fa-regular fa-star"></i>';
                alert("Message removed from saved favorites.");
            }
        }
    } catch (e) {
        console.error("Toggle favorite failed", e);
    }
};

// Toggle Pin conversation
window.togglePinConversation = async function(id, currentPinned) {
    event.stopPropagation();
    try {
        const response = await fetch(`/conversation/${id}`, {
            method: 'PUT',
            headers: getHeaders(),
            body: JSON.stringify({ is_pinned: !currentPinned })
        });
        if (response.ok) {
            loadConversations();
        }
    } catch (e) {
        console.error(e);
    }
};

// Rename conversation dialog
window.renameConversationPrompt = async function(id, currentTitle) {
    event.stopPropagation();
    const newTitle = prompt("Enter new title for conversation:", currentTitle);
    if (!newTitle || newTitle.trim() === '') return;
    
    try {
        const response = await fetch(`/conversation/${id}`, {
            method: 'PUT',
            headers: getHeaders(),
            body: JSON.stringify({ title: newTitle.trim() })
        });
        if (response.ok) {
            if (id === activeConversationId) {
                document.getElementById('activeChatTitle').textContent = newTitle;
            }
            loadConversations();
        }
    } catch (e) {
        console.error(e);
    }
};

// Delete conversation
window.deleteConversation = async function(id) {
    event.stopPropagation();
    if (!confirm("Are you sure you want to delete this conversation? This cannot be undone.")) return;
    
    try {
        const response = await fetch(`/conversation/${id}`, {
            method: 'DELETE',
            headers: getHeaders()
        });
        if (response.ok) {
            if (id === activeConversationId) {
                activeConversationId = null;
                document.getElementById('chatMessages').innerHTML = '';
                document.getElementById('emptyChatWelcome').classList.remove('d-none');
                document.getElementById('activeChatTitle').textContent = 'New Conversation';
                document.getElementById('activeChatModelText').textContent = 'Select a model to begin';
            }
            loadConversations();
        }
    } catch (e) {
        console.error(e);
    }
};

// Streaming Chat generator
async function sendMessage() {
    const textarea = document.getElementById('chatTextarea');
    const message = textarea.value.trim();
    if (!message) return;
    
    textarea.value = '';
    textarea.style.height = 'auto';
    document.getElementById('sendMessageBtn').disabled = true;
    
    // Append User Message to UI
    appendMessageBubble('user', message);
    scrollToBottom();
    
    // Add Streaming Typing placeholder
    const container = document.getElementById('chatMessages');
    const streamWrapper = document.createElement('div');
    streamWrapper.className = 'message-wrapper bot-msg';
    streamWrapper.innerHTML = `
        <div class="message-avatar">AI</div>
        <div class="message-bubble position-relative">
            <div class="typing-indicator" id="streamTypingIndicator">
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
                <div class="typing-dot"></div>
            </div>
            <details class="thinking-block d-none" id="streamingThinkingBlock" open>
                <summary><i class="fa-solid fa-brain me-1"></i> Thinking Process</summary>
                <div class="thinking-content" id="streamingThinkingContent"></div>
            </details>
            <div class="message-text-content" id="streamingTextContent"></div>
        </div>
    `;
    container.appendChild(streamWrapper);
    scrollToBottom();
    
    const streamingText = document.getElementById('streamingTextContent');
    const typingIndicator = document.getElementById('streamTypingIndicator');
    const streamingThinkingBlock = streamWrapper.querySelector('#streamingThinkingBlock');
    const streamingThinkingContent = streamWrapper.querySelector('#streamingThinkingContent');
    
    let accumulatedText = "";
    let accumulatedReasoning = "";
    
    try {
        const payload = {
            message: message,
            model: activeModel,
            conversation_id: activeConversationId
        };
        
        const response = await fetch('/chat/stream', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify(payload)
        });
        
        if (!response.ok) {
            typingIndicator.remove();
            streamingText.innerHTML = `<span class="text-danger">Failed to send message: ${response.statusText}</span>`;
            return;
        }
        
        // Consume EventStream
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop(); // Keep partial line in buffer
            
            for (const line of lines) {
                if (!line || !line.startsWith('data: ')) continue;
                const dataStr = line.slice(6).trim();
                
                try {
                    const dataJson = jsonParseSafe(dataStr);
                    if (!dataJson) continue;
                    
                    // First line returns conversation_id for new chats
                    if (dataJson.conversation_id) {
                        const prevId = activeConversationId;
                        activeConversationId = dataJson.conversation_id;
                        if (dataJson.is_new_chat) {
                            loadConversations();
                        }
                        // Set dropdown model
                        document.getElementById('activeChatModelText').textContent = activeModel;
                        continue;
                    }
                    
                    // Check if stream finished
                    if (dataJson.done) {
                        typingIndicator.remove();
                        // Replace stream area with normal static structure to attach actions correctly
                        streamWrapper.remove();
                        appendMessageBubble(
                            'assistant', 
                            accumulatedText, 
                            dataJson.message_id, 
                            dataJson.usage.response_time, 
                            dataJson.usage,
                            accumulatedReasoning
                        );
                        scrollToBottom();
                        
                        // Reload analytics to update Dashboard numbers
                        refreshProfileStats();
                        return;
                    }
                    
                    // Check if error occurred
                    if (dataJson.error) {
                        typingIndicator.remove();
                        streamingText.innerHTML = `<span class="text-danger"><i class="fa-solid fa-triangle-exclamation me-1"></i> ${dataJson.error}</span>`;
                        scrollToBottom();
                        return;
                    }

                    // Handle reasoning chunks
                    if (dataJson.reasoning) {
                        if (typingIndicator) typingIndicator.style.display = 'none';
                        streamingThinkingBlock.classList.remove('d-none');
                        accumulatedReasoning += dataJson.reasoning;
                        streamingThinkingContent.textContent = accumulatedReasoning;
                        scrollToBottom();
                    }

                    // Handle content chunks
                    if (dataJson.content) {
                        if (typingIndicator) typingIndicator.style.display = 'none';
                        accumulatedText += dataJson.content;
                        // Streaming UI render
                        streamingText.innerHTML = renderMarkdownWithMath(accumulatedText);
                        scrollToBottom();
                    }
                } catch (e) {
                    console.error("Stream parse error", e);
                }
            }
        }
    } catch (e) {
        typingIndicator.remove();
        streamingText.innerHTML = `<span class="text-danger">Error streaming response: ${e.message}</span>`;
    } finally {
        document.getElementById('sendMessageBtn').disabled = false;
    }
}

function jsonParseSafe(str) {
    try { return JSON.parse(str); } catch (e) { return null; }
}

function scrollToBottom() {
    const chatBox = document.getElementById('chatMessages');
    chatBox.scrollTop = chatBox.scrollHeight;
}

async function refreshProfileStats() {
    try {
        const response = await fetch('/profile', { headers: getHeaders() });
        if (response.ok) {
            const data = await response.json();
            setupUserInfo(data.profile, data.usage_stats);
        }
    } catch (e) {}
}

// Event Listeners Setup
document.addEventListener('DOMContentLoaded', async () => {
    // 1. Verify User Credentials
    const loggedIn = await verifyAuth();
    if (!loggedIn) return;
    
    // 2. Fetch configurations
    await loadPreferences();
    await fetchModels();
    await loadConversations();
    
    // Theme setup from preferences
    document.getElementById('themeToggleBtn').addEventListener('click', () => {
        currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', currentTheme);
        document.getElementById('themeToggleBtn').innerHTML = currentTheme === 'light' ? '<i class="fa-solid fa-sun"></i>' : '<i class="fa-solid fa-moon"></i>';
        
        // Save to preferences backend
        fetch('/settings', {
            method: 'POST',
            headers: getHeaders(),
            body: JSON.stringify({ theme: currentTheme })
        });
    });

    // Model Selector Change
    document.getElementById('modelSelectorDropdown').addEventListener('change', (e) => {
        activeModel = e.target.value;
        document.getElementById('activeChatModelText').textContent = activeModel;
    });

    // Send Button click
    document.getElementById('sendMessageBtn').addEventListener('click', sendMessage);
    
    // New Chat Trigger
    document.getElementById('newChatBtn').addEventListener('click', () => {
        activeConversationId = null;
        document.getElementById('chatMessages').innerHTML = '';
        document.getElementById('emptyChatWelcome').classList.remove('d-none');
        document.getElementById('activeChatTitle').textContent = 'New Conversation';
        document.getElementById('activeChatModelText').textContent = activeModel;
        document.querySelectorAll('.nav-item-chat').forEach(el => el.classList.remove('active'));
    });
    
    // Textarea Send controls and resize
    const textarea = document.getElementById('chatTextarea');
    textarea.addEventListener('input', () => {
        textarea.style.height = 'auto';
        textarea.style.height = (textarea.scrollHeight) + 'px';
        document.getElementById('sendMessageBtn').disabled = textarea.value.trim() === '';
    });
    
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // Search input throttle
    let searchTimeout = null;
    document.getElementById('searchChatInput').addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            loadConversations(e.target.value.trim());
        }, 300);
    });

    // Edit profile save
    document.getElementById('editProfileForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = document.getElementById('editUsername').value.trim();
        try {
            const response = await fetch('/profile', {
                method: 'PUT',
                headers: getHeaders(),
                body: JSON.stringify({ username })
            });
            if (response.ok) {
                alert("Profile changes saved.");
                refreshProfileStats();
                // Close Modal
                bootstrap.Modal.getInstance(document.getElementById('profileModal')).hide();
            }
        } catch (err) {
            alert("Failed to update profile.");
        }
    });

    // Settings save
    document.getElementById('settingsForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const default_model = document.getElementById('settingsDefaultModel').value;
        const system_prompt = document.getElementById('settingsSystemPrompt').value.trim();
        const theme = document.querySelector('input[name="themeRadio"]:checked').value;
        
        try {
            const response = await fetch('/settings', {
                method: 'POST',
                headers: getHeaders(),
                body: JSON.stringify({ default_model, system_prompt, theme })
            });
            if (response.ok) {
                alert("Preferences saved successfully!");
                activeModel = default_model;
                document.getElementById('modelSelectorDropdown').value = default_model;
                document.getElementById('activeChatModelText').textContent = default_model;
                currentTheme = theme;
                document.documentElement.setAttribute('data-theme', theme);
                document.getElementById('themeToggleBtn').innerHTML = theme === 'light' ? '<i class="fa-solid fa-sun"></i>' : '<i class="fa-solid fa-moon"></i>';
                
                bootstrap.Modal.getInstance(document.getElementById('settingsModal')).hide();
            }
        } catch (err) {
            alert("Failed to save settings.");
        }
    });

    // Sidebar toggles for mobile viewports
    document.getElementById('openSidebarBtn').addEventListener('click', () => {
        document.getElementById('sidebar').classList.add('show');
    });
    document.getElementById('closeSidebarBtn').addEventListener('click', () => {
        document.getElementById('sidebar').classList.remove('show');
    });

    // Logout
    document.getElementById('logoutBtn').addEventListener('click', async (e) => {
        e.preventDefault();
        try {
            await fetch('/auth/logout', { method: 'POST', headers: getHeaders() });
        } catch (err) {}
        localStorage.removeItem('access_token');
        window.location.href = '/auth';
    });
});
