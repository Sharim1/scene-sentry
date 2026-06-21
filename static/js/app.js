/**
 * Scene Sentry - Client-side JavaScript (entry point)
 *
 * Source modules live in static/js/src/*. This entry wires them together and is
 * bundled into static/dist/app.js by esbuild (see package.json). Modules that
 * register Alpine components / global helpers do so via `window.*` on import.
 */

import './src/csrf.js';
import './src/clerk.js';
import './src/tasks.js';
import './src/notifications.js';
import './src/library.js';
import './src/util.js';
import './src/search.js';

import { initToasts } from './src/toasts.js';
import { initTabs } from './src/tabs.js';
import { initForms } from './src/forms.js';
import { initGenreSelector } from './src/genre.js';
import { initCardInteractions } from './src/cards.js';
import { initGlobalCatalogSearch } from './src/search.js';

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
