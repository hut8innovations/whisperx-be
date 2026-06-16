-- STT Control Plane — frozen schema (Slices 1–2)
-- Run this once in the Supabase SQL editor.
-- All four tables are created now (schema-first) even though only
-- `users` and `api_keys` are exercised in slices 1–2.

-- 1. users: app-side row keyed to Supabase Auth's auth.users
create table if not exists public.users (
    id          uuid primary key references auth.users (id) on delete cascade,
    email       text,
    cohort_tag  text,
    created_at  timestamptz not null default now()
);

-- 2. api_keys: hashed-only key storage
create table if not exists public.api_keys (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references public.users (id) on delete cascade,
    key_hash    text not null unique,           -- SHA-256 of the plaintext key
    prefix      text not null,                  -- short display prefix, e.g. "stt_AbC12xYz"
    status      text not null default 'active'
                check (status in ('active', 'revoked')),
    created_at  timestamptz not null default now()
);
create index if not exists api_keys_user_id_idx on public.api_keys (user_id);

-- 3. usage_events: written from Slice 3 onward (defined now, unused in 1–2)
create table if not exists public.usage_events (
    id             uuid primary key default gen_random_uuid(),
    user_id        uuid not null references public.users (id) on delete cascade,
    ts             timestamptz not null default now(),
    audio_seconds  numeric not null default 0,
    model_version  text,
    cohort_tag     text
);
create index if not exists usage_events_user_id_ts_idx on public.usage_events (user_id, ts);

-- 4. subscriptions: written from Slice 6 (Razorpay) onward (defined now, unused in 1–2)
create table if not exists public.subscriptions (
    id                   uuid primary key default gen_random_uuid(),
    user_id              uuid not null unique references public.users (id) on delete cascade,
    plan                 text,
    status               text,
    razorpay_sub_id      text,
    current_period_end   timestamptz
);

-- RLS: on everywhere, no public policies. The trusted server uses the
-- service_role key (which bypasses RLS), so all DB access is mediated
-- by the app. anon/authenticated clients get zero direct access.
alter table public.users         enable row level security;
alter table public.api_keys      enable row level security;
alter table public.usage_events  enable row level security;
alter table public.subscriptions enable row level security;
