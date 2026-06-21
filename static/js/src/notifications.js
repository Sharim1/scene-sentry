import { refreshClerkToken } from './clerk.js';

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
