"""Test that /logout actually clears Clerk's session cookies.

__session, __client_uat, and __clerk_db_jwt are set with an explicit
Domain=<host> attribute (by our own Clerk handshake handler, and by Clerk's
own JS SDK) so they're shared with the Clerk FAPI subdomain. A delete_cookie()
call with no domain only clears a *host-only* cookie — a different cookie-jar
entry from a domain-scoped one of the same name, even when the domain string
matches the serving host. Missing the domain-scoped variant meant /logout
cleared the server-side session but left the real __session/__client_uat
cookies in place, so the next request to "/" was still authenticated and
bounced straight back to /dashboard instead of showing the user logged out.
"""

from fastapi.testclient import TestClient


def test_logout_clears_both_host_only_and_domain_scoped_cookies():
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.post("/logout", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/"

    set_cookie_headers = resp.headers.get_list("set-cookie")

    for name in ("__session", "__clerk_db_jwt", "scenesentry_session", "__client_uat"):
        matching = [h for h in set_cookie_headers if h.startswith(f"{name}=")]
        # One clear for the host-only variant, one for the domain-scoped
        # variant (Domain=testserver, since TestClient's default host is
        # "testserver") — both are needed to actually log the user out.
        assert len(matching) == 2, f"expected 2 Set-Cookie clears for {name}, got {len(matching)}: {matching}"
        assert any("domain=" in h.lower() for h in matching), f"{name} missing a domain-scoped clear: {matching}"
        assert any("domain=" not in h.lower() for h in matching), f"{name} missing a host-only clear: {matching}"
