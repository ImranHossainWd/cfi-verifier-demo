"""
Storage abstraction. Two backends:
  - LocalStorage (dev / single-server)
  - S3Storage    (S3 or Cloudflare R2 — both speak the same API)

Set STORAGE_BACKEND=local|s3|r2 to switch. R2 just sets a custom endpoint URL.
Files are stored under keys shaped like:
    customers/<customer_slug>/<year>/<wo_slug>/<packet_id>/<filename>
"""
from __future__ import annotations

import io
import re
import shutil
from pathlib import Path
from typing import BinaryIO, Optional

from .config import SETTINGS


_SLUG_RE = re.compile(r"[^a-zA-Z0-9_\-]+")


def _slug(s: str) -> str:
    return _SLUG_RE.sub("-", (s or "unknown")).strip("-").lower() or "unknown"


def archive_key(customer: Optional[str], year: int,
                wo: Optional[str], packet_id: str, filename: str) -> str:
    return (
        f"customers/{_slug(customer or 'unassigned')}/"
        f"{year}/{_slug(wo or 'no-wo')}/{packet_id}/{filename}"
    )


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class StorageBackend:
    name = "abstract"

    def put(self, key: str, data: BinaryIO, content_type: str = "application/octet-stream") -> str:
        raise NotImplementedError

    def put_path(self, key: str, src_path: Path,
                 content_type: str = "application/octet-stream") -> str:
        with src_path.open("rb") as f:
            return self.put(key, f, content_type=content_type)

    def get(self, key: str) -> bytes:
        raise NotImplementedError

    def url(self, key: str, expires_seconds: int = 3600) -> str:
        raise NotImplementedError

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


class LocalStorage(StorageBackend):
    name = "local"

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        # Defensive: never allow path traversal
        safe = key.replace("..", "").lstrip("/")
        return self.root / safe

    def put(self, key: str, data: BinaryIO, content_type: str = "application/octet-stream") -> str:
        target = self._p(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as f:
            shutil.copyfileobj(data, f)
        return key

    def get(self, key: str) -> bytes:
        return self._p(key).read_bytes()

    def url(self, key: str, expires_seconds: int = 3600) -> str:
        # Served by FastAPI at /storage/<key>
        return f"{SETTINGS.base_url}/storage/{key}"

    def exists(self, key: str) -> bool:
        return self._p(key).exists()

    def delete(self, key: str) -> None:
        p = self._p(key)
        if p.exists():
            p.unlink()


class S3Storage(StorageBackend):
    """Works against S3, Cloudflare R2, MinIO, or any S3-compatible service."""
    name = "s3"

    def __init__(self):
        try:
            import boto3  # type: ignore
        except ImportError as e:
            raise RuntimeError("boto3 not installed. Add 'boto3' to requirements.txt.") from e
        kwargs = dict(
            region_name=SETTINGS.s3_region,
            aws_access_key_id=SETTINGS.s3_access_key_id,
            aws_secret_access_key=SETTINGS.s3_secret_access_key,
        )
        if SETTINGS.s3_endpoint_url:
            kwargs["endpoint_url"] = SETTINGS.s3_endpoint_url
        self._client = boto3.client("s3", **kwargs)
        if not SETTINGS.s3_bucket:
            raise RuntimeError("S3_BUCKET env var is required for s3/r2 backend.")
        self.bucket = SETTINGS.s3_bucket

    def put(self, key: str, data: BinaryIO, content_type: str = "application/octet-stream") -> str:
        self._client.upload_fileobj(
            Fileobj=data,
            Bucket=self.bucket,
            Key=key,
            ExtraArgs={"ContentType": content_type},
        )
        return key

    def get(self, key: str) -> bytes:
        buf = io.BytesIO()
        self._client.download_fileobj(Bucket=self.bucket, Key=key, Fileobj=buf)
        return buf.getvalue()

    def url(self, key: str, expires_seconds: int = 3600) -> str:
        if SETTINGS.s3_public_base_url:
            return f"{SETTINGS.s3_public_base_url.rstrip('/')}/{key}"
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_seconds,
        )

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_BACKEND: Optional[StorageBackend] = None


def storage() -> StorageBackend:
    global _BACKEND
    if _BACKEND is None:
        kind = SETTINGS.storage_backend.lower()
        if kind in ("s3", "r2"):
            _BACKEND = S3Storage()
        else:
            _BACKEND = LocalStorage(SETTINGS.storage_local_dir)
    return _BACKEND
