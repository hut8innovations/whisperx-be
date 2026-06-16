<<<<<<< HEAD
# whisperx-be
API framework to expose the model to runpod
=======
# STT Control Plane — Slices 1–2 (Auth + API Key)

FastAPI + HTMX control plane for the STT product. One server-rendered codebase.
**In scope:** schema, Google OAuth (Supabase Auth), hashed API-key issue/rotate/revoke.
**Not here (by design):** `/v1/transcribe`, playground, usage/analytics, Razorpay.

```
app/
  config.py    settings (env)
  auth.py      Supabase PKCE OAuth (raw httpx)
  db.py        Supabase DB via service_role
  security.py  API key gen + SHA-256 hash
  main.py      routes + session
  templates/   base, login, dashboard, _api_key_panel
schema.sql     the four frozen tables
```

## Prerequisites (do before coding/running)

1. **Supabase project** created (Auth + Postgres).
2. **Run `schema.sql`** in the Supabase SQL editor (creates all four tables, enables RLS).
3. **Google OAuth provider** enabled: Supabase Dashboard → Authentication → Providers → Google.
   - In Google Cloud Console create an OAuth client (Web application). Authorized redirect URI:
     `https://YOUR-REF.supabase.co/auth/v1/callback`
   - Paste the Client ID + Secret into the Supabase Google provider.
4. **Redirect allow list**: Supabase → Authentication → URL Configuration → add
   `http://localhost:8000/auth/callback` (dev) and `https://<your-app>.onrender.com/auth/callback` (prod).
   Set the Site URL to your app's base URL.

That's it — no RunPod, Redis, or Razorpay needed for slices 1–2.

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in Supabase keys + SESSION_SECRET
uvicorn app.main:app --reload
# open http://localhost:8000
```

## Deploy (Render free)

Push to Git, create a Render Web Service from `render.yaml`, set the three Supabase
secrets + `APP_BASE_URL` (your `.onrender.com` URL). `SESSION_SECRET` is auto-generated;
`COOKIE_SECURE` is `true`. Add the Render callback URL to the Supabase allow list (step 4).
Free tier spins down after 15 min idle (30–50s cold wake) — expected for the pilot.

## How auth works (server-side PKCE)

`/login` makes a PKCE pair, stores the verifier in the signed session cookie, and
redirects to Supabase's `/authorize`. Google → Supabase → `/auth/callback?code=...`,
where the code + verifier are exchanged at `/token?grant_type=pkce` for access/refresh
tokens. Tokens live in the signed, httpOnly, SameSite=Lax session cookie and refresh on
expiry. The user row is created in `public.users` on first login.

## API keys

Generated as `stt_<random>`; the **plaintext is shown once** at creation. Only the
SHA-256 `key_hash` and a short `prefix` are stored. Rotate = revoke active + issue new.
Revoke = mark active key revoked. Slice 3 validation will hash the presented key and
look it up by `key_hash`.

## Done-condition checklist

- [ ] Sign in with Google → land on the dashboard
- [ ] Generate an API key → full key shown once
- [ ] Reload → only the prefix is shown
- [ ] Rotate → new key shown once, old one revoked
- [ ] Revoke → no active key
- [ ] Keys stored hashed (`api_keys.key_hash`); four tables exist
- [ ] Nothing calls a transcribe endpoint

## STOP

Slice 3 (`/v1/transcribe`) needs the live RunPod Slice 0 endpoint returning
speaker-attributed JSON. Do not build slices 3–6, a mock transcribe path, the
playground, analytics, or Razorpay in this codebase yet.
>>>>>>> cb284dd (STT control plane: slices 1-3)
