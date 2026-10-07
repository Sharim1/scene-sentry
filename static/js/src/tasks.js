import { refreshClerkToken } from './clerk.js';
import { showToast, showRefreshToast } from './toasts.js';

/**
 * Task Notifications Alpine.js Component
 * Handles real-time task status updates via SSE
 * SSE connection starts immediately when a task is created
 */
function taskNotifications() {
    return {
        tasks: [],
        eventSource: null,
        sseConnected: false,
        connectionAttempts: 0,
        maxAttempts: 5,
        pollInterval: null,

        init() {
            if (document.body.dataset.authenticated !== 'true') {
                return;
            }
            // Load any existing tasks from sessionStorage
            const stored = sessionStorage.getItem('activeTasks');
            if (stored) {
                try {
                    const parsed = JSON.parse(stored);
                    // Keep tasks that are not dismissed (completed tasks will auto-dismiss)
                    this.tasks = parsed.filter(t => !t.dismissed);
                } catch (e) {
                    this.tasks = [];
                }
            }

            // Always do an initial poll to check for any running/recent tasks
            this.checkForActiveTasks();

            // Connect to SSE if there are active tasks
            if (this.tasks.length > 0) {
                this.connectSSE();
                this.startPolling();
            }

            // Listen for custom events to add tasks
            window.addEventListener('taskCreated', (e) => {
                this.addTask(e.detail);
                // Connect to SSE immediately when a task is created
                if (!this.sseConnected) {
                    this.connectSSE();
                }
                // Start polling as backup for SSE
                this.startPolling();
            });

            // Re-initialize Lucide icons after Alpine renders
            this.$nextTick(() => {
                if (typeof lucide !== 'undefined') {
                    lucide.createIcons();
                }
            });
        },

        async checkForActiveTasks() {
            try {
                let response = await fetch('/api/tasks?active_only=true');
                if (response.status === 401) {
                    const refreshed = await refreshClerkToken();
                    if (refreshed) {
                        response = await fetch('/api/tasks?active_only=true');
                    }
                }
                if (response.ok) {
                    const data = await response.json();
                    if (data.tasks && data.tasks.length > 0) {
                        data.tasks.forEach(task => this.handleTaskUpdate(task));
                        if (!this.sseConnected) {
                            this.connectSSE();
                        }
                        this.startPolling();
                    }
                }
            } catch (e) {
                // Ignore errors on initial check
            }
        },

        connectSSE() {
            // Don't reconnect if already connected or too many attempts
            if (this.sseConnected || typeof EventSource === 'undefined') return;
            if (this.connectionAttempts >= this.maxAttempts) {
                console.warn('Max SSE connection attempts reached, falling back to polling');
                this.startPolling();
                return;
            }

            this.connectionAttempts++;

            try {
                this.eventSource = new EventSource('/api/tasks/stream');
                this.sseConnected = true;

                this.eventSource.onopen = () => {
                    console.log('SSE connected');
                    this.connectionAttempts = 0; // Reset on successful connection
                };

                this.eventSource.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        // Skip keepalive and connected messages
                        if (data.type === 'keepalive' || data.type === 'connected') return;
                        this.handleTaskUpdate(data);
                    } catch (e) {
                        // Ignore parse errors for non-JSON messages
                    }
                };

                this.eventSource.onerror = (error) => {
                    console.warn('SSE error, will retry or fall back to polling');
                    this.sseConnected = false;
                    if (this.eventSource) {
                        this.eventSource.close();
                        this.eventSource = null;
                    }
                    const activeTasks = this.tasks.filter(t => t.status === 'running' || t.status === 'pending');
                    if (activeTasks.length > 0) {
                        const delay = Math.min(1000 * Math.pow(2, this.connectionAttempts), 30000);
                        refreshClerkToken().finally(() => {
                            setTimeout(() => this.connectSSE(), delay);
                        });
                        this.startPolling();
                    }
                };
            } catch (e) {
                console.warn('SSE not supported, falling back to polling');
                this.sseConnected = false;
                this.startPolling();
            }
        },

        startPolling() {
            // Don't start multiple polling intervals
            if (this.pollInterval) return;

            let pollCount = 0;
            const maxPolls = 30; // Stop after 30 seconds of polling with no active tasks

            let refreshAttempted = false;
            const pollTasks = async () => {
                try {
                    let response = await fetch('/api/tasks?active_only=true');
                    if (response.status === 401 && !refreshAttempted) {
                        refreshAttempted = true;
                        const refreshed = await refreshClerkToken();
                        if (refreshed) {
                            response = await fetch('/api/tasks?active_only=true');
                            if (response.ok) refreshAttempted = false;
                        }
                    }
                    if (response.ok) {
                        refreshAttempted = false;
                        const data = await response.json();
                        if (data.tasks && data.tasks.length > 0) {
                            pollCount = 0;
                            data.tasks.forEach(task => this.handleTaskUpdate(task));
                        } else {
                            pollCount++;
                        }
                    } else if (response.status === 401) {
                        this.stopPolling();
                        showToast('Session expired. Please sign in again.', 'warning');
                        return;
                    }
                } catch (e) {
                    console.warn('Task polling failed:', e);
                    pollCount++;
                }

                // Stop polling if no tasks for too long
                const activeTasks = this.tasks.filter(t => t.status === 'running' || t.status === 'pending');
                if (activeTasks.length === 0 && pollCount > 5) {
                    this.stopPolling();
                }
                if (pollCount > maxPolls) {
                    this.stopPolling();
                }
            };

            // Poll every 2 seconds (less aggressive than 1s)
            this.pollInterval = setInterval(pollTasks, 2000);
            // Also poll immediately
            pollTasks();
        },

        stopPolling() {
            if (this.pollInterval) {
                clearInterval(this.pollInterval);
                this.pollInterval = null;
            }
        },

        handleTaskUpdate(data) {
            const existingIndex = this.tasks.findIndex(t => t.id === data.id);

            // Check if this task already triggered a reload (prevents infinite reload loop)
            const reloadedTasks = JSON.parse(sessionStorage.getItem('reloadedTasks') || '[]');
            const alreadyReloaded = reloadedTasks.includes(data.id);

            if (existingIndex >= 0) {
                // Update existing task
                this.tasks[existingIndex] = { ...this.tasks[existingIndex], ...data };
            } else {
                // Add new task only if it's not already completed and reloaded
                if (data.status === 'completed' && alreadyReloaded) {
                    // Skip adding completed tasks that we already processed
                    return;
                }
                this.tasks.push(data);
            }

            // Save to sessionStorage
            sessionStorage.setItem('activeTasks', JSON.stringify(this.tasks));

            if (data.status === 'completed' && !alreadyReloaded) {
                const idx = existingIndex >= 0 ? existingIndex : this.tasks.length - 1;
                this.tasks[idx].showCompleted = true;

                reloadedTasks.push(data.id);
                sessionStorage.setItem('reloadedTasks', JSON.stringify(reloadedTasks));

                setTimeout(() => {
                    const current = JSON.parse(sessionStorage.getItem('reloadedTasks') || '[]');
                    sessionStorage.setItem('reloadedTasks', JSON.stringify(current.filter(id => id !== data.id)));
                }, 60000);

                setTimeout(() => {
                    this.dismissTask(data.id);
                    if (['gossip_scrape', 'content_reranking'].includes(data.type)) {
                        showRefreshToast(data.type === 'gossip_scrape'
                            ? 'New gossip is ready!'
                            : 'Rankings updated!');
                    }
                }, 2500);
            } else if (data.status === 'completed' && alreadyReloaded) {
                this.dismissTask(data.id);
            }

            // Handle failed tasks
            if (data.status === 'failed') {
                setTimeout(() => {
                    this.dismissTask(data.id);
                }, 8000);
            }

            // Re-initialize Lucide icons
            this.$nextTick(() => {
                if (typeof lucide !== 'undefined') {
                    lucide.createIcons();
                }
            });
        },

        addTask(task) {
            // Check if task already exists
            const existing = this.tasks.find(t => t.id === task.id);
            if (existing) return;

            // Manually add a task (for optimistic UI)
            this.tasks.push({
                id: task.id || Date.now().toString(),
                name: task.name,
                message: task.message || 'Starting...',
                status: 'pending',
                progress: 0,
                ...task
            });

            sessionStorage.setItem('activeTasks', JSON.stringify(this.tasks));

            this.$nextTick(() => {
                if (typeof lucide !== 'undefined') {
                    lucide.createIcons();
                }
            });
        },

        dismissTask(taskId) {
            this.tasks = this.tasks.filter(t => t.id !== taskId);
            sessionStorage.setItem('activeTasks', JSON.stringify(this.tasks));

            // Stop polling and disconnect SSE if no more active tasks
            const activeTasks = this.tasks.filter(t => t.status === 'running' || t.status === 'pending');
            if (activeTasks.length === 0) {
                this.stopPolling();
                if (this.eventSource) {
                    this.eventSource.close();
                    this.eventSource = null;
                    this.sseConnected = false;
                }
            }
        },

        clearAll() {
            this.tasks = [];
            sessionStorage.removeItem('activeTasks');
            this.stopPolling();
            if (this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
                this.sseConnected = false;
            }
        }
    };
}

// Make taskNotifications available globally
window.taskNotifications = taskNotifications;

/**
 * Start a background task
 */
async function startBackgroundTask(taskType, options = {}) {
    try {
        const response = await fetch(`/api/tasks/${taskType}/start`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(options)
        });

        if (response.ok) {
            const data = await response.json();
            if (data.success && data.task) {
                // Dispatch custom event for taskNotifications to pick up
                window.dispatchEvent(new CustomEvent('taskCreated', { detail: data.task }));
                showToast(`Task started: ${data.task.name}`, 'info');
            } else if (!data.success) {
                showToast(data.message || 'Task already running', 'warning');
            }
            return data;
        } else {
            const error = await response.json();
            showToast(error.detail || 'Failed to start task', 'error');
            return null;
        }
    } catch (error) {
        showToast('Failed to start task', 'error');
        return null;
    }
}

/**
 * Start a discovery task (movies or TV shows)
 * Called by the "Discover New" buttons
 */
async function startDiscoveryTask(taskType, buttonElement) {
    // Disable button and show loading state
    const originalHTML = buttonElement.innerHTML;
    buttonElement.disabled = true;
    buttonElement.innerHTML = `
        <svg class="w-4 h-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        <span>Starting...</span>
    `;

    try {
        const result = await startBackgroundTask(taskType);

        // Re-enable button after a short delay
        setTimeout(() => {
            buttonElement.disabled = false;
            buttonElement.innerHTML = originalHTML;
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        }, 1000);

    } catch (error) {
        // Re-enable button on error
        buttonElement.disabled = false;
        buttonElement.innerHTML = originalHTML;
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }
}

window.startBackgroundTask = startBackgroundTask;
window.startDiscoveryTask = startDiscoveryTask;
