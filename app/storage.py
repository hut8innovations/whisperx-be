"""
Supabase Storage handoff for the playground.

RunPod's worker fetches audio from a URL, so an uploaded file has to land
somewhere fetchable first. We put it in a PRIVATE bucket (server-side, via the
service-role client) and hand RunPod a short-lived signed URL — interview audio
shouldn't be world-readable, so a public bucket is the wrong default.
"""

import uuid

from .config import settings
from .db import _sb  # reuse the service-role client


def upload_and_sign(
    user_id: str,
    filename: str | None,
    data: bytes,
    content_type: str | None,
) -> str:
    """Store bytes under the user's prefix and return a signed URL."""
    safe = (filename or "audio").replace("/", "_").replace("\\", "_")
    path = f"{user_id}/{uuid.uuid4().hex}-{safe}"

    _sb.storage.from_(settings.playground_bucket).upload(
        path,
        data,
        {"content-type": content_type or "application/octet-stream"},
    )

    signed = _sb.storage.from_(settings.playground_bucket).create_signed_url(
        path, settings.signed_url_ttl_s
    )

    # The response key has drifted across client versions — handle the variants.
    url = None
    if isinstance(signed, dict):
        for key in ("signedURL", "signedUrl", "signed_url"):
            if signed.get(key):
                url = signed[key]
                break
    if not url:
        raise RuntimeError(f"Unexpected signed-URL response: {signed!r}")

    if url.startswith("http"):
        return url
    # Older clients return a path relative to the project host.
    return f"{settings.supabase_url}{url if url.startswith('/') else '/' + url}"
