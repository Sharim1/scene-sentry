/**
 * MovieMind - Client-side JavaScript
 * Handles interactivity, form submissions, and UI enhancements
 */

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
        
        init() {
            // Load any existing tasks from sessionStorage
            const stored = sessionStorage.getItem('activeTasks');
            if (stored) {
                try {
                    const parsed = JSON.parse(stored);
                    // Only keep non-completed tasks
                    this.tasks = parsed.filter(t => t.status !== 'completed' && t.status !== 'failed');
                } catch (e) {
                    this.tasks = [];
                }
            }
            
            // Connect to SSE immediately if there are active tasks
            if (this.tasks.length > 0) {
                this.connectSSE();
            }
            
            // Listen for custom events to add tasks
            window.addEventListener('taskCreated', (e) => {
                this.addTask(e.detail);
                // Connect to SSE immediately when a task is created
                if (!this.sseConnected) {
                    this.connectSSE();
                }
            });
            
            // Re-initialize Lucide icons after Alpine renders
            this.$nextTick(() => {
                if (typeof lucide !== 'undefined') {
                    lucide.createIcons();
                }
            });
        },
        
        connectSSE() {
            // Don't reconnect if already connected or too many attempts
            if (this.sseConnected || typeof EventSource === 'undefined') return;
            if (this.connectionAttempts >= this.maxAttempts) {
                console.warn('Max SSE connection attempts reached');
                return;
            }
            
            this.connectionAttempts++;
            
            try {
                this.eventSource = new EventSource('/api/tasks/stream');
                this.sseConnected = true;
                
                this.eventSource.onopen = () => {
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
                    this.sseConnected = false;
                    if (this.eventSource) {
                        this.eventSource.close();
                        this.eventSource = null;
                    }
                    // Retry with exponential backoff if there are still active tasks
                    const activeTasks = this.tasks.filter(t => t.status === 'running' || t.status === 'pending');
                    if (activeTasks.length > 0) {
                        const delay = Math.min(1000 * Math.pow(2, this.connectionAttempts), 30000);
                        setTimeout(() => this.connectSSE(), delay);
                    }
                };
            } catch (e) {
                this.sseConnected = false;
            }
        },
        
        handleTaskUpdate(data) {
            const existingIndex = this.tasks.findIndex(t => t.id === data.id);
            
            if (existingIndex >= 0) {
                // Update existing task
                this.tasks[existingIndex] = { ...this.tasks[existingIndex], ...data };
            } else {
                // Add new task
                this.tasks.push(data);
            }
            
            // Save to sessionStorage
            sessionStorage.setItem('activeTasks', JSON.stringify(this.tasks));
            
            // Auto-dismiss completed tasks after 5 seconds
            if (data.status === 'completed') {
                const idx = existingIndex >= 0 ? existingIndex : this.tasks.length - 1;
                this.tasks[idx].showCompleted = true;
                setTimeout(() => {
                    this.dismissTask(data.id);
                    // Reload page to show new content after discovery completes
                    if (data.type === 'movie_discovery' || data.type === 'tv_discovery') {
                        window.location.reload();
                    }
                }, 3000);
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
            
            // Disconnect SSE if no more active tasks
            if (this.tasks.length === 0 && this.eventSource) {
                this.eventSource.close();
                this.eventSource = null;
                this.sseConnected = false;
            }
        },
        
        clearAll() {
            this.tasks = [];
            sessionStorage.removeItem('activeTasks');
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

// Make functions available globally
window.startBackgroundTask = startBackgroundTask;
window.startDiscoveryTask = startDiscoveryTask;
window.updateStatus = updateStatus;
window.updateProgress = updateProgress;
window.copyToClipboard = copyToClipboard;
window.confirmAction = confirmAction;
