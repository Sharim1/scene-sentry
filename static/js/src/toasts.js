/**
 * Toast Notifications
 */
export function initToasts() {
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
export function showToast(message, type = 'info') {
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
export function showRefreshToast(message) {
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

// Make showToast available globally
window.showToast = showToast;
