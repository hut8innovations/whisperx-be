"""
Server-side Supabase Auth via the GoTrue REST API.

Why raw httpx instead of supabase-py for auth:
supabase-py's PKCE code verifier lives in browser-style local storage, which
does not survive a stateless server's authorize -> callback round trip. Here we
generate the PKCE pair ourselves, stash the verifier in the signed session
cookie, and exchange it manually. This is the only real "auth code" we write —
GoTrue does the rest.

Flow:
  1. /login         -> make PKCE pair, store verifier in session, 302 to authorize
  2. Google + GoTrue redirect back to /auth/callback?code=...
  3. /auth/callback -> POST /token?grant_type=pkce with {auth_code, code_verifier}
                       -> {access_token, refresh_token, expires_at, user}
  4. tokens kept in the signed session cookie; refreshed on expiry
"""

import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

from .config import settings

_http = httpx.Client(timeout=20.0)


def pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256."""
    verifier = secrets.token_urlsafe(64)  # ~86 chars, within the 43–128 range
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def authorize_url(challenge: str) -> str:
    query = urlencode(
        {
            "provider": "google",
            "redirect_to": f"{settings.app_base_url}/auth/callback",
            "code_challenge": challenge,
            "code_challenge_method": "s256",
        }
    )
    return f"{settings.supabase_url}/auth/v1/authorize?{query}"


def exchange_code(auth_code: str, code_verifier: str) -> dict:
    resp = _http.post(
        f"{settings.supabase_url}/auth/v1/token",
        params={"grant_type": "pkce"},
        headers={
            "apikey": settings.supabase_anon_key,
            "Content-Type": "application/json",
        },
        json={"auth_code": auth_code, "code_verifier": code_verifier},
    )
    resp.raise_for_status()
    return resp.json()


def refresh_session(refresh_token: str) -> dict | None:
    resp = _http.post(
        f"{settings.supabase_url}/auth/v1/token",
        params={"grant_type": "refresh_token"},
        headers={
            "apikey": settings.supabase_anon_key,
            "Content-Type": "application/json",
        },
        json={"refresh_token": refresh_token},
    )
    if resp.status_code != 200:
        return None
    return resp.json()
