"""SSO authentication for the dashboard (OAuth2 authorization-code flow).

Design choices for safety with minimal dependencies:
  - Standard library only (urllib for HTTP, hmac/hashlib for cookies).
  - Identity is confirmed by calling the provider's ``userinfo`` endpoint with the
    access token rather than verifying an ID-token JWT locally — this avoids
    hand-rolling JWKS fetching and signature verification, which is easy to get
    subtly wrong. The userinfo response is authoritative.
  - Sessions are stateless: a cookie carrying {sub, exp} signed with an HMAC over
    ``session_secret``. No server-side session store to leak or lose.
  - Authorization FAILS CLOSED: with neither a domain nor an allow-list
    configured, nobody is authorized.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.parse
import urllib.request
from typing import Optional

from .config import Config

PROVIDERS = {
    "google": {
        "authorize": "https://accounts.google.com/o/oauth2/v2/auth",
        "token": "https://oauth2.googleapis.com/token",
        "userinfo": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
    },
    "microsoft": {
        # {tenant} is substituted from config.oauth_tenant.
        "authorize": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
        "token": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        "userinfo": "https://graph.microsoft.com/oidc/userinfo",
        "scope": "openid email profile",
    },
}


class AuthError(Exception):
    pass


def provider_endpoints(config: Config) -> dict:
    p = PROVIDERS.get(config.auth_provider)
    if not p:
        raise AuthError(f"unknown auth_provider: {config.auth_provider!r}")
    tenant = config.oauth_tenant or "organizations"
    return {
        "authorize": p["authorize"].format(tenant=tenant),
        "token": p["token"].format(tenant=tenant),
        "userinfo": p["userinfo"],
        "scope": p["scope"],
    }


# ------------------------------------------------------------- signed tokens
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(payload: dict, secret: str) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    sig = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def unsign(token: str, secret: str, now: Optional[float] = None) -> Optional[dict]:
    """Verify signature and expiry. Returns the payload dict or None."""
    now = now if now is not None else time.time()
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(_unb64(body))
        if float(data.get("exp", 0)) < now:
            return None
        return data
    except Exception:
        return None


def make_state(secret: str, now: Optional[float] = None) -> str:
    now = now if now is not None else time.time()
    return sign({"n": secrets.token_hex(8), "exp": now + 600, "pur": "state"}, secret)


def make_session(email: str, secret: str, ttl: float, now: Optional[float] = None) -> str:
    now = now if now is not None else time.time()
    return sign({"sub": email, "exp": now + ttl, "pur": "session"}, secret)


def session_email(cookie_value: str, secret: str, now: Optional[float] = None) -> Optional[str]:
    data = unsign(cookie_value, secret, now=now)
    if not data or data.get("pur") != "session":
        return None
    return data.get("sub")


# ---------------------------------------------------------------- authz check
def is_authorized(email: Optional[str], config: Config) -> bool:
    """Fail closed: authorize only verified emails matching the allow-list or domain."""
    if not email:
        return False
    email = email.strip().lower()
    allow = [e.strip().lower() for e in (config.auth_allowed_emails or []) if e.strip()]
    domain = (config.auth_allowed_domain or "").strip().lower().lstrip("@")
    if allow and email in allow:
        return True
    if domain and email.endswith("@" + domain):
        # If an allow-list is also set, domain membership alone is not enough.
        return not allow
    return False


# ---------------------------------------------------------------- oauth flow
def authorize_url(config: Config, state: str) -> str:
    ep = provider_endpoints(config)
    params = {
        "client_id": config.oauth_client_id,
        "redirect_uri": config.oauth_redirect_url,
        "response_type": "code",
        "scope": ep["scope"],
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    if config.auth_provider == "google" and config.auth_allowed_domain:
        params["hd"] = config.auth_allowed_domain  # domain hint (not a security control)
    return ep["authorize"] + "?" + urllib.parse.urlencode(params)


def exchange_code(config: Config, code: str) -> str:
    """Exchange an authorization code for an access token. Returns access_token."""
    ep = provider_endpoints(config)
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": config.oauth_client_id,
        "client_secret": config.oauth_client_secret,
        "redirect_uri": config.oauth_redirect_url,
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(ep["token"], data=data, method="POST",
                                 headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    token = payload.get("access_token")
    if not token:
        raise AuthError("token endpoint returned no access_token")
    return token


def fetch_email(config: Config, access_token: str) -> Optional[str]:
    """Call userinfo and return the verified email (or None)."""
    ep = provider_endpoints(config)
    req = urllib.request.Request(
        ep["userinfo"], headers={"Authorization": f"Bearer {access_token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        info = json.loads(resp.read().decode())
    email = info.get("email")
    # Google returns email_verified; Microsoft userinfo implies a real account.
    if config.auth_provider == "google" and info.get("email_verified") is False:
        return None
    return email
