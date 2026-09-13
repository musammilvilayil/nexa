/**
 * NEXA Level 5 Autonomous Personal AI OS — Desktop Client Controller
 */

const API_BASE = (window.location.protocol && window.location.protocol.startsWith('http') && window.location.host)
  ? window.location.origin
  : 'http://127.0.0.1:8765';

const WS_BASE = (window.location.protocol && window.location.protocol.startsWith('http') && window.location.host)
  ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`
  : 'ws://127.0.0.1:8765/ws';

// Export early window global helpers so HTML onclick attributes never hit undefined
window.resumeTask = (id) => (window.app ? window.app.resumeTask(id) : console.warn('[NEXA] App not yet ready for resumeTask'));
window.pauseTask = (id) => (window.app ? window.app.pauseTask(id) : console.warn('[NEXA] App not yet ready for pauseTask'));
window.cancelTask = (id) => (window.app ? window.app.cancelTask(id) : console.warn('[NEXA] App not yet ready for cancelTask'));
window.retryTask = (id) => (window.app ? window.app.retryTask(id) : console.warn('[NEXA] App not yet ready for retryTask'));
window.stopTask = (id) => (window.app ? window.app.stopTask(id) : console.warn('[NEXA] App not yet ready for stopTask'));
window.startTask = (goal) => (window.app ? window.app.startTask(goal) : console.warn('[NEXA] App not yet ready for startTask'));
window.sendPrompt = (text) => (window.app ? window.app.sendPrompt(text) : console.warn('[NEXA] App not yet ready for sendPrompt'));
window.sendCommand = (cmd) => (window.app ? window.app.executeCommand(cmd) : console.warn('[NEXA] App not yet ready for sendCommand'));

let _backendOfflineLogged = false;

async function apiFetch(endpoint, options = {}) {
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE}${endpoint}`;
  try {
    const res = await fetch(url, options);
    if (_backendOfflineLogged) {
      console.log(`[NEXA] Connection restored to ${API_BASE}`);
      _backendOfflineLogged = false;
    }
    return res;
  } catch (err) {
    if (!_backendOfflineLogged) {
      console.warn(`[NEXA] Backend not reachable at ${API_BASE}. Entering offline/reconnect mode.`);
      _backendOfflineLogged = true;
    }
    throw new Error(`Unable to reach NEXA server at ${API_BASE}. Ensure backend is running.`);
  }
}

class NexaApp {
  constructor() {
    this.ws = null;
    this.connectionState = 'CONNECTING';
    this.wsBackoffMs = 1000;
    this.maxWsBackoffMs = 30000;
    this.wsReconnectTimer = null;
    this.restPollingTimer = null;
    this.activeView = 'chat';
    this.voiceRecognition = null;
    this.isListening = false;
    this.isSpeaking = false;
    this.ttsMuted = false;
    this.activeTask = null;
    this.pendingConfirmation = null;
    this.cooldownInterval = null;
    this.currentConversationId = null;
    this.currentMode = 'auto';

    this.initDOM();
    this.initWebSocket();
    this.initVoice();
    this.startMetricsPolling();
    this.loadConversations().catch(() => {});
  }

  initDOM() {
    // Nav buttons
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.addEventListener('click', () => this.switchView(btn.dataset.view));
    });

    // Chat Mode Chips
    document.querySelectorAll('.mode-chip').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.mode-chip').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.currentMode = btn.dataset.mode;
        this.showToast(`Mode set to ${btn.textContent.trim()}`);
      });
    });

    // Theme toggle
    const themeBtn = document.getElementById('btn-theme-toggle');
    if (themeBtn) {
      themeBtn.addEventListener('click', () => {
        const html = document.documentElement;
        const current = html.getAttribute('data-theme') || 'dark';
        const next = current === 'dark' ? 'light' : 'dark';
        html.setAttribute('data-theme', next);
      });
    }

    // Input & Send
    const input = document.getElementById('command-input');
    const sendBtn = document.getElementById('btn-send');
    if (sendBtn && input) {
      sendBtn.addEventListener('click', () => this.handleSendCommand());
      input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          this.handleSendCommand();
        }
      });
    }

    // Mic button
    const micBtn = document.getElementById('btn-mic');
    if (micBtn) {
      micBtn.addEventListener('click', () => this.toggleVoice());
    }

    // Emergency Stop
    const stopBtn = document.getElementById('btn-stop');
    if (stopBtn) {
      stopBtn.addEventListener('click', () => this.triggerEmergencyStop());
    }

    // Confirmation Buttons
    const cancelConfirmBtn = document.getElementById('btn-confirm-cancel');
    const acceptConfirmBtn = document.getElementById('btn-confirm-accept');
    if (cancelConfirmBtn) {
      cancelConfirmBtn.addEventListener('click', () => this.cancelPendingConfirmation());
    }
    if (acceptConfirmBtn) {
      acceptConfirmBtn.addEventListener('click', () => this.acceptPendingConfirmation());
    }

    // New task button (New Chat)
    const newTaskBtn = document.getElementById('btn-new-task');
    if (newTaskBtn) {
      newTaskBtn.addEventListener('click', () => {
        this.createNewConversation().catch(() => {});
        this.switchView('chat');
        if (input) input.focus();
      });
    }

    this.initTrainingUI();

    // Settings actions
    const chkAutostart = document.getElementById('chk-autostart');
    if (chkAutostart) {
      chkAutostart.addEventListener('change', async (e) => {
        try {
          const res = await apiFetch('/api/autostart', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enable: e.target.checked }),
          });
          const data = await res.json();
          this.showToast(data.enabled ? 'Auto-start enabled' : 'Auto-start disabled');
        } catch (err) {
          this.showToast('Failed to update auto-start', 'error');
        }
      });
    }

    const btnSettingsStop = document.getElementById('btn-settings-stop');
    if (btnSettingsStop) {
      btnSettingsStop.addEventListener('click', () => this.triggerEmergencyStop());
    }

    const btnSettingsReset = document.getElementById('btn-settings-reset');
    if (btnSettingsReset) {
      btnSettingsReset.addEventListener('click', async () => {
        await apiFetch('/api/failsafe/reset', { method: 'POST' });
        this.showToast('Failsafe monitor reset');
      });
    }

    // Voice Mute Toggle
    const btnVoiceMute = document.getElementById('btn-voice-mute');
    if (btnVoiceMute) {
      btnVoiceMute.addEventListener('click', () => {
        this.ttsMuted = !this.ttsMuted;
        btnVoiceMute.textContent = this.ttsMuted ? '🔇 Sound Off' : '🔊 Sound On';
        if (this.ttsMuted && window.speechSynthesis) {
          window.speechSynthesis.cancel();
        }
      });
    }

    // Expose prompt helper for chip buttons
    window.sendPrompt = (text) => {
      if (input) {
        input.value = text;
        this.handleSendCommand();
      }
    };
  }

  setConnectionState(state, detail = '') {
    this.connectionState = state;
    const badge = document.getElementById('badge-online');
    const sideStatus = document.getElementById('sidebar-status-text');
    const dot = document.querySelector('.sidebar-footer .status-indicator-pill .dot');

    if (state === 'CONNECTED') {
      if (badge) {
        badge.textContent = 'ONLINE';
        badge.className = 'status-badge green';
      }
      if (sideStatus) {
        sideStatus.textContent = 'NEXA READY';
      }
      if (dot) {
        dot.className = 'dot pulse-green';
      }
    } else if (state === 'CONNECTING') {
      if (badge) {
        badge.textContent = 'CONNECTING...';
        badge.className = 'status-badge';
      }
      if (sideStatus) {
        sideStatus.textContent = 'CONNECTING...';
      }
      if (dot) {
        dot.className = 'dot';
      }
    } else if (state === 'POLLING') {
      if (badge) {
        badge.textContent = 'POLLING';
        badge.className = 'status-badge amber';
      }
      if (sideStatus) {
        sideStatus.textContent = detail || 'LIVE (REST POLLING)';
      }
      if (dot) {
        dot.className = 'dot pulse-amber';
      }
    } else if (state === 'RECONNECTING') {
      if (badge) {
        badge.textContent = 'RECONNECTING';
        badge.className = 'status-badge amber';
      }
      if (sideStatus) {
        sideStatus.textContent = detail || 'RECONNECTING...';
      }
      if (dot) {
        dot.className = 'dot pulse-amber';
      }
    } else { // OFFLINE, DISCONNECTED or ERROR
      if (badge) {
        badge.textContent = 'OFFLINE';
        badge.className = 'status-badge red';
      }
      if (sideStatus) {
        sideStatus.textContent = detail || 'BACKEND OFFLINE';
      }
      if (dot) {
        dot.className = 'dot pulse-red';
      }
    }
  }

  updateOnlineBadge(online) {
    this.setConnectionState(online ? 'CONNECTED' : 'RECONNECTING');
  }

  startRestPolling() {
    if (this.restPollingTimer) return;
    this.restFailures = 0;

    const scheduleNext = (delay) => {
      if (this.restPollingTimer) clearTimeout(this.restPollingTimer);
      this.restPollingTimer = setTimeout(pollRest, delay);
    };

    const pollRest = async () => {
      try {
        const [resStatus, resTasks] = await Promise.all([
          apiFetch('/api/status').then(r => r.ok ? r.json() : null).catch(() => null),
          apiFetch('/api/tasks').then(r => r.ok ? r.json() : null).catch(() => null),
        ]);
        if (resStatus) {
          this.restFailures = 0;
          this.setConnectionState('POLLING');
          this.updateStatusUI(resStatus);
          if (resTasks && this.activeView === 'tasks') this.renderTasks(resTasks.tasks || []);
          scheduleNext(3000);
        } else {
          this.restFailures = (this.restFailures || 0) + 1;
          const backoff = Math.min(3000 * Math.pow(1.5, Math.min(this.restFailures, 6)), 30000);
          if (this.restFailures >= 2) {
            this.setConnectionState('OFFLINE', `SERVER OFFLINE (Retrying in ${Math.round(backoff / 1000)}s)`);
          }
          scheduleNext(backoff);
        }
      } catch (e) {
        this.restFailures = (this.restFailures || 0) + 1;
        const backoff = Math.min(3000 * Math.pow(1.5, Math.min(this.restFailures, 6)), 30000);
        if (this.restFailures >= 2) {
          this.setConnectionState('OFFLINE', `SERVER OFFLINE (Retrying in ${Math.round(backoff / 1000)}s)`);
        }
        scheduleNext(backoff);
      }
    };
    pollRest();
  }

  stopRestPolling() {
    if (this.restPollingTimer) {
      clearTimeout(this.restPollingTimer);
      this.restPollingTimer = null;
    }
  }

  initWebSocket() {
    if (this.wsReconnectTimer) {
      clearTimeout(this.wsReconnectTimer);
      this.wsReconnectTimer = null;
    }
    if (this.ws) {
      try {
        this.ws.onopen = null;
        this.ws.onmessage = null;
        this.ws.onclose = null;
        this.ws.onerror = null;
        this.ws.close();
      } catch (e) {}
      this.ws = null;
    }

    this.setConnectionState(this.wsBackoffMs > 1000 ? 'RECONNECTING' : 'CONNECTING');

    try {
      this.ws = new WebSocket(WS_BASE);

      this.ws.onopen = () => {
        console.log('[NEXA] WebSocket connected successfully to', WS_BASE);
        this.wsBackoffMs = 1000;
        this._wsMaxLogged = false;
        this.setConnectionState('CONNECTED');
        this.stopRestPolling();
        this.loadConversations().catch(() => {});
        if (this.activeView === 'tasks') this.loadTasks().catch(() => {});
      };

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleServerMessage(data);
        } catch (err) {
          console.error('[NEXA] Error parsing WS message:', err);
        }
      };

      this.ws.onclose = (event) => {
        const delay = this.wsBackoffMs;
        if (delay < this.maxWsBackoffMs || !this._wsMaxLogged) {
          console.warn(`[NEXA] WebSocket disconnected. Reconnecting in ${delay}ms... (code: ${event.code})`);
          if (delay >= this.maxWsBackoffMs) this._wsMaxLogged = true;
        }
        this.setConnectionState('RECONNECTING', `RETRYING (${Math.round(delay / 1000)}s)`);
        this.startRestPolling();

        // Bounded exponential backoff
        this.wsBackoffMs = Math.min(this.wsBackoffMs * 2, this.maxWsBackoffMs);
        this.wsReconnectTimer = setTimeout(() => this.initWebSocket(), delay);
      };

      this.ws.onerror = (err) => {
        // Soft fallback to polling without flooding uncaught exceptions
        this.startRestPolling();
      };
    } catch (e) {
      console.warn('[NEXA] Failed to initialize WebSocket:', e);
      this.setConnectionState('ERROR');
      this.startRestPolling();
      const delay = this.wsBackoffMs;
      this.wsBackoffMs = Math.min(this.wsBackoffMs * 2, this.maxWsBackoffMs);
      this.wsReconnectTimer = setTimeout(() => this.initWebSocket(), delay);
    }
  }

  handleServerMessage(msg) {
    if (msg.type === 'init') {
      this.updateStatusUI(msg.status);
      this.updateMetricsUI(msg.metrics);
    } else if (msg.type === 'event') {
      this.handleEvent(msg.event);
    } else if (msg.type === 'command_result') {
      this.handleCommandResult(msg);
    } else if (msg.type === 'confirm_result') {
      this.hideConfirmationCard();
      if (msg.result && msg.result.message) {
        this.appendNexaResponse(msg.result.message);
      }
      this.showToast('Action authorization processed');
    } else if (msg.type === 'cancel_result') {
      this.hideConfirmationCard();
      if (msg.result && msg.result.message) {
        this.appendNexaResponse(msg.result.message);
      }
      this.showToast('Action cancelled');
    }
  }

  handleEvent(evt) {
    const type = evt.event_type;

    // Update live task card
    if (type === 'TASK_CREATED' || type === 'TASK_STARTED') {
      this.showLiveTaskCard(evt.title, evt.message);
      this.loadTasks();
    } else if (type === 'TASK_PROGRESS') {
      this.updateLiveTaskProgress(evt);
    } else if (type === 'TASK_COMPLETED') {
      this.completeLiveTask(evt);
      this.loadTasks();
    } else if (type === 'TASK_FAILED') {
      this.failLiveTask(evt);
      this.loadTasks();
    } else if (type === 'TASK_PAUSED') {
      this.showToast(evt.message || 'Task paused', 'info');
      this.loadTasks();
    } else if (type === 'TASK_RESUMED') {
      this.showToast(evt.message || 'Task resumed', 'success');
      this.loadTasks();
    } else if (type === 'TASK_CANCELLED') {
      this.showToast(evt.message || 'Task cancelled', 'warning');
      this.loadTasks();
    } else if (type === 'CONFIRMATION_REQUIRED') {
      this.showConfirmationCard(evt);
    } else if (type === 'SYSTEM_HEALTH_CHANGED') {
      this.showToast(`${evt.title}: ${evt.message}`);
    }

    // Append progressive step card into conversation
    if (['SECURITY_CHECK', 'TOOL_STARTED', 'TOOL_COMPLETED', 'VERIFICATION_STARTED', 'VERIFICATION_PASSED', 'RECOVERY_STARTED'].includes(type)) {
      this.appendProgressiveStep(evt);
    }

    // Training UI hooks
    if (type === 'TASK_STEP_COMPLETED' || type.startsWith('CAPABILITY_') || type === 'TASK_STARTED' || type === 'TASK_COMPLETED') {
      this.appendTrainingEvent(evt);
      if (evt.payload && evt.payload.progress_pct !== undefined) {
        this.updateTrainingUI({ stats: evt.payload, is_running: type !== 'TASK_COMPLETED' });
        const taskCurr = document.getElementById('training-curr-task');
        const catCurr = document.getElementById('training-curr-category');
        if (taskCurr) taskCurr.textContent = `Task #${evt.payload.task_id || '-'}`;
        if (catCurr) catCurr.textContent = evt.payload.category || '-';
      }
    }
  }

  showLiveTaskCard(title, message) {
    const card = document.getElementById('live-task-card');
    if (!card) return;
    card.classList.remove('hidden');

    const titleEl = document.getElementById('task-card-title');
    const currentEl = document.getElementById('task-current-step');
    const pctEl = document.getElementById('task-card-pct');
    const barEl = document.getElementById('task-card-bar');

    if (titleEl) titleEl.textContent = title;
    if (currentEl) currentEl.textContent = message || 'Processing...';
    if (pctEl) pctEl.textContent = '20%';
    if (barEl) barEl.style.width = '20%';
  }

  updateLiveTaskProgress(evt) {
    const card = document.getElementById('live-task-card');
    if (!card) return;
    card.classList.remove('hidden');

    const currentEl = document.getElementById('task-current-step');
    const completedEl = document.getElementById('task-completed-steps');
    const pctEl = document.getElementById('task-card-pct');
    const barEl = document.getElementById('task-card-bar');

    if (currentEl) currentEl.textContent = evt.message;
    if (evt.data && evt.data.steps) {
      if (completedEl) completedEl.textContent = `${evt.data.steps.length} steps planned`;
      if (pctEl) pctEl.textContent = '65%';
      if (barEl) barEl.style.width = '65%';
    }
  }

  completeLiveTask(evt) {
    const pctEl = document.getElementById('task-card-pct');
    const barEl = document.getElementById('task-card-bar');
    const currentEl = document.getElementById('task-current-step');
    const stateEl = document.getElementById('task-badge-state');

    if (pctEl) pctEl.textContent = '100%';
    if (barEl) barEl.style.width = '100%';
    if (currentEl) currentEl.textContent = 'Task completed successfully ✓';
    if (stateEl) stateEl.textContent = 'DONE';

    setTimeout(() => {
      const card = document.getElementById('live-task-card');
      if (card) card.classList.add('hidden');
    }, 4000);
  }

  failLiveTask(evt) {
    const currentEl = document.getElementById('task-current-step');
    const stateEl = document.getElementById('task-badge-state');
    if (currentEl) currentEl.textContent = `Failed: ${evt.message}`;
    if (stateEl) {
      stateEl.textContent = 'FAILED';
      stateEl.style.color = 'var(--accent-red)';
    }
  }

  showConfirmationCard(evt) {
    const card = document.getElementById('confirmation-card');
    if (!card) return;
    card.classList.remove('hidden');

    this.pendingConfirmation = evt.data || {};
    const actionEl = document.getElementById('confirm-action-name');
    const paramsEl = document.getElementById('confirm-params-json');
    const riskEl = document.getElementById('confirm-risk-badge');
    const acceptBtn = document.getElementById('btn-confirm-accept');
    const timerEl = document.getElementById('confirm-cooldown-timer');

    if (actionEl) actionEl.textContent = `${evt.data.skill || 'Operation'}.${evt.data.operation || 'action'}`;
    if (paramsEl) paramsEl.textContent = JSON.stringify(evt.data.params || {}, null, 2);
    if (riskEl) {
      riskEl.textContent = (evt.data.risk || 'MUTATE').toUpperCase();
    }

    // If critical risk, start 5-second mandatory cooldown countdown
    if (evt.data.risk === 'critical') {
      let remaining = 5;
      if (acceptBtn) acceptBtn.disabled = true;
      if (timerEl) timerEl.textContent = ` (${remaining}s cooldown)`;

      if (this.cooldownInterval) clearInterval(this.cooldownInterval);
      this.cooldownInterval = setInterval(() => {
        remaining -= 1;
        if (remaining <= 0) {
          clearInterval(this.cooldownInterval);
          if (acceptBtn) acceptBtn.disabled = false;
          if (timerEl) timerEl.textContent = '';
        } else {
          if (timerEl) timerEl.textContent = ` (${remaining}s cooldown)`;
        }
      }, 1000);
    } else {
      if (acceptBtn) acceptBtn.disabled = false;
      if (timerEl) timerEl.textContent = '';
    }
  }

  hideConfirmationCard() {
    const card = document.getElementById('confirmation-card');
    if (card) card.classList.add('hidden');
    if (this.cooldownInterval) clearInterval(this.cooldownInterval);
    this.pendingConfirmation = null;
  }

  acceptPendingConfirmation() {
    if (!this.pendingConfirmation || !this.pendingConfirmation.action_id) return;
    const actionId = this.pendingConfirmation.action_id;
    this.hideConfirmationCard();
    this.showToast('Action authorization processing...');
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        action: 'confirm',
        action_id: actionId,
      }));
    } else {
      apiFetch('/api/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_id: actionId }),
      })
      .then(res => res.json())
      .then(data => {
        if (data && data.message) this.appendNexaResponse(data.message);
        this.showToast('Action authorization processed');
      })
      .catch(err => {
        this.showToast('Confirmation failed: ' + err.message);
      });
    }
  }

  cancelPendingConfirmation() {
    if (!this.pendingConfirmation || !this.pendingConfirmation.action_id) return;
    const actionId = this.pendingConfirmation.action_id;
    this.hideConfirmationCard();
    this.showToast('Action cancelling...');
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({
        action: 'cancel',
        action_id: actionId,
      }));
    } else {
      apiFetch('/api/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action_id: actionId }),
      })
      .then(res => res.json())
      .then(data => {
        if (data && data.message) this.appendNexaResponse(data.message);
        this.showToast('Action cancelled');
      })
      .catch(err => {
        this.showToast('Cancellation failed: ' + err.message);
      });
    }
  }

  appendProgressiveStep(evt) {
    const feed = document.getElementById('conversation-feed');
    if (!feed) return;

    const step = document.createElement('div');
    step.className = 'progressive-step';
    step.innerHTML = `<span>⚡</span><span>[${evt.event_type}] ${evt.title}: ${evt.message}</span>`;
    feed.appendChild(step);
    feed.scrollTop = feed.scrollHeight;
  }

  async loadConversations() {
    try {
      const res = await apiFetch('/api/conversations');
      if (!res.ok) return;
      const data = await res.json();
      const listEl = document.getElementById('recent-chats-list');
      if (!listEl) return;
      listEl.innerHTML = '';
      (data.conversations || []).forEach(conv => {
        const item = document.createElement('div');
        item.className = 'chat-item' + (conv.id === this.currentConversationId ? ' active' : '');
        item.innerHTML = `
          <span class="chat-title">${this.escapeHtml(conv.title)}</span>
          <button class="chat-delete-btn" title="Delete chat">✕</button>
        `;
        item.addEventListener('click', (e) => {
          if (e.target.classList.contains('chat-delete-btn')) {
            e.stopPropagation();
            this.deleteConversation(conv.id).catch(() => {});
          } else {
            this.switchConversation(conv.id).catch(() => {});
          }
        });
        listEl.appendChild(item);
      });
    } catch (err) {
      // Offline / handled gracefully
    }
  }

  async createNewConversation() {
    try {
      const res = await apiFetch('/api/conversations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'New Chat' }),
      });
      if (!res.ok) return;
      const data = await res.json();
      this.currentConversationId = data.conversation_id;
      const feed = document.getElementById('conversation-feed');
      if (feed) {
        feed.innerHTML = `
          <div class="message nexa-message">
            <div class="message-avatar">◈</div>
            <div class="message-bubble">
              <p>New conversation started. How can I assist you today?</p>
            </div>
            <span class="message-time">Ready</span>
          </div>
        `;
      }
      this.loadConversations().catch(() => {});
    } catch (err) {
      // Offline / handled gracefully
    }
  }

  async switchConversation(convId) {
    try {
      this.currentConversationId = convId;
      const res = await apiFetch(`/api/conversations/${convId}`);
      if (!res.ok) {
        this.showToast('Could not load conversation', 'warning');
        return;
      }
      const conv = await res.json();
      const feed = document.getElementById('conversation-feed');
      if (!feed) return;
      feed.innerHTML = '';
      (conv.messages || []).forEach(m => {
        if (m.role === 'user') {
          this.appendUserMessage(m.content);
        } else {
          this.appendNexaResponse(m.content);
        }
      });
      this.loadConversations().catch(() => {});
    } catch (err) {
      this.showToast('Server offline - unable to switch conversation', 'warning');
    }
  }

  async deleteConversation(convId) {
    try {
      await apiFetch(`/api/conversations/${convId}`, { method: 'DELETE' });
      if (this.currentConversationId === convId) {
        this.createNewConversation();
      } else {
        this.loadConversations();
      }
    } catch (err) {
      console.warn('Failed to delete conversation', err);
    }
  }

  handleSendCommand() {
    const input = document.getElementById('command-input');
    if (!input) return;
    const text = input.value.trim();
    if (!text) return;

    // Append user message
    this.appendUserMessage(text);
    input.value = '';

    const payload = {
      action: 'command',
      command: text,
      text: text,
      conversation_id: this.currentConversationId,
      mode: this.currentMode,
    };

    // Send to WebSocket
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    } else {
      // Fallback to REST
      apiFetch('/api/command', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      .then(async res => {
        if (!res.ok) {
          const errText = await res.text();
          throw new Error(`Server returned status ${res.status}: ${errText}`);
        }
        return res.json();
      })
      .then(data => {
        if (data.conversation_id && !this.currentConversationId) {
          this.currentConversationId = data.conversation_id;
        }
        this.handleCommandResult({ command: text, result: data });
      })
      .catch(err => {
        const isNetwork = err.message && (err.message.includes('Unable to reach') || err.message.includes('Failed to fetch'));
        const errDisplay = isNetwork
          ? `⚠️ **Backend Connection Failure**\n\nUnable to connect to NEXA backend at \`${API_BASE}\`.\n\nPlease verify that the NEXA server is running:\n\`python -m ui.launcher\` (or \`python -m ui.server\`).`
          : `Error executing command: ${err.message}`;
        this.appendNexaResponse(errDisplay);
      });
    }
  }

  appendUserMessage(text) {
    const feed = document.getElementById('conversation-feed');
    if (!feed) return;

    const msg = document.createElement('div');
    msg.className = 'message user-message';
    msg.innerHTML = `
      <div class="message-bubble">
        <p>${this.escapeHtml(text)}</p>
      </div>
      <span class="message-time">${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
    `;
    feed.appendChild(msg);
    feed.scrollTop = feed.scrollHeight;
  }

  appendNexaResponse(text) {
    const feed = document.getElementById('conversation-feed');
    if (!feed) return;

    const msg = document.createElement('div');
    msg.className = 'message nexa-message';
    msg.innerHTML = `
      <div class="message-avatar">◈</div>
      <div class="message-bubble">
        <p>${this.formatMarkdown(text)}</p>
      </div>
      <span class="message-time">${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
    `;
    feed.appendChild(msg);
    feed.scrollTop = feed.scrollHeight;

    // Speak response if TTS is enabled
    this.speakResponse(text);
  }

  handleCommandResult(msg) {
    const res = msg.result || {};
    if (res.status === 'confirmation_required' && res.pending) {
      this.showConfirmationCard({ data: res.pending });
    }
    if (res.message) {
      this.appendNexaResponse(res.message);
    }
    this.loadConversations();
  }

  speakResponse(text) {
    if (this.ttsMuted || !window.speechSynthesis) return;

    // Provide concise spoken summary if text is long
    let toSpeak = text;
    if (text.length > 200) {
      const firstSentence = text.split(/[.\n]/)[0];
      toSpeak = `${firstSentence}. Full details are displayed on your screen.`;
    }

    const utterance = new SpeechSynthesisUtterance(toSpeak);
    utterance.rate = 1.05;

    this.setMicState('speaking');
    const statusEl = document.getElementById('voice-tts-status');
    if (statusEl) statusEl.textContent = 'Speaking...';

    utterance.onend = () => {
      this.setMicState('idle');
      if (statusEl) statusEl.textContent = 'Standby';
    };

    utterance.onerror = () => {
      this.setMicState('idle');
      if (statusEl) statusEl.textContent = 'Standby';
    };

    window.speechSynthesis.speak(utterance);
  }

  initVoice() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (SpeechRecognition) {
      this.voiceRecognition = new SpeechRecognition();
      this.voiceRecognition.continuous = false;
      this.voiceRecognition.interimResults = true;
      this.voiceRecognition.lang = 'en-US';

      this.voiceRecognition.onstart = () => {
        this.isListening = true;
        this.setMicState('listening');
        const wave = document.getElementById('voice-wave');
        if (wave) wave.classList.remove('hidden');
      };

      this.voiceRecognition.onresult = (event) => {
        let transcript = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        const input = document.getElementById('command-input');
        if (input) input.value = transcript;
      };

      this.voiceRecognition.onend = () => {
        this.isListening = false;
        this.setMicState('idle');
        const wave = document.getElementById('voice-wave');
        if (wave) wave.classList.add('hidden');

        const input = document.getElementById('command-input');
        if (input && input.value.trim()) {
          this.handleSendCommand();
        }
      };

      this.voiceRecognition.onerror = (event) => {
        console.warn('Speech recognition error:', event.error);
        this.isListening = false;
        this.setMicState('error');
        setTimeout(() => this.setMicState('idle'), 2000);
      };
    }
  }

  toggleVoice() {
    if (!this.voiceRecognition) {
      this.showToast('Browser speech recognition not available. Please type your command.', 'error');
      return;
    }

    if (this.isListening) {
      this.voiceRecognition.stop();
    } else {
      this.voiceRecognition.start();
    }
  }

  setMicState(state) {
    const btn = document.getElementById('btn-mic');
    const label = document.getElementById('mic-label');
    if (!btn) return;

    btn.className = `mic-btn ${state}`;
    if (label) {
      if (state === 'listening') label.textContent = 'Listening...';
      else if (state === 'processing') label.textContent = 'Thinking...';
      else if (state === 'speaking') label.textContent = 'Speaking...';
      else if (state === 'error') label.textContent = 'Error';
      else label.textContent = 'Voice';
    }
  }

  triggerEmergencyStop() {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'failsafe_stop' }));
    }
    apiFetch('/api/failsafe/stop', { method: 'POST' });
    this.showToast('EMERGENCY STOP ACTIVATED', 'error');
  }

  switchView(viewName) {
    this.activeView = viewName;

    // Toggle active nav button
    document.querySelectorAll('.nav-item').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.view === viewName);
    });

    // Toggle view panels
    document.querySelectorAll('.view-panel').forEach(panel => {
      panel.classList.toggle('active', panel.id === `view-${viewName}`);
    });

    // Load data for specific view
    if (viewName === 'tasks') this.loadTasks();
    else if (viewName === 'memory') this.loadMemory();
    else if (viewName === 'extensions') this.loadExtensions();
    else if (viewName === 'mcp') this.loadMCP();
    else if (viewName === 'activity') this.loadActivity();
    else if (viewName === 'settings') this.loadSettings();
  }

  renderTasks(tasks) {
    const tbody = document.getElementById('tasks-tbody');
    if (!tbody) return;
    if (!tasks || tasks.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" class="text-center">No tasks recorded yet</td></tr>';
      return;
    }
    tbody.innerHTML = tasks.map(t => {
      const stateStr = String(t.state || '').toLowerCase();
      let badgeClass = '';
      if (stateStr === 'completed') badgeClass = 'green';
      else if (stateStr === 'running' || stateStr === 'in_progress') badgeClass = 'green';
      else if (stateStr === 'paused') badgeClass = 'amber';
      else if (stateStr === 'cancelled' || stateStr === 'failed') badgeClass = 'red';

      const isPaused = stateStr === 'paused';
      const isTerminal = stateStr === 'completed' || stateStr === 'cancelled';

      return `
        <tr>
          <td><code>${this.escapeHtml(t.task_id.substring(0, 8))}</code></td>
          <td>${this.escapeHtml(t.goal || 'Autonomous Goal')}</td>
          <td><span class="status-badge ${badgeClass}">${this.escapeHtml(stateStr.toUpperCase())}</span></td>
          <td>${t.current_step || 0} / ${t.total_steps || 1}</td>
          <td>${t.started_at ? this.escapeHtml(String(t.started_at).substring(11, 19) || '-') : '-'}</td>
          <td>
            ${!isPaused && !isTerminal ? `<button class="btn-secondary" onclick="app.pauseTask('${t.task_id}')">Pause</button>` : ''}
            ${isPaused ? `<button class="btn-secondary" onclick="app.resumeTask('${t.task_id}')">Resume</button>` : ''}
            ${!isTerminal ? `<button class="btn-secondary" onclick="app.cancelTask('${t.task_id}')">Cancel</button>` : ''}
            ${isTerminal ? `<button class="btn-secondary" onclick="app.retryTask('${t.task_id}')">Retry</button>` : ''}
          </td>
        </tr>
      `;
    }).join('');
  }

  async loadTasks() {
    const tbody = document.getElementById('tasks-tbody');
    if (!tbody) return;
    try {
      const res = await apiFetch('/api/tasks');
      if (!res.ok) return;
      const data = await res.json();
      this.renderTasks(data.tasks || []);
      const badge = document.getElementById('badge-tasks');
      if (badge && data.tasks) {
        const activeCount = data.tasks.filter(t => !['completed', 'cancelled'].includes(String(t.state).toLowerCase())).length;
        badge.textContent = activeCount;
      }
    } catch (e) {
      if (tbody.children.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="text-center text-secondary">Offline / Unable to load tasks</td></tr>';
      }
    }
  }

  async resumeTask(taskId) {
    if (!taskId) return;
    try {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: 'resume_task', task_id: taskId }));
      }
      const res = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId }),
      });
      const data = await res.json();
      if (data.success) {
        this.showToast(`Task ${taskId.substring(0, 8)} resumed`, 'success');
        await this.loadTasks();
      } else {
        this.showToast(`Failed to resume task: ${data.error || 'Unknown error'}`, 'error');
      }
    } catch (err) {
      console.error('[NEXA] Error resuming task:', err);
      this.showToast('Network error resuming task', 'error');
    }
  }

  async pauseTask(taskId) {
    if (!taskId) return;
    try {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: 'pause_task', task_id: taskId }));
      }
      const res = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId }),
      });
      const data = await res.json();
      if (data.success) {
        this.showToast(`Task ${taskId.substring(0, 8)} paused`, 'info');
        await this.loadTasks();
      } else {
        this.showToast(`Failed to pause task: ${data.error || 'Unknown error'}`, 'error');
      }
    } catch (err) {
      console.error('[NEXA] Error pausing task:', err);
      this.showToast('Network error pausing task', 'error');
    }
  }

  async cancelTask(taskId) {
    if (!taskId) return;
    try {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ action: 'cancel_task', task_id: taskId }));
      }
      const res = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId }),
      });
      const data = await res.json();
      if (data.success) {
        this.showToast(`Task ${taskId.substring(0, 8)} cancelled`, 'warning');
        await this.loadTasks();
      } else {
        this.showToast(`Failed to cancel task: ${data.error || 'Unknown error'}`, 'error');
      }
    } catch (err) {
      console.error('[NEXA] Error cancelling task:', err);
      this.showToast('Network error cancelling task', 'error');
    }
  }

  async retryTask(taskId) {
    if (!taskId) return;
    try {
      const res = await apiFetch(`/api/tasks/${encodeURIComponent(taskId)}/retry`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_id: taskId }),
      });
      const data = await res.json();
      if (data.success) {
        this.showToast(`Task ${taskId.substring(0, 8)} retried`, 'success');
        await this.loadTasks();
      } else {
        this.showToast(`Failed to retry task: ${data.error || 'Unknown error'}`, 'error');
      }
    } catch (err) {
      console.error('[NEXA] Error retrying task:', err);
      this.showToast('Network error retrying task', 'error');
    }
  }

  async stopTask(taskId) {
    return this.cancelTask(taskId);
  }

  async startTask(goal) {
    if (!goal) return;
    try {
      const res = await apiFetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal }),
      });
      const data = await res.json();
      if (data.success) {
        this.showToast(`Task started: ${data.task_id || ''}`, 'success');
        await this.loadTasks();
      } else {
        this.showToast(`Failed to start task: ${data.error || ''}`, 'error');
      }
      return data;
    } catch (e) {
      console.error('[NEXA] Error starting task:', e);
      this.showToast('Network error starting task', 'error');
    }
  }

  executeCommand(text) {
    return this.sendPrompt(text);
  }

  sendPrompt(text) {
    const input = document.getElementById('command-input');
    if (input) {
      input.value = text;
      this.handleSendCommand();
    }
  }

  async loadMemory() {
    const grid = document.getElementById('memory-grid');
    if (!grid) return;
    try {
      const res = await apiFetch('/api/memory');
      if (!res.ok) return;
      const data = await res.json();
      grid.innerHTML = (data.layers || []).map(l => `
        <div class="info-card">
          <div class="telemetry-header">
            <span>LAYER ${l.id}</span>
            <span class="status-badge green">${l.status}</span>
          </div>
          <h3>${l.name}</h3>
          <p>${l.summary}</p>
        </div>
      `).join('');
    } catch (e) {
      if (!grid.children.length) grid.innerHTML = '<p class="text-secondary">Offline / Unable to load memory snapshot</p>';
    }
  }

  async loadExtensions() {
    const grid = document.getElementById('extensions-grid');
    if (!grid) return;
    try {
      const res = await apiFetch('/api/extensions');
      if (!res.ok) return;
      const data = await res.json();
      grid.innerHTML = (data.extensions || []).map(e => `
        <div class="info-card">
          <div class="telemetry-header">
            <span>${e.category.toUpperCase()}</span>
            <span class="status-badge green">${e.status.toUpperCase()}</span>
          </div>
          <h3>${e.name} v${e.version}</h3>
          <p>${e.description}</p>
        </div>
      `).join('');
    } catch (e) {
      if (!grid.children.length) grid.innerHTML = '<p class="text-secondary">Offline / Unable to load extensions</p>';
    }
  }

  async loadMCP() {
    const grid = document.getElementById('mcp-grid');
    if (!grid) return;
    try {
      const res = await apiFetch('/api/mcp');
      if (!res.ok) return;
      const data = await res.json();
      grid.innerHTML = (data.tools || []).map(t => `
        <div class="info-card">
          <div class="telemetry-header">
            <span>SERVER: ${(t.server || 'LOCAL').toUpperCase()}</span>
            <span class="risk-badge">${t.risk_tier.toUpperCase()}</span>
          </div>
          <h3>${t.name}</h3>
          <p>${t.description}</p>
        </div>
      `).join('');
    } catch (e) {
      if (!grid.children.length) grid.innerHTML = '<p class="text-secondary">Offline / Unable to load MCP tools</p>';
    }
  }

  async loadActivity() {
    const stream = document.getElementById('activity-stream');
    if (!stream) return;
    try {
      const res = await apiFetch('/api/activity');
      if (!res.ok) return;
      const data = await res.json();
      if (!data.activities || data.activities.length === 0) {
        stream.innerHTML = '<p class="text-secondary">No recent activity logged</p>';
        return;
      }
      stream.innerHTML = data.activities.map(a => `
        <div class="activity-item">
          <span class="activity-time">${a.timestamp.substring(11, 19)}</span>
          <span class="activity-cat">${a.category.toUpperCase()}</span>
          <span class="activity-desc"><strong>${a.action}</strong>: ${JSON.stringify(a.details || {})}</span>
          <span class="status-badge green">${a.status}</span>
        </div>
      `).join('');
    } catch (e) {
      if (!stream.children.length) stream.innerHTML = '<p class="text-secondary">Offline / Unable to load activity stream</p>';
    }
  }

  async loadSettings() {
    try {
      const res = await apiFetch('/api/autostart');
      const data = await res.json();
      const chk = document.getElementById('chk-autostart');
      if (chk) chk.checked = !!data.enabled;
    } catch (e) {}
  }

  startMetricsPolling() {
    const fetchMetrics = async () => {
      // If offline or disconnected, back off significantly to avoid network storm
      if (this.connectionState === 'OFFLINE' || this.connectionState === 'ERROR') {
        this.metricsPollingTimer = setTimeout(fetchMetrics, 15000);
        return;
      }
      try {
        const res = await apiFetch('/api/metrics');
        if (res.ok) {
          const data = await res.json();
          this.updateMetricsUI(data);
        }
      } catch (err) {
        // silent on transient network hiccup
      }
      const delay = (this.connectionState === 'CONNECTED') ? 5000 : 10000;
      this.metricsPollingTimer = setTimeout(fetchMetrics, delay);
    };
    fetchMetrics();
  }

  stopMetricsPolling() {
    if (this.metricsPollingTimer) {
      clearTimeout(this.metricsPollingTimer);
      this.metricsPollingTimer = null;
    }
  }

  updateMetricsUI(metrics) {
    if (!metrics) return;

    // CPU
    if (metrics.cpu) {
      const cpuEl = document.getElementById('meter-cpu-val');
      const barEl = document.getElementById('meter-cpu-bar');
      if (cpuEl) cpuEl.textContent = `${metrics.cpu.cores} Cores (${metrics.cpu.architecture || 'win32'})`;
      if (barEl) barEl.style.width = '25%';
    }

    // RAM
    if (metrics.ram) {
      const ramEl = document.getElementById('meter-ram-val');
      const barEl = document.getElementById('meter-ram-bar');
      if (ramEl) ramEl.textContent = `${metrics.ram.used_gb} / ${metrics.ram.total_gb} GB (${metrics.ram.used_percent}%)`;
      if (barEl) barEl.style.width = `${metrics.ram.used_percent}%`;
    }

    // Drives
    if (metrics.drives) {
      const c = metrics.drives['C:'];
      if (c) {
        const ssdVal = document.getElementById('meter-ssd-val');
        const ssdBar = document.getElementById('meter-ssd-bar');
        if (ssdVal) ssdVal.textContent = `${c.free_gb} GB Free (${c.free_percent}%)`;
        if (ssdBar) ssdBar.style.width = `${100 - c.free_percent}%`;
      }
      const d = metrics.drives['D:'];
      if (d) {
        const hddVal = document.getElementById('meter-hdd-val');
        const hddBar = document.getElementById('meter-hdd-bar');
        if (hddVal) hddVal.textContent = `${d.free_gb} GB Free (${d.free_percent}%)`;
        if (hddBar) hddBar.style.width = `${100 - d.free_percent}%`;
      }
    }
  }

  updateStatusUI(status) {
    if (!status) return;
    const failsafeEl = document.getElementById('telemetry-failsafe');
    if (failsafeEl) {
      failsafeEl.textContent = status.failsafe || 'ACTIVE';
      failsafeEl.className = status.failsafe === 'ACTIVE' ? 'text-green' : 'text-red';
    }

    const secgateEl = document.getElementById('telemetry-secgate');
    if (secgateEl && status.security_gate) {
      secgateEl.textContent = status.security_gate;
    }

    const browserEl = document.getElementById('telemetry-browser');
    if (browserEl) {
      browserEl.textContent = 'Chromium Ready';
    }

    const voiceEl = document.getElementById('telemetry-voice');
    if (voiceEl && status.voice) {
      voiceEl.textContent = `${status.voice.mic || 'Mic'} / ${status.voice.tts || 'TTS'}`;
    }

    const badgeMcp = document.getElementById('badge-mcp');
    if (badgeMcp && status.mcp_tools_count !== undefined) {
      badgeMcp.textContent = status.mcp_tools_count;
    }
  }

  showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }

  escapeHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  formatMarkdown(text) {
    let formatted = this.escapeHtml(text);
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    formatted = formatted.replace(/\n/g, '<br>');
    return formatted;
  }

  initTrainingUI() {
    const btnStart = document.getElementById('btn-training-start');
    const btnPause = document.getElementById('btn-training-pause');
    const btnResume = document.getElementById('btn-training-resume');
    const btnStop = document.getElementById('btn-training-stop');
    const btnPilot = document.getElementById('btn-training-pilot');

    if (btnStart) {
      btnStart.addEventListener('click', async () => {
        try {
          const res = await apiFetch('/api/training/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
          });
          const data = await res.json();
          this.showToast(data.message || 'Training started', data.success ? 'success' : 'warning');
          this.fetchTrainingStatus();
        } catch (e) {
          this.showToast('Failed to start training', 'error');
        }
      });
    }

    if (btnPilot) {
      btnPilot.addEventListener('click', async () => {
        try {
          const res = await apiFetch('/api/training/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ max_tasks: 100 }),
          });
          const data = await res.json();
          this.showToast(data.message || 'Pilot started (100 tasks)', data.success ? 'success' : 'warning');
          this.fetchTrainingStatus();
        } catch (e) {
          this.showToast('Failed to start pilot', 'error');
        }
      });
    }

    if (btnPause) {
      btnPause.addEventListener('click', async () => {
        try {
          const res = await apiFetch('/api/training/pause', { method: 'POST' });
          const data = await res.json();
          this.showToast(data.message || 'Training paused');
          this.fetchTrainingStatus();
        } catch (e) {
          this.showToast('Failed to pause training', 'error');
        }
      });
    }

    if (btnResume) {
      btnResume.addEventListener('click', async () => {
        try {
          const res = await apiFetch('/api/training/resume', { method: 'POST' });
          const data = await res.json();
          this.showToast(data.message || 'Training resumed');
          this.fetchTrainingStatus();
        } catch (e) {
          this.showToast('Failed to resume training', 'error');
        }
      });
    }

    if (btnStop) {
      btnStop.addEventListener('click', async () => {
        try {
          const res = await apiFetch('/api/training/stop', { method: 'POST' });
          const data = await res.json();
          this.showToast(data.message || 'Training stopped', 'warning');
          this.fetchTrainingStatus();
        } catch (e) {
          this.showToast('Failed to stop training', 'error');
        }
      });
    }

    this.fetchTrainingStatus();
  }

  async fetchTrainingStatus() {
    try {
      const res = await apiFetch('/api/training/status');
      if (!res.ok) return;
      const data = await res.json();
      this.updateTrainingUI(data);
    } catch (e) {}
  }

  updateTrainingUI(data) {
    if (!data) return;
    const stats = data.stats || {};
    const progressEl = document.getElementById('training-stat-progress');
    const countEl = document.getElementById('training-stat-count');
    const rateEl = document.getElementById('training-stat-rate');
    const passedEl = document.getElementById('training-stat-passed');
    const failedEl = document.getElementById('training-stat-failed');
    const recEl = document.getElementById('training-stat-recovered');
    const skillsEl = document.getElementById('training-stat-skills');
    const bugsEl = document.getElementById('training-stat-bugs');
    const statusEl = document.getElementById('training-curr-status');

    if (progressEl) progressEl.textContent = `${stats.progress_pct || 0}%`;
    if (countEl) countEl.textContent = `${stats.completed_tasks || 0} / ${stats.total_tasks || 6075} Tasks`;
    if (rateEl) rateEl.textContent = `${stats.success_rate || 100}%`;
    if (passedEl) passedEl.textContent = stats.passed || 0;
    if (failedEl) failedEl.textContent = stats.failed || 0;
    if (recEl) recEl.textContent = stats.recovered || 0;
    if (skillsEl) skillsEl.textContent = stats.skills_built || 0;
    if (bugsEl) bugsEl.textContent = stats.bugs_fixed || 0;
    if (statusEl) {
      statusEl.textContent = data.is_running ? (data.is_paused ? 'PAUSED' : 'RUNNING') : 'IDLE';
      statusEl.className = data.is_running ? 'text-cyan' : 'text-green';
    }
  }

  appendTrainingEvent(evt) {
    const stream = document.getElementById('training-event-stream');
    if (!stream) return;
    const div = document.createElement('div');
    div.style.padding = '4px 8px';
    div.style.background = 'rgba(255,255,255,0.03)';
    div.style.borderRadius = '4px';
    div.innerHTML = `<span style="color: var(--cyan);">[${new Date().toLocaleTimeString()}]</span> <strong>${this.escapeHtml(evt.title || '')}:</strong> ${this.escapeHtml(evt.message || '')}`;
    stream.prepend(div);
    if (stream.children.length > 50) {
      stream.removeChild(stream.lastChild);
    }
  }
}

// Instantiate app on load and export globals
let app;
window.addEventListener('DOMContentLoaded', () => {
  app = new NexaApp();
  window.app = app;
  window.resumeTask = (id) => window.app && window.app.resumeTask(id);
  window.pauseTask = (id) => window.app && window.app.pauseTask(id);
  window.cancelTask = (id) => window.app && window.app.cancelTask(id);
  window.retryTask = (id) => window.app && window.app.retryTask(id);
  window.stopTask = (id) => window.app && window.app.cancelTask(id);
  window.startTask = (goal) => window.app && window.app.startTask(goal);
  window.sendPrompt = (text) => window.app && window.app.sendPrompt(text);
  window.sendCommand = (cmd) => window.app && window.app.executeCommand(cmd);
});
