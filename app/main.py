"""
California Fruit Inc. — AI Sorting Quality Verifier (production web app).

FastAPI entry point. Wraps the engine/ verifier in:
  - Multi-user auth (Clerk / Supabase / dev)
  - Persistent Postgres (or SQLite in dev)
  - S3 / R2 / local storage for PDFs and outputs
  - Background packet verification
  - Edit-and-propagate corrections
  - Per-user digital signatures
  - Sign-off + archive flow with audit log
  - Customer-index dashboard view
  - Per-packet rescan
  - Mobile/tablet-friendly verification UI
  - Stripe pass-through billing (~$0.04/packet)

Run:  uvicorn app.main:app --reload
Docs: http://localhost:8000/docs
UI:   http://localhost:8000/
"""
from __future__ import annotations

import base64
import json
import shutil
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from contextlib import asynccontextmanager

from fastapi import (BackgroundTasks, Depends, FastAPI, File, Form, HTTPException,
                      Query, Response, UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from .auth import get_current_user, require_role
from .config import SETTINGS, PROJECT_ROOT
from .db import create_all, db_session, get_db
from .models import (AuditLog, BillingEvent, Customer, FieldOverride, Packet,
                      PacketRun, Signature, Signoff, User)
from .schemas import (CustomerSummary, FieldOverrideIn, FieldOverrideOut,
                       PacketDetail, PacketSummary, SignoffIn, SignoffOut, UserOut)
from .stamping import stamp_signoff
from .storage import archive_key, storage
from .verifier_runner import run_packet_verification


# ---------------------------------------------------------------------------
# App setup — modern lifespan API (works in both uvicorn and TestClient)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Boot
    create_all()
    web_dir = PROJECT_ROOT / "web"
    if web_dir.exists():
        app.mount("/ui", StaticFiles(directory=web_dir, html=True), name="ui")
    # Sync customers from YAML so the drill-down view has rows on first launch
    try:
        from .verifier_runner import _import_verifier
        _import_verifier()
        from verifier import Config       # type: ignore
        cfg = Config.load(PROJECT_ROOT / "engine" / "config")
        with db_session() as db:
            for cp in cfg.customers:
                existing = db.query(Customer).filter(
                    Customer.canonical_name == cp.canonical).one_or_none()
                if existing is None:
                    db.add(Customer(
                        canonical_name=cp.canonical,
                        customer_code=cp.customer_code,
                        co_packer_route=cp.co_packer_route,
                        requires_bol=cp.requires_bol,
                        requires_trailer_inspection=cp.requires_trailer_inspection,
                        is_backup_source_only=cp.is_backup_source_only,
                        notes=cp.notes,
                    ))
    except Exception as e:
        print(f"[startup] customer sync skipped: {e}")
    yield
    # Shutdown — nothing to clean up; SessionLocal is per-request


app = FastAPI(
    title="California Fruit Inc. — AI Sorting Quality Verifier",
    version="1.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", include_in_schema=False)
def root_index():
    return FileResponse(PROJECT_ROOT / "web" / "index.html")


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": "1.0.0", "env": SETTINGS.env,
            "auth_provider": SETTINGS.auth_provider,
            "vision_provider": SETTINGS.vision_provider,
            "storage_backend": SETTINGS.storage_backend}


# ---------------------------------------------------------------------------
# Local storage browse (only used when STORAGE_BACKEND=local)
# ---------------------------------------------------------------------------

@app.get("/storage/{full_path:path}", include_in_schema=False)
def serve_local_storage(full_path: str,
                         _user: User = Depends(get_current_user)):
    if SETTINGS.storage_backend != "local":
        raise HTTPException(status_code=404, detail="local storage not enabled")
    p = SETTINGS.storage_local_dir / full_path
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(p)


# ---------------------------------------------------------------------------
# Users + signatures
# ---------------------------------------------------------------------------

@app.get("/api/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut(id=user.id, email=user.email, full_name=user.full_name,
                   role=user.role, has_signature=user.signature is not None)


@app.put("/api/me/signature", response_model=UserOut)
async def upload_signature(
        signature: UploadFile = File(...),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)) -> UserOut:
    """
    Upload (or replace) the current user's stored signature image.
    The dashboard captures it via a <canvas> on first sign-in and posts a PNG.
    """
    if signature.content_type not in ("image/png", "image/jpeg", "image/webp"):
        raise HTTPException(status_code=400, detail="signature must be PNG/JPEG/WEBP")
    raw = await signature.read()
    if len(raw) > 1_000_000:
        raise HTTPException(status_code=400, detail="signature must be < 1MB")
    sig = user.signature or Signature(user_id=user.id, image_png=raw)
    sig.image_png = raw
    db.add(sig); db.commit(); db.refresh(user)
    db.add(AuditLog(user_id=user.id, user_email=user.email,
                    action="signature.update", target_type="user",
                    target_id=user.id))
    db.commit()
    return UserOut(id=user.id, email=user.email, full_name=user.full_name,
                   role=user.role, has_signature=True)


@app.get("/api/me/signature.png")
def get_my_signature(user: User = Depends(get_current_user)):
    if not user.signature:
        raise HTTPException(status_code=404)
    return Response(content=user.signature.image_png, media_type="image/png")


# ---------------------------------------------------------------------------
# Packets — list, upload, detail, rescan
# ---------------------------------------------------------------------------

def _packet_to_summary(p: Packet) -> PacketSummary:
    return PacketSummary(
        id=p.id, display_name=p.display_name,
        customer_canonical=p.customer_canonical, invoice_no=p.invoice_no,
        work_orders=p.work_orders, status=p.status,
        overall_color=p.overall_color, n_pages=p.n_pages,
        n_sub_packets=p.n_sub_packets, n_pass=p.n_pass,
        n_fail=p.n_fail, n_info=p.n_info,
        uploaded_at=p.uploaded_at, completed_at=p.completed_at,
    )


def _packet_to_detail(p: Packet) -> PacketDetail:
    s = storage()
    return PacketDetail(
        **_packet_to_summary(p).model_dump(),
        storage_url_verified_pdf=(
            s.url(p.storage_key_verified_pdf) if p.storage_key_verified_pdf else None),
        storage_url_matrix_xlsx=(
            s.url(p.storage_key_matrix_xlsx) if p.storage_key_matrix_xlsx else None),
        storage_url_issues_csv=(
            s.url(p.storage_key_issues_csv) if p.storage_key_issues_csv else None),
        storage_url_trace_json=(
            s.url(p.storage_key_trace_json) if p.storage_key_trace_json else None),
        error_message=p.error_message,
    )


@app.get("/api/packets", response_model=List[PacketSummary])
def list_packets(customer: Optional[str] = Query(default=None),
                  status: Optional[str] = Query(default=None),
                  limit: int = Query(default=200, le=2000),
                  user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    q = db.query(Packet).filter(Packet.status != "superseded")
    if customer:
        q = q.filter(Packet.customer_canonical == customer)
    if status:
        q = q.filter(Packet.status == status)
    q = q.order_by(desc(Packet.uploaded_at)).limit(limit)
    return [_packet_to_summary(p) for p in q.all()]


@app.post("/api/packets", response_model=PacketDetail, status_code=202)
async def upload_packet(
        background: BackgroundTasks,
        pdf: UploadFile = File(...),
        display_name: Optional[str] = Form(default=None),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)):
    """Accept a PDF upload, queue verification in the background."""
    if pdf.content_type not in ("application/pdf", "application/x-pdf"):
        raise HTTPException(status_code=400, detail="must be a PDF")
    raw = await pdf.read()
    if len(raw) > SETTINGS.max_packet_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"PDF exceeds {SETTINGS.max_packet_size_mb} MB limit")

    name = display_name or Path(pdf.filename or "packet.pdf").name
    p = Packet(display_name=name, status="queued",
               year=datetime.utcnow().year,
               uploaded_by_user_id=user.id)
    db.add(p); db.commit(); db.refresh(p)
    key = archive_key(p.customer_canonical or "unassigned", p.year, "no-wo",
                      p.id, f"input_{name}")
    storage().put(key, __import__("io").BytesIO(raw), content_type="application/pdf")
    p.storage_key_input_pdf = key
    db.add(AuditLog(user_id=user.id, user_email=user.email, action="packet.upload",
                    target_type="packet", target_id=p.id,
                    details_json={"display_name": name, "size_bytes": len(raw)}))
    db.commit()

    background.add_task(run_packet_verification, p.id)
    return _packet_to_detail(p)


@app.get("/api/packets/{packet_id}", response_model=PacketDetail)
def get_packet(packet_id: str,
                user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    p = db.get(Packet, packet_id)
    if p is None:
        raise HTTPException(status_code=404)
    return _packet_to_detail(p)


@app.get("/api/packets/{packet_id}/trace")
def get_packet_trace(packet_id: str,
                      user: User = Depends(get_current_user),
                      db: Session = Depends(get_db)):
    p = db.get(Packet, packet_id)
    if p is None or not p.storage_key_trace_json:
        raise HTTPException(status_code=404)
    raw = storage().get(p.storage_key_trace_json)
    return JSONResponse(content=json.loads(raw))


@app.post("/api/packets/{packet_id}/rescan", response_model=PacketDetail,
          status_code=202)
async def rescan_packet(
        packet_id: str,
        background: BackgroundTasks,
        pdf: Optional[UploadFile] = File(default=None),
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db)):
    """
    Re-run the verifier on a packet.
    - If a new PDF is provided, supersede the original (audit-preserving) and
      run on the corrected version.
    - If no PDF is provided, re-run on the existing input PDF (e.g. after
      Vicky added a new field override).
    """
    p = db.get(Packet, packet_id)
    if p is None:
        raise HTTPException(status_code=404)

    if pdf is not None:
        raw = await pdf.read()
        if len(raw) > SETTINGS.max_packet_size_mb * 1024 * 1024:
            raise HTTPException(status_code=413, detail="PDF too large")
        # Create a NEW packet that supersedes the old (preserve original for audit)
        new_p = Packet(
            display_name=pdf.filename or p.display_name,
            customer_canonical=p.customer_canonical,
            year=p.year,
            status="queued",
            uploaded_by_user_id=user.id,
        )
        db.add(new_p); db.commit(); db.refresh(new_p)
        key = archive_key(new_p.customer_canonical or "unassigned", new_p.year,
                          "no-wo", new_p.id,
                          f"input_{pdf.filename or 'packet.pdf'}")
        storage().put(key, __import__("io").BytesIO(raw),
                      content_type="application/pdf")
        new_p.storage_key_input_pdf = key

        # Carry over the existing field overrides — corrections persist across rescans
        for o in p.field_overrides:
            db.add(FieldOverride(
                packet_id=new_p.id, page_no=o.page_no,
                field_key=o.field_key, new_value=o.new_value,
                rationale=f"[carried from {p.id}] {o.rationale or ''}",
                edited_by_user_id=o.edited_by_user_id,
            ))

        p.status = "superseded"; p.superseded_by_packet_id = new_p.id
        db.add(AuditLog(user_id=user.id, user_email=user.email,
                        action="packet.rescan_with_new_pdf",
                        target_type="packet", target_id=p.id,
                        details_json={"new_packet_id": new_p.id}))
        db.commit()
        background.add_task(run_packet_verification, new_p.id)
        return _packet_to_detail(new_p)

    # No new PDF — re-run on the existing input
    p.status = "queued"
    db.add(AuditLog(user_id=user.id, user_email=user.email,
                    action="packet.rescan", target_type="packet", target_id=p.id))
    db.commit()
    background.add_task(run_packet_verification, p.id)
    return _packet_to_detail(p)


@app.delete("/api/packets/{packet_id}", status_code=204)
def delete_packet(packet_id: str,
                   user: User = Depends(require_role("admin")),
                   db: Session = Depends(get_db)):
    p = db.get(Packet, packet_id)
    if p is None:
        raise HTTPException(status_code=404)
    # Soft-delete: mark superseded but keep the rows + storage objects
    p.status = "superseded"
    db.add(AuditLog(user_id=user.id, user_email=user.email,
                    action="packet.delete", target_type="packet", target_id=p.id))
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Edit-and-propagate
# ---------------------------------------------------------------------------

@app.post("/api/packets/{packet_id}/overrides",
          response_model=FieldOverrideOut, status_code=201)
def add_field_override(packet_id: str,
                        body: FieldOverrideIn,
                        background: BackgroundTasks,
                        user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """
    Vicky clicks a flagged field, types the correct value. The override is
    stored AND a re-run is queued so every page that referenced the field
    is re-checked against the corrected value.
    """
    p = db.get(Packet, packet_id)
    if p is None:
        raise HTTPException(status_code=404)
    o = FieldOverride(
        packet_id=p.id, page_no=body.page_no, field_key=body.field_key,
        new_value=body.new_value, rationale=body.rationale,
        propagate_to_pages=(json.dumps(body.propagate_to_pages)
                            if body.propagate_to_pages else None),
        edited_by_user_id=user.id,
    )
    db.add(o)
    db.add(AuditLog(user_id=user.id, user_email=user.email,
                    action="packet.field_override",
                    target_type="packet", target_id=p.id,
                    details_json={"page_no": body.page_no,
                                  "field_key": body.field_key,
                                  "new_value": body.new_value}))
    p.status = "queued"
    db.commit(); db.refresh(o)
    background.add_task(run_packet_verification, p.id)
    return FieldOverrideOut(
        id=o.id, page_no=o.page_no, field_key=o.field_key,
        new_value=o.new_value, rationale=o.rationale,
        propagate_to_pages=body.propagate_to_pages,
        edited_by_email=user.email, edited_at=o.edited_at,
    )


@app.get("/api/packets/{packet_id}/overrides",
          response_model=List[FieldOverrideOut])
def list_overrides(packet_id: str,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    p = db.get(Packet, packet_id)
    if p is None:
        raise HTTPException(status_code=404)
    out = []
    for o in p.field_overrides:
        editor = db.get(User, o.edited_by_user_id)
        out.append(FieldOverrideOut(
            id=o.id, page_no=o.page_no, field_key=o.field_key,
            new_value=o.new_value, rationale=o.rationale,
            propagate_to_pages=(json.loads(o.propagate_to_pages)
                                if o.propagate_to_pages else None),
            edited_by_email=(editor.email if editor else None),
            edited_at=o.edited_at,
        ))
    return out


# ---------------------------------------------------------------------------
# Sign-off and archive (with verification stamp)
# ---------------------------------------------------------------------------

@app.post("/api/packets/{packet_id}/signoff", response_model=SignoffOut)
def signoff_packet(packet_id: str,
                    body: SignoffIn,
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    p = db.get(Packet, packet_id)
    if p is None:
        raise HTTPException(status_code=404)
    if not p.storage_key_verified_pdf:
        raise HTTPException(status_code=400, detail="packet has no verified PDF yet")

    # Resolve signature
    sig_png: Optional[bytes] = None
    if body.use_stored_signature and user.signature:
        sig_png = user.signature.image_png
    elif body.signature_png_b64:
        try:
            sig_png = base64.b64decode(body.signature_png_b64)
        except Exception:
            raise HTTPException(status_code=400, detail="invalid signature_png_b64")

    workdir = Path(tempfile.mkdtemp(prefix=f"signoff-{p.id[:8]}-"))
    try:
        in_pdf = workdir / "in.pdf"
        out_pdf = workdir / "archived.pdf"
        in_pdf.write_bytes(storage().get(p.storage_key_verified_pdf))
        stamp_signoff(in_pdf, out_pdf,
                       user_name=user.full_name or user.email,
                       signed_at=datetime.utcnow(),
                       signature_png=sig_png)

        archive_pdf_key = archive_key(
            p.customer_canonical or "unassigned", p.year,
            (p.work_orders or "no-wo").split(",")[0].strip(), p.id,
            f"{Path(p.display_name).stem}_ARCHIVED.pdf")
        storage().put_path(archive_pdf_key, out_pdf, content_type="application/pdf")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    s = Signoff(packet_id=p.id, user_id=user.id,
                signature_image_png=sig_png, notes=body.notes,
                archived_pdf_storage_key=archive_pdf_key)
    db.add(s); p.status = "archived"
    db.add(AuditLog(user_id=user.id, user_email=user.email,
                    action="packet.signoff", target_type="packet",
                    target_id=p.id,
                    details_json={"archived_pdf_key": archive_pdf_key}))
    db.commit(); db.refresh(s)

    return SignoffOut(id=s.id, user_email=user.email, signed_at=s.signed_at,
                      archived_pdf_url=storage().url(archive_pdf_key),
                      notes=s.notes)


# ---------------------------------------------------------------------------
# Customer-index dashboard view
# ---------------------------------------------------------------------------

@app.get("/api/customers", response_model=List[CustomerSummary])
def list_customer_summaries(user: User = Depends(get_current_user),
                              db: Session = Depends(get_db)):
    rows = (db.query(
        Packet.customer_canonical.label("name"),
        func.count(Packet.id).label("n"),
        func.sum(func.cast(Packet.status == "passed", __import__("sqlalchemy").Integer)).label("n_pass"),
        func.sum(func.cast(Packet.status == "failed", __import__("sqlalchemy").Integer)).label("n_fail"),
        func.max(Packet.uploaded_at).label("last_at"),
    ).filter(Packet.status != "superseded")
     .group_by(Packet.customer_canonical).all())
    out = []
    for r in rows:
        out.append(CustomerSummary(
            canonical_name=r.name or "(unassigned)",
            n_packets=r.n or 0,
            n_passed=int(r.n_pass or 0),
            n_failed=int(r.n_fail or 0),
            last_upload_at=r.last_at,
        ))
    out.sort(key=lambda c: (-(c.last_upload_at.timestamp() if c.last_upload_at else 0)))
    return out


# ---------------------------------------------------------------------------
# Stripe webhook (verifier reports usage; this confirms charge)
# ---------------------------------------------------------------------------

@app.post("/api/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request_body: dict):
    # Stub — full HMAC validation belongs in production. Logged for now.
    print(f"[stripe] webhook event: {request_body.get('type')}")
    return {"received": True}


# ---------------------------------------------------------------------------
# Minor admin endpoints
# ---------------------------------------------------------------------------

@app.get("/api/audit_log")
def get_audit_log(limit: int = 200,
                   user: User = Depends(require_role("admin")),
                   db: Session = Depends(get_db)):
    rows = (db.query(AuditLog).order_by(desc(AuditLog.at)).limit(limit).all())
    return [{"at": r.at.isoformat(), "user_email": r.user_email,
             "action": r.action, "target_type": r.target_type,
             "target_id": r.target_id, "details": r.details_json} for r in rows]
