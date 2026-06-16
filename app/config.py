from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # App
    session_secret: str
    app_base_url: str = "http://localhost:8000"  # no trailing slash
    cookie_secure: bool = False                   # true on Render (HTTPS)
    default_cohort_tag: str = "pilot"

    # --- Slice 3: model serving (RunPod, the dumb remote dependency) ---
    runpod_endpoint_id: str = ""
    runpod_api_key: str = ""
    model_version: str = "whisperx-large-v3-baseline"  # stamped on every usage_event
    monthly_quota_seconds: int = 36000                 # 10 hours / cycle (soft cap)
    runpod_poll_timeout_s: int = 300
    runpod_poll_interval_s: float = 2.5


settings = Settings()
