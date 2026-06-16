"""
Database access via supabase-py using the service_role key.

The server is trusted, so it uses service_role (bypasses RLS). There is no
client-side DB access in this architecture — everything goes through here.
No migration tooling, no ORM: PostgREST calls against the four frozen tables.
"""

from supabase import Client, create_client

from .config import settings

_sb: Client = create_client(
    settings.supabase_url, settings.supabase_service_role_key
)


def ensure_user(user_id: str, email: str | None) -> None:
    """Create the app-side user row on first login (idempotent, no clobber)."""
    existing = (
        _sb.table("users").select("id").eq("id", user_id).limit(1).execute()
    )
    if not existing.data:
        _sb.table("users").insert(
            {
                "id": user_id,
                "email": email,
                "cohort_tag": settings.default_cohort_tag,
            }
        ).execute()


def get_active_key(user_id: str) -> dict | None:
    res = (
        _sb.table("api_keys")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "active")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def insert_key(user_id: str, key_hash: str, prefix: str) -> None:
    _sb.table("api_keys").insert(
        {
            "user_id": user_id,
            "key_hash": key_hash,
            "prefix": prefix,
            "status": "active",
        }
    ).execute()


def revoke_active_keys(user_id: str) -> None:
    _sb.table("api_keys").update({"status": "revoked"}).eq(
        "user_id", user_id
    ).eq("status", "active").execute()


# --- Slice 3: public API ----------------------------------------------------
def get_user_by_key_hash(key_hash: str) -> dict | None:
    """Resolve an active key to its owner. Returns {'user_id', 'cohort_tag'}.

    The embedded users(cohort_tag) select uses the api_keys.user_id -> users.id
    foreign key so the cohort lands on the usage_event for the retention study.
    """
    res = (
        _sb.table("api_keys")
        .select("user_id, users(cohort_tag)")
        .eq("key_hash", key_hash)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    embedded = row.get("users")
    cohort = embedded.get("cohort_tag") if isinstance(embedded, dict) else None
    return {"user_id": row["user_id"], "cohort_tag": cohort}


def used_seconds_this_period(user_id: str) -> float:
    """Sum of metered audio_seconds since the start of the current UTC month."""
    from datetime import datetime, timezone

    start = (
        datetime.now(timezone.utc)
        .replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        .isoformat()
    )
    res = (
        _sb.table("usage_events")
        .select("audio_seconds")
        .eq("user_id", user_id)
        .gte("ts", start)
        .execute()
    )
    return sum(float(r["audio_seconds"] or 0) for r in (res.data or []))


def insert_usage_event(
    user_id: str,
    audio_seconds: float,
    model_version: str,
    cohort_tag: str | None,
) -> None:
    _sb.table("usage_events").insert(
        {
            "user_id": user_id,
            "audio_seconds": audio_seconds,
            "model_version": model_version,
            "cohort_tag": cohort_tag or settings.default_cohort_tag,
        }
    ).execute()
