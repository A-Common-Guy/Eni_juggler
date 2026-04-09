/**
 * AI Chat Panel for ENI Juggler.
 * Collapsible side panel that interfaces with the Claude-based AI assistant.
 */
const ChatPanel = {
    _container: null,
    _messagesEl: null,
    _inputEl: null,
    _sendBtn: null,
    _available: false,
    _busy: false,

    async init(containerId) {
        this._container = document.getElementById(containerId);
        this._messagesEl = this._container.querySelector('.chat-messages');
        this._inputEl = this._container.querySelector('.chat-input');
        this._sendBtn = this._container.querySelector('.chat-send-btn');

        this._sendBtn.addEventListener('click', () => this._send());
        this._inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this._send();
            }
        });

        this._container.querySelector('.chat-clear-btn')
            .addEventListener('click', () => this._clearHistory());

        this._container.querySelector('.chat-settings-btn')
            .addEventListener('click', () => this._openSettings());

        document.getElementById('btnCancelSettings')
            .addEventListener('click', () => this._closeSettings());
        document.getElementById('btnSaveSettings')
            .addEventListener('click', () => this._saveSettings());
        document.getElementById('btnToggleKeyVisibility')
            .addEventListener('click', () => {
                const input = document.getElementById('settingsApiKey');
                input.type = input.type === 'password' ? 'text' : 'password';
            });

        await this._checkAvailability();
    },

    async _checkAvailability() {
        try {
            const status = await API.aiStatus();
            this._available = status.available;
        } catch {
            this._available = false;
        }

        const toggle = document.getElementById('btnAiToggle');
        if (!this._available) {
            toggle.style.display = 'none';
            this._container.classList.remove('open');
            document.getElementById('workspace').classList.remove('chat-open');
        } else {
            toggle.style.display = '';
        }
    },

    toggle() {
        if (!this._available) return;
        const isOpen = this._container.classList.toggle('open');
        document.getElementById('workspace').classList.toggle('chat-open', isOpen);
        if (isOpen) {
            this._inputEl.focus();
        }
    },

    isOpen() {
        return this._container.classList.contains('open');
    },

    async _send() {
        const text = this._inputEl.value.trim();
        if (!text || this._busy) return;

        this._appendMessage('user', text);
        this._inputEl.value = '';
        this._setBusy(true);

        try {
            const result = await API.aiChat(text);
            if (result.error) {
                this._appendMessage('error', `Error: ${result.error}`);
            }
            if (result.actions && result.actions.length > 0) {
                this._appendActions(result.actions);
                await App.refreshSlaves();
            }
            if (result.response) {
                this._appendMessage('assistant', result.response);
            }
        } catch (e) {
            this._appendMessage('error', `Failed to reach AI: ${e.message}`);
        } finally {
            this._setBusy(false);
        }
    },

    async _openSettings() {
        try {
            const s = await API.getSettings();

            const keyInput = document.getElementById('settingsApiKey');
            keyInput.value = '';
            keyInput.placeholder = s.groq_api_key_masked || 'gsk_...';

            const statusEl = document.getElementById('settingsKeyStatus');
            if (s.groq_api_key_set) {
                const src = s.source === 'env' ? ' (from environment variable)' : ' (saved in config.json)';
                statusEl.textContent = `Key set: ${s.groq_api_key_masked}${src}`;
                statusEl.style.color = 'var(--success)';
            } else {
                statusEl.textContent = 'No key set. Get a free key at console.groq.com';
                statusEl.style.color = 'var(--text-dim)';
            }

            const modelSelect = document.getElementById('settingsModel');
            modelSelect.innerHTML = '';
            for (const m of s.available_models) {
                const opt = document.createElement('option');
                opt.value = m.id;
                opt.textContent = m.label;
                if (m.id === s.model) opt.selected = true;
                modelSelect.appendChild(opt);
            }

            document.getElementById('aiSettingsOverlay').classList.add('active');
        } catch (e) {
            console.error('Failed to load settings:', e);
        }
    },

    _closeSettings() {
        document.getElementById('aiSettingsOverlay').classList.remove('active');
    },

    async _saveSettings() {
        const key = document.getElementById('settingsApiKey').value.trim();
        const model = document.getElementById('settingsModel').value;

        const payload = { model };
        if (key) payload.groq_api_key = key;

        try {
            const result = await API.saveSettings(payload);
            this._closeSettings();
            if (result.ai_available && !this._available) {
                this._available = true;
                document.getElementById('btnAiToggle').style.display = '';
            }
            this._available = result.ai_available;
        } catch (e) {
            alert('Failed to save settings: ' + e.message);
        }
    },

    _formatAction(action) {
        const i = action.input;
        switch (action.tool) {
            case 'get_slaves':         return 'get slaves';
            case 'get_slave_details':  return 'get slave details';
            case 'get_operations':     return 'get operations';
            case 'toggle_slave':       return `toggle slave → ${i.enabled ? 'on' : 'off'}`;
            case 'remove_slave':       return 'remove slave';
            case 'reorder_slaves':     return 'reorder slaves';
            case 'duplicate_slave':    return 'duplicate slave';
            case 'edit_slave_property': return `edit slave: ${i.field} = ${i.value}`;
            case 'set_active_pdo':     return `set active pdo: ${i.pdo_type}[${i.pdo_idx}]`;
            case 'edit_pdo_entry':     return `edit pdo entry: ${i.pdo_type}[${i.pdo_idx}][${i.entry_idx}] ${i.field} → ${i.value}`;
            case 'add_pdo_entry':      return `add pdo entry: ${i.name} to ${i.pdo_type}[${i.pdo_idx}]`;
            case 'remove_pdo_entry':   return `remove pdo entry: ${i.pdo_type}[${i.pdo_idx}][${i.entry_idx}]`;
            default:                   return action.tool.replace(/_/g, ' ');
        }
    },

    _appendActions(actions) {
        const container = document.createElement('div');
        container.className = 'chat-msg chat-msg-tools';

        const list = document.createElement('div');
        list.className = 'chat-tools-list';

        for (const action of actions) {
            const chip = document.createElement('div');
            chip.className = 'chat-tool-chip';
            chip.title = JSON.stringify(action.input, null, 2);
            chip.textContent = this._formatAction(action);
            list.appendChild(chip);
        }

        container.appendChild(list);
        this._messagesEl.appendChild(container);
        this._messagesEl.scrollTop = this._messagesEl.scrollHeight;
    },

    _appendMessage(role, text) {
        const msg = document.createElement('div');
        msg.className = `chat-msg chat-msg-${role}`;

        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble';
        bubble.innerHTML = this._renderMarkdown(text);

        msg.appendChild(bubble);
        this._messagesEl.appendChild(msg);
        this._messagesEl.scrollTop = this._messagesEl.scrollHeight;
    },

    _renderMarkdown(text) {
        return text
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\n/g, '<br>');
    },

    _setBusy(busy) {
        this._busy = busy;
        this._sendBtn.disabled = busy;
        this._inputEl.disabled = busy;

        const existing = this._messagesEl.querySelector('.chat-thinking');
        if (busy && !existing) {
            const el = document.createElement('div');
            el.className = 'chat-msg chat-msg-assistant chat-thinking';
            el.innerHTML = '<div class="chat-bubble"><span class="dot-pulse"><span></span><span></span><span></span></span></div>';
            this._messagesEl.appendChild(el);
            this._messagesEl.scrollTop = this._messagesEl.scrollHeight;
        } else if (!busy && existing) {
            existing.remove();
        }
    },

    async _clearHistory() {
        try {
            await API.aiClear();
        } catch { /* ignore */ }
        this._messagesEl.innerHTML = '';
        this._appendMessage('assistant', 'Chat history cleared. How can I help you with the ENI configuration?');
    },
};
