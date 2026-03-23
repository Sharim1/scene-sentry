/**
 * Scene Sentry - Client-side JavaScript
 * Handles interactivity, form submissions, and UI enhancements
 */

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
            
            // Auto-dismiss completed tasks after a delay and refresh page
            if (data.status === 'completed' && !alreadyReloaded) {
                const idx = existingIndex >= 0 ? existingIndex : this.tasks.length - 1;
                this.tasks[idx].showCompleted = true;
                
                // Mark this task as having triggered a reload
                reloadedTasks.push(data.id);
                sessionStorage.setItem('reloadedTasks', JSON.stringify(reloadedTasks));
                
                // Clean up old reloaded task IDs after 60 seconds (to prevent memory growth)
                setTimeout(() => {
                    const current = JSON.parse(sessionStorage.getItem('reloadedTasks') || '[]');
                    const updated = current.filter(id => id !== data.id);
                    sessionStorage.setItem('reloadedTasks', JSON.stringify(updated));
                }, 60000);
                
                setTimeout(async () => {
                    this.dismissTask(data.id);
                    // Reload page to show new content after discovery/scrape completes
                    if (['movie_discovery', 'tv_discovery', 'gossip_scrape', 'content_reranking'].includes(data.type)) {
                        // First check if we're still authenticated before reloading
                        // This prevents redirect to login if token expired
                        try {
                            const authCheck = await fetch('/api/tasks?active_only=true');
                            if (authCheck.ok) {
                                // User is authenticated, safe to reload
                                window.location.reload();
                            } else if (authCheck.status === 401) {
                                // Token expired - show a toast instead of reloading
                                // The new content is already saved, user can navigate manually
                                if (typeof window.showToast === 'function') {
                                    window.showToast('Discovery complete! Refresh the page to see new content.', 'success');
                                }
                            }
                        } catch (e) {
                            // Network error - just show toast
                            if (typeof window.showToast === 'function') {
                                window.showToast('Discovery complete! Refresh the page to see new content.', 'success');
                            }
                        }
                    }
                }, 2500);
            } else if (data.status === 'completed' && alreadyReloaded) {
                // Already reloaded for this task, just dismiss it
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
    
    toast.innerHTML = `
        <div class="flex items-center gap-3">
            <i data-lucide="${iconMap[type]}" class="w-5 h-5"></i>
            <span class="text-sm">${message}</span>
            <button onclick="this.parentElement.parentElement.remove()" class="ml-4 p-1 hover:bg-white/10 rounded transition-colors">
                <i data-lucide="x" class="w-4 h-4"></i>
            </button>
        </div>
    `;
    
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
 * Search with Live Results (for future AJAX search)
 */
const handleSearch = debounce(async (query) => {
    if (query.length < 2) return;
    
    try {
        const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
        const data = await response.json();
        // Handle results...
    } catch (error) {
        console.error('Search error:', error);
    }
}, 300);

/**
 * Status Update API call
 */
async function updateStatus(itemId, newStatus) {
    try {
        const response = await fetch(`/api/library/${itemId}/status`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ status: newStatus })
        });
        
        if (response.ok) {
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
 * Add content to library using AJAX
 * Handles auth errors gracefully by showing a toast instead of redirecting
 */
async function addToLibrary(contentId, status, buttonElement = null) {
    // Show loading state if button provided
    let originalHTML = '';
    if (buttonElement) {
        originalHTML = buttonElement.innerHTML;
        buttonElement.disabled = true;
        buttonElement.innerHTML = '<svg class="w-4 h-4 animate-spin" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg>';
    }
    
    try {
        const formData = new FormData();
        formData.append('content_id', contentId);
        formData.append('status', status);
        
        const response = await fetch('/add-to-library', {
            method: 'POST',
            body: formData,
            redirect: 'manual' // Prevent automatic redirect following
        });
        
        if (response.ok || response.type === 'opaqueredirect' || response.status === 303) {
            // Success - check if we were redirected to login (auth issue)
            const redirectUrl = response.headers.get('Location') || '';
            if (redirectUrl.includes('/login')) {
                showToast('Session expired. Please refresh the page to continue.', 'warning');
            } else {
                showToast('Added to library!', 'success');
                // Reload page after short delay to show updated state
                setTimeout(() => window.location.reload(), 1000);
            }
        } else if (response.status === 401) {
            showToast('Session expired. Please refresh the page to continue.', 'warning');
        } else {
            showToast('Failed to add to library. Please try again.', 'error');
        }
    } catch (error) {
        console.error('Add to library error:', error);
        showToast('Failed to add to library. Please try again.', 'error');
    } finally {
        // Restore button state
        if (buttonElement && originalHTML) {
            buttonElement.disabled = false;
            buttonElement.innerHTML = originalHTML;
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        }
    }
}

/**
 * Cleanup article-style entries using AJAX
 * Handles auth errors gracefully
 */
async function cleanupArticles(buttonElement = null) {
    // Show loading state
    let originalHTML = '';
    if (buttonElement) {
        originalHTML = buttonElement.innerHTML;
        buttonElement.disabled = true;
        buttonElement.innerHTML = '<svg class="w-3 h-3 animate-spin" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" fill="none"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path></svg>';
    }
    
    try {
        const response = await fetch('/cleanup-articles', {
            method: 'POST',
            redirect: 'manual'
        });
        
        if (response.ok || response.type === 'opaqueredirect' || response.status === 303) {
            const redirectUrl = response.headers.get('Location') || '';
            if (redirectUrl.includes('/login')) {
                showToast('Session expired. Please refresh the page.', 'warning');
            } else {
                showToast('Cleanup complete!', 'success');
                setTimeout(() => window.location.reload(), 1000);
            }
        } else if (response.status === 401) {
            showToast('Session expired. Please refresh the page.', 'warning');
        } else {
            showToast('Cleanup failed. Please try again.', 'error');
        }
    } catch (error) {
        console.error('Cleanup error:', error);
        showToast('Cleanup failed. Please try again.', 'error');
    } finally {
        if (buttonElement && originalHTML) {
            buttonElement.disabled = false;
            buttonElement.innerHTML = originalHTML;
            if (typeof lucide !== 'undefined') {
                lucide.createIcons();
            }
        }
    }
}

// Make functions available globally
window.startBackgroundTask = startBackgroundTask;
window.startDiscoveryTask = startDiscoveryTask;
window.updateStatus = updateStatus;
window.updateProgress = updateProgress;
window.addToLibrary = addToLibrary;
window.cleanupArticles = cleanupArticles;
window.copyToClipboard = copyToClipboard;
window.confirmAction = confirmAction;
