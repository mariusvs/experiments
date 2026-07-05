"""Tests for SSO auth: token signing, authorization rules, and route gating."""

import http.client
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from activity_tracker import auth, dashboard
from activity_tracker.config import Config

SECRET = "test-secret-key"


# ------------------------------------------------------------- signed tokens
def test_sign_unsign_roundtrip_and_tamper():
    tok = auth.sign({"sub": "a@x.com", "exp": time.time() + 100}, SECRET)
    assert auth.unsign(tok, SECRET)["sub"] == "a@x.com"
    # wrong secret fails
    assert auth.unsign(tok, "other") is None
    # tampered body fails
    body, sig = tok.split(".", 1)
    assert auth.unsign("AAAA." + sig, SECRET) is None


def test_session_expiry():
    now = 1000.0
    s = auth.make_session("a@x.com", SECRET, ttl=10, now=now)
    assert auth.session_email(s, SECRET, now=now + 5) == "a@x.com"
    assert auth.session_email(s, SECRET, now=now + 20) is None  # expired
    # a state token is not accepted as a session
    st = auth.make_state(SECRET, now=now)
    assert auth.session_email(st, SECRET, now=now + 1) is None


# ------------------------------------------------------------- authorization
def test_is_authorized_domain_and_allowlist():
    dom = Config(auth_allowed_domain="scigrow.tech")
    assert auth.is_authorized("marius@scigrow.tech", dom)
    assert auth.is_authorized("MARIUS@SciGrow.Tech", dom)  # case-insensitive
    assert not auth.is_authorized("evil@gmail.com", dom)
    assert not auth.is_authorized(None, dom)
    assert not auth.is_authorized("", dom)

    # fail closed: nothing configured => nobody in
    assert not auth.is_authorized("anyone@scigrow.tech", Config())

    # allow-list narrows even within domain
    both = Config(auth_allowed_domain="scigrow.tech",
                  auth_allowed_emails=["boss@scigrow.tech"])
    assert auth.is_authorized("boss@scigrow.tech", both)
    assert not auth.is_authorized("intern@scigrow.tech", both)


def test_authorize_url_and_tenant():
    g = Config(auth_provider="google", oauth_client_id="cid",
               oauth_redirect_url="https://d.example/auth/callback",
               auth_allowed_domain="scigrow.tech")
    url = auth.authorize_url(g, "STATE123")
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid" in url and "state=STATE123" in url
    assert "hd=scigrow.tech" in url  # google domain hint
    assert "response_type=code" in url

    m = Config(auth_provider="microsoft", oauth_tenant="mytenant",
               oauth_client_id="cid", oauth_redirect_url="https://d/x")
    eps = auth.provider_endpoints(m)
    assert "mytenant" in eps["authorize"] and "mytenant" in eps["token"]


# ---------------------------------------------------------------- gating (live)
def _start_server(config):
    handler = type("H", (dashboard._Handler,), {
        "config": config, "days": 7, "weeks": 4, "period_days": 7})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def _get(port, path, cookie=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Cookie": cookie} if cookie else {}
    c.request("GET", path, headers=headers)
    r = c.getresponse()
    body = r.read()
    r_headers = r.getheaders()
    c.close()
    return r.status, dict(r_headers), body, r_headers


def _set_cookies(header_list):
    return [v for (k, v) in header_list if k.lower() == "set-cookie"]


def test_gating_redirects_and_allows(monkeypatch=None):
    cfg = Config(auth_enabled=True, auth_provider="google",
                 oauth_client_id="cid", oauth_client_secret="sec",
                 oauth_redirect_url="http://127.0.0.1/auth/callback",
                 auth_allowed_domain="scigrow.tech", session_secret=SECRET,
                 session_ttl=3600)
    httpd, port = _start_server(cfg)
    try:
        # 1. unauthenticated app route redirects to /auth/login
        status, headers, _, _ = _get(port, "/")
        assert status == 302 and headers.get("Location") == "/auth/login"

        # 2. /auth/login redirects to Google and sets a state cookie
        status, headers, _, hlist = _get(port, "/auth/login")
        assert status == 302
        assert headers["Location"].startswith("https://accounts.google.com/")
        state_cookies = _set_cookies(hlist)
        assert any(c.startswith("sat_state=") for c in state_cookies)

        # 3. patch the network calls and drive the callback with a valid state
        import activity_tracker.auth as auth_mod
        auth_mod.exchange_code = lambda cfg, code: "fake-token"
        auth_mod.fetch_email = lambda cfg, tok: "marius@scigrow.tech"
        state = auth.make_state(SECRET)
        status, headers, _, hlist = _get(
            port, f"/auth/callback?code=abc&state={state}",
            cookie=f"sat_state={state}")
        assert status == 302 and headers["Location"] == "/"
        sess = [c for c in _set_cookies(hlist) if c.startswith("sat_session=")]
        assert sess
        session_val = sess[0].split("=", 1)[1].split(";", 1)[0]

        # 4. app route now returns 200 with the session cookie, and the page
        #    carries the signed-in identity for the "signed in as … · sign out" chip
        status, _, body, _ = _get(port, "/", cookie=f"sat_session={session_val}")
        assert status == 200 and b"<!doctype html>" in body.lower()
        assert b"marius@scigrow.tech" in body
        assert b"/auth/logout" in body

        # 5. an unauthorized email is rejected at callback
        auth_mod.fetch_email = lambda cfg, tok: "outsider@gmail.com"
        state2 = auth.make_state(SECRET)
        status, _, body, _ = _get(
            port, f"/auth/callback?code=abc&state={state2}",
            cookie=f"sat_state={state2}")
        assert status == 403 and b"not authorized" in body

        # 6. CSRF: mismatched state is rejected
        good = auth.make_state(SECRET)
        status, _, _, _ = _get(port, f"/auth/callback?code=abc&state={good}",
                               cookie="sat_state=different")
        assert status == 400
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    test_sign_unsign_roundtrip_and_tamper()
    test_session_expiry()
    test_is_authorized_domain_and_allowlist()
    test_authorize_url_and_tenant()
    test_gating_redirects_and_allows()
    print("All auth tests passed.")
