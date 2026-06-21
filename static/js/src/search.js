import { refreshClerkToken } from './clerk.js';
import { debounce } from './util.js';

/**
 * Global catalog search (modal in base.html) — GET /api/search
 */
export function initGlobalCatalogSearch() {
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
