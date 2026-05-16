"""
App configuration — every value is overridable via environment variables.
See .env.example for the full list and infra/RUNBOOK.md for which provider
sets which value.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v else default


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENGINE_DIR = PROJECT_ROOT / "engine"
ENGINE_CONFIG_DIR = ENGINE_DIR / "config"
ENGINE_SRC_DIR = ENGINE_DIR / "src"


@dataclass
class Settings:
    # Runtime
    env: str = _env("ENV", "dev")                                # dev | staging | prod
    debug: bool = _env_bool("DEBUG", default=True)
    secret_key: str = _env("SECRET_KEY", "dev-secret-change-me")

    # HTTP
    base_url: str = _env("BASE_URL", "http://localhost:8000")
    cors_origins: List[str] = field(default_factory=lambda: [
        o.strip() for o in (_env("CORS_ORIGINS", "*") or "").split(",") if o.strip()
    ])

    # Database
    database_url: str = _env(
        "DATABASE_URL",
        f"sqlite:///{PROJECT_ROOT / 'cfi_local.db'}",
    )

    # Storage backend: 'local' | 's3' | 'r2'
    storage_backend: str = _env("STORAGE_BACKEND", "local")
    storage_local_dir: Path = Path(_env("STORAGE_LOCAL_DIR",
                                        str(PROJECT_ROOT / "storage")))
    s3_bucket: Optional[str] = _env("S3_BUCKET")
    s3_region: Optional[str] = _env("S3_REGION", "us-east-1")
    s3_endpoint_url: Optional[str] = _env("S3_ENDPOINT_URL")  # set for R2
    s3_access_key_id: Optional[str] = _env("S3_ACCESS_KEY_ID")
    s3_secret_access_key: Optional[str] = _env("S3_SECRET_ACCESS_KEY")
    s3_public_base_url: Optional[str] = _env("S3_PUBLIC_BASE_URL")

    # Adobe Document Cloud (optional auto-archive target)
    adobe_cloud_enabled: bool = _env_bool("ADOBE_CLOUD_ENABLED", default=False)
    adobe_client_id: Optional[str] = _env("ADOBE_CLIENT_ID")
    adobe_client_secret: Optional[str] = _env("ADOBE_CLIENT_SECRET")

    # Auth — choose one provider
    auth_provider: str = _env("AUTH_PROVIDER", "dev")  # dev | clerk | supabase
    clerk_secret_key: Optional[str] = _env("CLERK_SECRET_KEY")
    clerk_jwt_audience: Optional[str] = _env("CLERK_JWT_AUDIENCE")
    clerk_jwks_url: Optional[str] = _env("CLERK_JWKS_URL")
    supabase_url: Optional[str] = _env("SUPABASE_URL")
    supabase_anon_key: Optional[str] = _env("SUPABASE_ANON_KEY")
    supabase_service_role_key: Optional[str] = _env("SUPABASE_SERVICE_ROLE_KEY")
    supabase_jwt_secret: Optional[str] = _env("SUPABASE_JWT_SECRET")

    # Anthropic vision OCR
    anthropic_api_key: Optional[str] = _env("ANTHROPIC_API_KEY")
    anthropic_model: str = _env("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    # Set to 'mock' for offline runs, 'anthropic' for production
    vision_provider: str = _env("VISION_PROVIDER", "mock")
    vision_cache_path: Optional[str] = _env(
        "VISION_CACHE_PATH",
        str(ENGINE_DIR / "cache" / "vision_cache.json"),
    )
    # When true, every page is sent to vision OCR (useful for smoke-testing
    # that the API key works end-to-end; expect higher cost per packet).
    vision_force: bool = _env_bool("VISION_FORCE", default=False)

    # Stripe pass-through billing (no markup)
    stripe_enabled: bool = _env_bool("STRIPE_ENABLED", default=False)
    stripe_secret_key: Optional[str] = _env("STRIPE_SECRET_KEY")
    stripe_webhook_secret: Optional[str] = _env("STRIPE_WEBHOOK_SECRET")
    stripe_price_id_per_packet: Optional[str] = _env("STRIPE_PRICE_ID_PER_PACKET")
    # Cost basis for the pass-through ($0.04/packet at typical volume)
    cost_per_page_usd_cents: float = float(_env("COST_PER_PAGE_USD_CENTS", "0.3"))

    # Background jobs
    job_runner: str = _env("JOB_RUNNER", "fastapi_background")  # or 'rq' / 'celery'
    redis_url: Optional[str] = _env("REDIS_URL")

    # Verifier behavior
    max_packet_size_mb: int = _env_int("MAX_PACKET_SIZE_MB", 200)
    verifier_timeout_seconds: int = _env_int("VERIFIER_TIMEOUT_SECONDS", 600)


SETTINGS = Settings()
