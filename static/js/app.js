/**
 * Scene Sentry - Client-side JavaScript
 * Handles interactivity, form submissions, and UI enhancements
 */

function getCsrfToken() {
    const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : '';
}

(function() {
    const originalFetch = window.fetch;
    window.fetch = function(input, init) {
        init = init || {};
        const method = (init.method || 'GET').toUpperCase();
        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
            init.headers = init.headers || {};
            if (init.headers instanceof Headers) {
                if (!init.headers.has('x-csrftoken')) {
                    init.headers.set('x-csrftoken', getCsrfToken());
                }
            } else {
                init.headers['x-csrftoken'] = init.headers['x-csrftoken'] || getCsrfToken();
            }
        }
        return originalFetch.call(this, input, init);
    };

    document.addEventListener('submit', function(e) {
        const form = e.target;
        if (form.tagName !== 'FORM' || form.method.toUpperCase() !== 'POST') return;
        // Skip forms handled by dedicated JS (marked with data-ajax-skip)
        if (form.dataset.ajaxSkip) return;
        e.preventDefault();
        const formData = new FormData(form);
        const action = form.action || window.location.href;
        fetch(action, {
            method: 'POST',
            headers: { 'x-csrftoken': getCsrfToken() },
            body: formData,
            redirect: 'follow',
        }).then(function(resp) {
            if (resp.redirected) {
                window.location.href = resp.url;
            } else if (resp.ok) {
                showToast('Done!', 'success');
            } else {
                resp.text().then(function(html) {
                    document.open();
                    document.write(html);
                    document.close();
                });
            }
        }).catch(function() {
            form.submit();
        });
    });
})();

/**
 * Attempt to refresh the Clerk session token.
 * Returns true if a fresh token was obtained, false otherwise.
 */
async function refreshClerkToken() {
    try {
        if (window.__clerkReady) {
            const clerk = await window.__clerkReady;
            if (clerk && clerk.session) {
                await clerk.session.getToken({ skipCache: true });
                return true;
            }
        }
    } catch (e) {
        console.warn('Clerk token refresh failed:', e);
    }
    return false;
}
window.refreshClerkToken = refreshClerkToken;

document.addEventListener('DOMContentLoaded', function() {
    // Initialize Lucide icons - with guard to prevent double initialization
    if (typeof lucide !== 'undefined' && !window.lucideInitialized) {
        window.lucideInitialized = true;
        lucide.createIcons();
    }

    // Initialize all interactive components
    initToasts();
    initTabs();
    initForms();
    initGenreSelector();
    initCardInteractions();
    initGlobalCatalogSearch();
});

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
 * Notification Bell Alpine.js Component
 * Handles SSE streaming, unread badge, dropdown, and toast popups
 */
function notificationBell() {
    return {
        open: false,
        notifications: [],
        unreadCount: 0,
        eventSource: null,
        loaded: false,
        _sseAttempts: 0,
        _maxSseAttempts: 5,
        _reconnectTimer: null,

        init() {
            this.fetchNotifications();
            this.connectSSE();

            document.addEventListener('visibilitychange', () => {
                if (document.hidden) {
                    this._disconnectSSE();
                } else {
                    this._sseAttempts = 0;
                    this.connectSSE();
                    this.fetchNotifications();
                }
            });
        },

        async fetchNotifications() {
            try {
                let res = await fetch('/api/notifications');
                if (res.status === 401) {
                    const refreshed = await refreshClerkToken();
                    if (refreshed) res = await fetch('/api/notifications');
                    else return;
                }
                if (res.ok) {
                    const data = await res.json();
                    this.notifications = data.notifications || [];
                    this.unreadCount = data.unread_count || 0;
                    this.loaded = true;
                }
            } catch (e) { /* ignore */ }
        },

        connectSSE() {
            if (typeof EventSource === 'undefined') return;
            if (this.eventSource) return;
            if (document.hidden) return;
            if (this._sseAttempts >= this._maxSseAttempts) return;

            this._sseAttempts++;

            try {
                this.eventSource = new EventSource('/api/notifications/stream');
                this.eventSource.onopen = () => {
                    this._sseAttempts = 0;
                };
                this.eventSource.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === 'new_notifications') {
                            this.unreadCount = data.unread_count;
                            if (data.items && data.items.length > 0) {
                                for (const item of data.items) {
                                    if (!this.notifications.find(n => n.id === item.id)) {
                                        this.notifications.unshift(item);
                                        this._showToast(item);
                                    }
                                }
                                this.notifications = this.notifications.slice(0, 30);
                            }
                            this.$nextTick(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); });
                        }
                    } catch (e) { /* ignore parse errors */ }
                };
                this.eventSource.onerror = () => {
                    this._disconnectSSE();
                    if (this._sseAttempts >= this._maxSseAttempts) return;
                    const backoff = Math.min(30000, 5000 * Math.pow(2, this._sseAttempts));
                    this._reconnectTimer = setTimeout(() => this.connectSSE(), backoff);
                };
            } catch (e) { /* SSE not supported */ }
        },

        _disconnectSSE() {
            if (this._reconnectTimer) { clearTimeout(this._reconnectTimer); this._reconnectTimer = null; }
            if (this.eventSource) { this.eventSource.close(); this.eventSource = null; }
        },

        _showToast(item) {
            if (typeof window.showToast === 'function') {
                window.showToast(item.body || item.title, 'info');
            }
        },

        toggle() {
            this.open = !this.open;
            if (this.open && !this.loaded) this.fetchNotifications();
            this.$nextTick(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); });
        },

        async markRead(id) {
            try {
                const res = await fetch(`/api/notifications/${id}/read`, { method: 'POST' });
                if (res.ok) {
                    const n = this.notifications.find(x => x.id === id);
                    if (n) n.is_read = true;
                    this.unreadCount = Math.max(0, this.unreadCount - 1);
                }
            } catch (e) { /* ignore */ }
        },

        async markAllRead() {
            try {
                const res = await fetch('/api/notifications/read-all', { method: 'POST' });
                if (res.ok) {
                    this.notifications.forEach(n => n.is_read = true);
                    this.unreadCount = 0;
                }
            } catch (e) { /* ignore */ }
        },

        clickNotification(n) {
            if (!n.is_read) this.markRead(n.id);
            this.open = false;
            if (n.link) window.location.href = n.link;
        },

        timeAgo(iso) {
            if (!iso) return '';
            const diff = Date.now() - new Date(iso).getTime();
            const mins = Math.floor(diff / 60000);
            if (mins < 1) return 'Just now';
            if (mins < 60) return mins + 'm ago';
            const hrs = Math.floor(mins / 60);
            if (hrs < 24) return hrs + 'h ago';
            return Math.floor(hrs / 24) + 'd ago';
        },

        destroy() {
            this._disconnectSSE();
        }
    };
}
window.notificationBell = notificationBell;

/**
 * Toast Notifications
 */
function initToasts() {
    // Auto-hide toasts after 5 seconds
    const toasts = document.querySelectorAll('.toast');
    toasts.forEach(toast => {
        setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => toast.remove(), 300);
        }, 5000);
    });
}

/**
 * Show toast notification
 */
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type} fixed bottom-4 right-4 p-4 rounded-lg bg-card border border-white/10 shadow-xl z-50 animate-in`;
    
    const iconMap = {
        success: 'check-circle',
        error: 'alert-circle',
        warning: 'alert-triangle',
        info: 'info'
    };
    
    const container = document.createElement('div');
    container.className = 'flex items-center gap-3';

    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', iconMap[type] || 'info');
    icon.className = 'w-5 h-5';
    container.appendChild(icon);

    const span = document.createElement('span');
    span.className = 'text-sm';
    span.textContent = message;
    container.appendChild(span);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'ml-4 p-1 hover:bg-white/10 rounded transition-colors';
    closeBtn.addEventListener('click', () => toast.remove());
    const closeIcon = document.createElement('i');
    closeIcon.setAttribute('data-lucide', 'x');
    closeIcon.className = 'w-4 h-4';
    closeBtn.appendChild(closeIcon);
    container.appendChild(closeBtn);

    toast.appendChild(container);
    
    document.body.appendChild(toast);
    
    if (typeof lucide !== 'undefined') {
        lucide.createIcons();
    }
    
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

/**
 * Persistent toast with a "Refresh" action button.
 * Stays on screen until dismissed or clicked — no auto-reload.
 */
function showRefreshToast(message) {
    const toast = document.createElement('div');
    toast.className = 'fixed bottom-4 right-4 p-4 rounded-lg bg-card border border-primary/30 shadow-xl z-50 animate-in max-w-sm';

    const container = document.createElement('div');
    container.className = 'flex items-center gap-3';

    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', 'refresh-cw');
    icon.className = 'w-5 h-5 text-primary flex-shrink-0';
    container.appendChild(icon);

    const text = document.createElement('span');
    text.className = 'text-sm flex-1';
    text.textContent = message;
    container.appendChild(text);

    const btn = document.createElement('button');
    btn.className = 'ml-2 px-3 py-1 text-xs font-medium rounded-md bg-primary text-white hover:bg-primary/80 transition-colors flex-shrink-0';
    btn.textContent = 'Refresh';
    btn.addEventListener('click', () => window.location.reload());
    container.appendChild(btn);

    const closeBtn = document.createElement('button');
    closeBtn.className = 'ml-1 p-1 hover:bg-white/10 rounded transition-colors flex-shrink-0';
    closeBtn.addEventListener('click', () => toast.remove());
    const closeIcon = document.createElement('i');
    closeIcon.setAttribute('data-lucide', 'x');
    closeIcon.className = 'w-4 h-4';
    closeBtn.appendChild(closeIcon);
    container.appendChild(closeBtn);

    toast.appendChild(container);
    document.body.appendChild(toast);

    if (typeof lucide !== 'undefined') lucide.createIcons();

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'opacity 0.3s, transform 0.3s';
        setTimeout(() => toast.remove(), 300);
    }, 15000);
}

/**
 * Alpine component for live library tab counts.
 * Listens for library:status-changed, library:item-added, and library:item-removed
 * and adjusts the displayed counts without a page reload.
 */
function libraryCounts(initial) {
    return {
        c: Object.assign({ all: 0, watching: 0, planned: 0, completed: 0, dropped: 0, maybe: 0 }, initial),
        _loading: false,

        onStatusChanged(detail) {
            const oldS = detail.oldStatus;
            const newS = detail.status;
            if (!newS || oldS === newS) return;
            if (oldS && this.c[oldS] !== undefined) {
                this.c[oldS] = Math.max(0, this.c[oldS] - 1);
            }
            if (this.c[newS] !== undefined) {
                this.c[newS]++;
            }
        },

        onItemAdded(detail) {
            const s = detail.status;
            if (s && this.c[s] !== undefined) this.c[s]++;
            this.c.all++;
        },

        onItemRemoved(detail) {
            const s = detail.status;
            if (s && this.c[s] !== undefined) {
                this.c[s] = Math.max(0, this.c[s] - 1);
            }
            this.c.all = Math.max(0, this.c.all - 1);
        },

        async switchLibraryTab(url, clickedTab) {
            if (this._loading) return;

            const tabs = document.querySelectorAll('#library-tabs .tab');
            tabs.forEach(t => t.classList.remove('active'));
            clickedTab.classList.add('active');

            const container = document.getElementById('library-content');
            if (!container) return;

            this._loading = true;
            container.style.opacity = '0.4';
            container.style.transition = 'opacity 0.15s';

            try {
                const resp = await fetch(url);
                if (!resp.ok) { window.location.href = url; return; }

                const html = await resp.text();
                const doc = new DOMParser().parseFromString(html, 'text/html');
                const newContent = doc.getElementById('library-content');

                if (newContent) {
                    container.innerHTML = newContent.innerHTML;
                    container.style.opacity = '1';
                    if (typeof lucide !== 'undefined') lucide.createIcons();
                } else {
                    window.location.href = url;
                    return;
                }

                history.pushState({ libraryTab: true }, '', url);
            } catch (e) {
                window.location.href = url;
                return;
            } finally {
                this._loading = false;
            }
        }
    };
}
window.libraryCounts = libraryCounts;

// Handle browser back/forward on the library page
window.addEventListener('popstate', function() {
    if (window.location.pathname === '/library') {
        const container = document.getElementById('library-content');
        if (container) {
            container.style.opacity = '0.4';
            container.style.transition = 'opacity 0.15s';
            fetch(window.location.href)
                .then(r => r.text())
                .then(html => {
                    const doc = new DOMParser().parseFromString(html, 'text/html');
                    const newContent = doc.getElementById('library-content');
                    const newTabs = doc.getElementById('library-tabs');
                    if (newContent) {
                        container.innerHTML = newContent.innerHTML;
                        container.style.opacity = '1';
                        if (typeof lucide !== 'undefined') lucide.createIcons();
                    }
                    if (newTabs) {
                        const tabs = document.querySelectorAll('#library-tabs .tab');
                        const freshTabs = newTabs.querySelectorAll('.tab');
                        tabs.forEach((t, i) => {
                            t.classList.toggle('active', freshTabs[i] && freshTabs[i].classList.contains('active'));
                        });
                    }
                })
                .catch(() => window.location.reload());
        }
    }
});

// Make showToast available globally
window.showToast = showToast;

/**
 * Tab Navigation
 */
function initTabs() {
    const tabContainers = document.querySelectorAll('[data-tabs]');
    
    tabContainers.forEach(container => {
        const tabs = container.querySelectorAll('[data-tab]');
        const panels = container.querySelectorAll('[data-panel]');
        
        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const targetPanel = tab.dataset.tab;
                
                // Update tab states
                tabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                
                // Update panel visibility
                panels.forEach(p => {
                    p.classList.toggle('hidden', p.dataset.panel !== targetPanel);
                });
            });
        });
    });
}

/**
 * Form Handling with Loading States
 */
function initForms() {
    const forms = document.querySelectorAll('form[data-loading]');
    
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const button = form.querySelector('button[type="submit"]');
            if (button) {
                button.disabled = true;
                button.innerHTML = `
                    <i data-lucide="loader-2" class="w-4 h-4 animate-spin"></i>
                    <span>Loading...</span>
                `;
                if (typeof lucide !== 'undefined') {
                    lucide.createIcons();
                }
            }
        });
    });
    
    // Discovery form specific handling - now with background task support
    const discoveryForms = document.querySelectorAll('form[action*="/discover"], form[action*="/refresh"]');
    discoveryForms.forEach(form => {
        form.addEventListener('submit', function(e) {
            const button = form.querySelector('button[type="submit"]');
            if (button) {
                button.disabled = true;
                const originalHTML = button.innerHTML;
                button.innerHTML = `
                    <svg class="w-4 h-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    <span>Starting...</span>
                `;
                
                // Re-enable button after 2 seconds for background tasks
                setTimeout(() => {
                    button.disabled = false;
                    button.innerHTML = originalHTML;
                    if (typeof lucide !== 'undefined') {
                        lucide.createIcons();
                    }
                }, 2000);
            }
        });
    });
}

/**
 * Genre Selector with Visual Feedback
 */
function initGenreSelector() {
    const genreLabels = document.querySelectorAll('label:has(input[name="genres"])');
    
    genreLabels.forEach(label => {
        const checkbox = label.querySelector('input[type="checkbox"]');
        if (!checkbox) return;
        
        checkbox.addEventListener('change', () => {
            label.classList.toggle('ring-2', checkbox.checked);
            label.classList.toggle('ring-primary', checkbox.checked);
            label.classList.toggle('bg-primary/10', checkbox.checked);
            
            // Update check icon
            const iconContainer = label.querySelector('.w-4.h-4.rounded');
            if (iconContainer) {
                iconContainer.classList.toggle('bg-primary', checkbox.checked);
                iconContainer.classList.toggle('border-primary', checkbox.checked);
                iconContainer.innerHTML = checkbox.checked 
                    ? '<i data-lucide="check" class="w-3 h-3 text-white"></i>' 
                    : '';
                if (typeof lucide !== 'undefined') {
                    lucide.createIcons();
                }
            }
        });
    });
}

/**
 * Card Hover Interactions
 */
function initCardInteractions() {
    // Movie cards - hover effects are handled by CSS
    const movieCards = document.querySelectorAll('.group:has(.aspect-\\[2\\/3\\])');
    
    movieCards.forEach(card => {
        card.addEventListener('mouseenter', () => {
            card.style.zIndex = '10';
        });
        
        card.addEventListener('mouseleave', () => {
            card.style.zIndex = '';
        });
    });
}

/**
 * Confirm Dialog
 */
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

/**
 * Copy to Clipboard
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Copied to clipboard!', 'success');
    } catch (err) {
        showToast('Failed to copy', 'error');
    }
}

/**
 * Format Time Ago
 */
function timeAgo(date) {
    const now = new Date();
    const diff = now - new Date(date);
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    
    if (days > 0) return `${days}d ago`;
    if (hours > 0) return `${hours}h ago`;
    if (minutes > 0) return `${minutes}m ago`;
    return 'Just now';
}

/**
 * Debounce utility
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Global catalog search (modal in base.html) — GET /api/search
 */
function initGlobalCatalogSearch() {
    const input = document.getElementById('global-search-q');
    const resultsEl = document.getElementById('global-search-results');
    const hintEl = document.getElementById('global-search-hint');
    if (!input || !resultsEl) return;

    if (input.dataset.bound === '1') return;
    input.dataset.bound = '1';

    const runQuery = debounce(async (raw) => {
        const query = (raw || '').trim();
        if (hintEl) hintEl.remove();

        if (query.length < 1) {
            resultsEl.innerHTML = '<p class="px-3 py-6 text-center text-muted-foreground" id="global-search-hint">Type at least one character to search.</p>';
            return;
        }

        resultsEl.innerHTML = '<p class="px-3 py-4 text-center text-sm text-muted-foreground">Searching…</p>';

        try {
            let response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
            if (response.status === 401) {
                const refreshed = await refreshClerkToken();
                if (refreshed) {
                    response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
                }
            }
            if (!response.ok) {
                resultsEl.innerHTML = '<p class="px-3 py-4 text-center text-sm text-destructive">Search failed. Try again.</p>';
                return;
            }
            const data = await response.json();
            const items = data.results || [];
            if (items.length === 0) {
                resultsEl.innerHTML = '<p class="px-3 py-6 text-center text-muted-foreground">No titles matched your search.</p>';
                return;
            }
            const frag = document.createDocumentFragment();
            items.forEach((item) => {
                const a = document.createElement('a');
                a.href = `/${item.id}`;
                a.className = 'flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-white/5 transition-colors';

                const thumb = document.createElement('div');
                thumb.className = 'w-10 h-14 flex-shrink-0 rounded-md overflow-hidden bg-white/5 border border-white/10';
                if (item.poster_url) {
                    const img = document.createElement('img');
                    img.src = item.poster_url;
                    img.alt = '';
                    img.className = 'w-full h-full object-cover';
                    img.loading = 'lazy';
                    thumb.appendChild(img);
                } else {
                    thumb.innerHTML = '<div class="w-full h-full flex items-center justify-center text-xs text-muted-foreground">—</div>';
                }

                const text = document.createElement('div');
                text.className = 'min-w-0 flex-1';
                const typeLabel = (item.content_type || '').replace(/_/g, ' ');
                const titleEl = document.createElement('div');
                titleEl.className = 'text-sm font-medium text-foreground truncate';
                titleEl.textContent = item.title || '';
                const sub = document.createElement('div');
                sub.className = 'text-xs text-muted-foreground';
                sub.textContent = item.year ? `${typeLabel} · ${item.year}` : typeLabel;
                text.appendChild(titleEl);
                text.appendChild(sub);

                a.appendChild(thumb);
                a.appendChild(text);
                frag.appendChild(a);
            });
            resultsEl.innerHTML = '';
            resultsEl.appendChild(frag);
            if (typeof lucide !== 'undefined') lucide.createIcons();
        } catch (e) {
            console.error('Search error:', e);
            resultsEl.innerHTML = '<p class="px-3 py-4 text-center text-sm text-destructive">Search error. Check your connection.</p>';
        }
    }, 300);

    input.addEventListener('input', (e) => runQuery(e.target.value));
}
window.initGlobalCatalogSearch = initGlobalCatalogSearch;

/**
 * Status Update API call — updates DOM in-place via Alpine events.
 * Accepts an optional oldStatus so tab counts can be adjusted without reload.
 */
async function updateStatus(itemId, newStatus, oldStatus) {
    try {
        const response = await fetch(`/api/library/${itemId}/status`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });

        if (response.ok) {
            const data = await response.json();
            const finalStatus = data.status || newStatus;
            window.dispatchEvent(new CustomEvent('library:status-changed', {
                detail: { itemId: itemId, status: finalStatus, oldStatus: oldStatus || null }
            }));
            showToast('Status updated!', 'success');
            return true;
        } else {
            throw new Error('Failed to update');
        }
    } catch (error) {
        showToast('Failed to update status', 'error');
        return false;
    }
}

/**
 * Progress Update API call  
 */
async function updateProgress(itemId, progress, season = null, episode = null) {
    try {
        const response = await fetch(`/api/library/${itemId}/progress`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ progress, season, episode })
        });
        
        if (response.ok) {
            showToast('Progress updated!', 'success');
            return true;
        } else {
            throw new Error('Failed to update');
        }
    } catch (error) {
        showToast('Failed to update progress', 'error');
        return false;
    }
}

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

/**
 * Add content to library (or update status if already tracked) via JSON API.
 * Updates DOM in-place via Alpine events — no page reload.
 */
async function addToLibrary(contentId, status) {
    try {
        const response = await fetch('/api/library', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content_id: contentId, status: status })
        });

        if (response.ok) {
            const data = await response.json();
            window.dispatchEvent(new CustomEvent('library:item-added', {
                detail: {
                    contentId: contentId,
                    itemId: data.item_id,
                    status: data.status || status
                }
            }));
            showToast('Added to library!', 'success');
            return true;
        } else if (response.status === 401) {
            showToast('Session expired. Please refresh the page to continue.', 'warning');
        } else {
            showToast('Failed to add to library. Please try again.', 'error');
        }
    } catch (error) {
        console.error('Add to library error:', error);
        showToast('Failed to add to library. Please try again.', 'error');
    }
    return false;
}

/**
 * Remove item from library via JSON API.
 * On library page: fades card out. On other pages: clears status badge.
 * @param {number} itemId - Library item ID
 * @param {string} title - Content title (for confirmation dialog)
 * @param {string} [currentStatus] - Current watch status (for updating tab counts)
 */
async function removeFromLibrary(itemId, title = 'this item', currentStatus) {
    if (!confirm(`Remove "${title}" from your library? This will affect your personalized rankings.`)) {
        return;
    }

    try {
        const response = await fetch(`/api/library/${itemId}`, {
            method: 'DELETE',
        });

        if (response.ok) {
            window.dispatchEvent(new CustomEvent('library:item-removed', {
                detail: { itemId: itemId, status: currentStatus || null }
            }));

            // On the library page, fade out the removed card
            if (window.location.pathname === '/library') {
                const card = document.querySelector(`[data-item-id="${itemId}"]`);
                if (card) {
                    card.style.transition = 'opacity 0.3s, transform 0.3s';
                    card.style.opacity = '0';
                    card.style.transform = 'scale(0.95)';
                    setTimeout(() => card.remove(), 300);
                }
            }

            showToast('Removed from library', 'success');
            return true;
        } else if (response.status === 401) {
            showToast('Session expired. Please refresh the page to continue.', 'warning');
        } else {
            showToast('Failed to remove from library. Please try again.', 'error');
        }
    } catch (error) {
        console.error('Remove from library error:', error);
        showToast('Failed to remove from library. Please try again.', 'error');
    }
    return false;
}

// Make functions available globally
window.startBackgroundTask = startBackgroundTask;
window.startDiscoveryTask = startDiscoveryTask;
window.updateStatus = updateStatus;
window.updateProgress = updateProgress;
window.addToLibrary = addToLibrary;
window.removeFromLibrary = removeFromLibrary;
window.copyToClipboard = copyToClipboard;
window.confirmAction = confirmAction;
