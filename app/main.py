"""
STT Control Plane — FastAPI + HTMX, one server-rendered codebase.

Slices in this codebase:
  Schema  : schema.sql (run once in Supabase)
  Slice 1 : Google OAuth via Supabase Auth + route protection
  Slice 2 : hashed API-key issue / rotate / revoke (shown once)
  Slice 3 : public POST /v1/transcribe (API-key auth -> RunPod -> usage_event)

Deliberately NOT here: playground UI (4), usage/analytics panels (5),
Razorpay (6). Built against this same codebase in later sessions.
"""

import time

from fastapi import FastAPI, Header, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

from . import auth, db, runpod_client
from .config import settings
from .security import generate_api_key, hash_key

app = FastAPI(title="STT Control Plane")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    https_only=settings.cookie_secure,
    same_site="lax",  # blocks cross-site POST cookies -> baseline CSRF cover
)

templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------- session ----
def _store_tokens(session, token: dict) -> None:
    session["access_token"] = token["access_token"]
    session["refresh_token"] = token["refresh_token"]
    session["expires_at"] = token.get("expires_at") or (
        time.time() + token.get("expires_in", 3600)
    )
    user = token.get("user") or {}
    session["user_id"] = user.get("id")
    session["email"] = user.get("email")


def current_user(request: Request) -> dict | None:
    """Return {'id', 'email'} for a valid session, refreshing if needed."""
    session = request.session
    if not session.get("access_token"):
        return None

    # Trust the session until ~1 min before expiry; no per-request network call.
    if time.time() < session.get("expires_at", 0) - 60 and session.get("user_id"):
        return {"id": session["user_id"], "email": session.get("email")}

    # Expired -> try a refresh.
    refresh_token = session.get("refresh_token")
    if refresh_token:
        token = auth.refresh_session(refresh_token)
        if token:
            _store_tokens(session, token)
            return {"id": session["user_id"], "email": session.get("email")}

    session.clear()
    return None


def _unauthorized(request: Request) -> Response:
    """Redirect to login — via HX-Redirect for HTMX requests, 302 otherwise."""
    if request.headers.get("hx-request") == "true":
        return Response(status_code=204, headers={"HX-Redirect": "/login"})
    return RedirectResponse("/login", status_code=302)


def _render_key_panel(request: Request, key: dict | None, plaintext: str | None):
    return templates.TemplateResponse(
        request,
        "_api_key_panel.html",
        {"key": key, "plaintext": plaintext},
    )


# ------------------------------------------------------------------ routes ----
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    if current_user(request):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(request, "login.html", {})


@app.get("/login")
def login(request: Request):
    verifier, challenge = auth.pkce_pair()
    request.session["pkce_verifier"] = verifier
    return RedirectResponse(auth.authorize_url(challenge), status_code=302)


@app.get("/auth/callback", response_class=HTMLResponse)
def auth_callback(request: Request, code: str | None = None, error: str | None = None):
    if error or not code:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": error or "Sign-in was cancelled or failed."},
        )

    verifier = request.session.pop("pkce_verifier", None)
    if not verifier:
        # Verifier lost (different browser/expired session) — restart cleanly.
        return RedirectResponse("/login", status_code=302)

    try:
        token = auth.exchange_code(code, verifier)
    except Exception:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Could not complete sign-in. Please try again."},
        )

    _store_tokens(request.session, token)
    if request.session.get("user_id"):
        db.ensure_user(request.session["user_id"], request.session.get("email"))
    return RedirectResponse("/dashboard", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = current_user(request)
    if not user:
        return _unauthorized(request)
    key = db.get_active_key(user["id"])
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"user": user, "key": key, "plaintext": None},
    )


# --- Slice 2: API key panel (HTMX, swaps #key-panel) -------------------------
@app.post("/keys", response_class=HTMLResponse)
def create_key(request: Request):
    user = current_user(request)
    if not user:
        return _unauthorized(request)

    existing = db.get_active_key(user["id"])
    if existing:
        # Already issued; do not mint a duplicate. Rotate to replace.
        return _render_key_panel(request, existing, None)

    plaintext, key_hash, prefix = generate_api_key()
    db.insert_key(user["id"], key_hash, prefix)
    return _render_key_panel(request, db.get_active_key(user["id"]), plaintext)


@app.post("/keys/rotate", response_class=HTMLResponse)
def rotate_key(request: Request):
    user = current_user(request)
    if not user:
        return _unauthorized(request)

    db.revoke_active_keys(user["id"])
    plaintext, key_hash, prefix = generate_api_key()
    db.insert_key(user["id"], key_hash, prefix)
    return _render_key_panel(request, db.get_active_key(user["id"]), plaintext)


@app.post("/keys/revoke", response_class=HTMLResponse)
def revoke_key(request: Request):
    user = current_user(request)
    if not user:
        return _unauthorized(request)

    db.revoke_active_keys(user["id"])
    return _render_key_panel(request, None, None)


# --- Slice 3: public API (API-key auth, NOT cookie session) ------------------
class TranscribeRequest(BaseModel):
    audio_url: str
    min_speakers: int | None = None
    max_speakers: int | None = None


def _api_key_owner(authorization: str | None) -> dict | None:
    """Resolve `Authorization: Bearer <key>` to {'user_id', 'cohort_tag'}."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    presented = authorization.split(" ", 1)[1].strip()
    if not presented:
        return None
    return db.get_user_by_key_hash(hash_key(presented))


@app.post("/v1/transcribe")
def transcribe(body: TranscribeRequest, authorization: str | None = Header(default=None)):
    owner = _api_key_owner(authorization)
    if not owner:
        return JSONResponse({"error": "invalid_api_key"}, status_code=401)

    # Soft quota: reject only if already over the cycle cap. We can't know the
    # new file's duration until after transcription, so we don't pre-charge it.
    used = db.used_seconds_this_period(owner["user_id"])
    if used >= settings.monthly_quota_seconds:
        return JSONResponse(
            {
                "error": "quota_exceeded",
                "used_seconds": used,
                "quota_seconds": settings.monthly_quota_seconds,
            },
            status_code=402,
        )

    if not settings.runpod_endpoint_id or not settings.runpod_api_key:
        return JSONResponse({"error": "model_endpoint_not_configured"}, status_code=503)

    try:
        output = runpod_client.transcribe(
            body.audio_url, body.min_speakers, body.max_speakers
        )
    except runpod_client.RunPodTimeout:
        return JSONResponse({"error": "transcription_timeout"}, status_code=504)
    except runpod_client.RunPodError as exc:
        return JSONResponse(
            {"error": "transcription_failed", "detail": str(exc)}, status_code=502
        )

    shaped = runpod_client.shape(output)
    db.insert_usage_event(
        owner["user_id"],
        shaped["audio_seconds"],
        settings.model_version,
        owner.get("cohort_tag"),
    )
    return {
        "model_version": settings.model_version,
        "detected_language": shaped["detected_language"],
        "audio_seconds": shaped["audio_seconds"],
        "full_transcript": shaped["full_transcript"],
        "segments": shaped["segments"],
    }


@app.get("/healthz")
def healthz():
    return {"ok": True}
