import { showToast } from './toasts.js';

export function getCsrfToken() {
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
