/**
 * Attempt to refresh the Clerk session token.
 * Returns true if a fresh token was obtained, false otherwise.
 */
export async function refreshClerkToken() {
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
