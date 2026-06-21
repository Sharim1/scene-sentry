import { showToast } from './toasts.js';

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

window.updateStatus = updateStatus;
window.updateProgress = updateProgress;
window.addToLibrary = addToLibrary;
window.removeFromLibrary = removeFromLibrary;
