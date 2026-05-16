"""
Auth provider abstraction. Three modes:

  AUTH_PROVIDER=dev        — bypass auth; auto-provision a single Vicky user.
                              Used for local development and CI smoke tests.

  AUTH_PROVIDER=clerk      — verify Clerk JWTs against Clerk's JWKS.
                              Set CLERK_JWKS_URL and CLERK_JWT_AUDIENCE.

  AUTH_PROVIDER=supabase   — verify Supabase JWTs with the project's HS256 secret.
                              Set SUPABASE_JWT_SECRET (the 'JWT Secret' under
                              Settings → API in the Supabase dashboard).

The web client sends the access token in the Authorization: Bearer header. The
get_current_user dependency turns it into a User row, auto-provisioning on the
first sign-in so admins don't need to pre-create accounts.
"""
from __future__ import annotations

import functools
import time
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from .config import SETTINGS
from .db import get_db
from .models import User


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _clerk_jwks() -> dict:
    import urllib.request
    import json as _json
    if not SETTINGS.clerk_jwks_url:
        raise RuntimeError("CLERK_JWKS_URL not set.")
    with urllib.request.urlopen(SETTINGS.clerk_jwks_url) as r:
        return _json.loads(r.read())


def _verify_clerk(token: str) -> dict:
    try:
        import jwt           # PyJWT
        from jwt import PyJWKClient
    except ImportError as e:
        raise RuntimeError("PyJWT[crypto] not installed.") from e
    jwks_client = PyJWKClient(SETTINGS.clerk_jwks_url)
    signing_key = jwks_client.get_signing_key_from_jwt(token).key
    payload = jwt.decode(
        token, signing_key,
        algorithms=["RS256"],
        audience=SETTINGS.clerk_jwt_audience,
        options={"verify_aud": bool(SETTINGS.clerk_jwt_audience)},
    )
    return payload


def _verify_supabase(token: str) -> dict:
    try:
        import jwt
    except ImportError as e:
        raise RuntimeError("PyJWT not installed.") from e
    if not SETTINGS.supabase_jwt_secret:
        raise RuntimeError("SUPABASE_JWT_SECRET not set.")
    payload = jwt.decode(
        token, SETTINGS.supabase_jwt_secret,
        algorithms=["HS256"], audience="authenticated",
    )
    return payload


def _verify_token(token: str) -> dict:
    if SETTINGS.auth_provider == "clerk":
        return _verify_clerk(token)
    if SETTINGS.auth_provider == "supabase":
        return _verify_supabase(token)
    raise HTTPException(status_code=500, detail="auth_provider misconfigured")


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def _get_or_create_user(db: Session, *, external_id: Optional[str],
                         email: str, name: str, role: str = "verifier") -> User:
    user = None
    if external_id:
        user = db.query(User).filter(User.external_id == external_id).one_or_none()
    if user is None and email:
        user = db.query(User).filter(User.email == email).one_or_none()
    if user is None:
        user = User(external_id=external_id, email=email, full_name=name, role=role)
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # Keep external_id / name fresh on each sign-in
        changed = False
        if external_id and not user.external_id:
            user.external_id = external_id; changed = True
        if name and not user.full_name:
            user.full_name = name; changed = True
        if changed:
            db.commit()
    user.last_seen_at = __import__("datetime").datetime.utcnow()
    db.commit()
    return user


def get_current_user(authorization: Optional[str] = Header(default=None),
                     db: Session = Depends(get_db)) -> User:
    if SETTINGS.auth_provider == "dev":
        # Dev shortcut — single shared user.
        return _get_or_create_user(
            db, external_id="dev-vicky",
            email="vicky@californiafruit.test", name="Vicky Melkonian",
            role="admin")

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Missing bearer token")
    token = authorization.split(None, 1)[1].strip()

    try:
        payload = _verify_token(token)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail=f"Invalid token: {e}")

    # Both Clerk and Supabase put the subject in `sub` and email in `email`.
    external_id = payload.get("sub")
    email = (payload.get("email")
             or payload.get("primary_email_address")
             or "")
    name = (payload.get("name")
            or payload.get("full_name")
            or payload.get("user_metadata", {}).get("full_name", ""))
    return _get_or_create_user(db, external_id=external_id, email=email, name=name)


def require_role(*allowed: str):
    """Dependency factory: require_role('admin') or require_role('admin', 'verifier')."""
    def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403,
                                detail=f"Requires role: {' or '.join(allowed)}")
        return user
    return _checker
