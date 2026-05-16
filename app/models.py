"""
Database models for the verifier web app.

Tables:
  users           — Vicky, the shipping coordinator, anyone else with access
  signatures      — per-user PNG signature image (stored as bytes; small)
  customers       — California Fruit's customer registry (mirrors customers.yaml
                    so the dashboard can drill down)
  packets         — uploaded packet metadata + verifier outputs pointer
  packet_runs     — every verifier execution (original + each rescan)
  field_overrides — Vicky's edit-and-propagate corrections
  signoffs        — per-packet sign-off audit record
  audit_log       — generic who-did-what-when log for SQF compliance
  billing_events  — per-packet cost record for Stripe pass-through
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), unique=True,
                                                       nullable=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="verifier")
    # roles: 'admin' | 'verifier' | 'viewer'
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    signature: Mapped[Optional["Signature"]] = relationship(
        "Signature", back_populates="user", uselist=False, cascade="all, delete-orphan")


class Signature(Base):
    __tablename__ = "signatures"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), unique=True)
    image_png: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    width_px: Mapped[int] = mapped_column(Integer, default=400)
    height_px: Mapped[int] = mapped_column(Integer, default=120)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    user: Mapped[User] = relationship("User", back_populates="signature")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    canonical_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    customer_code: Mapped[str] = mapped_column(String(64), default="")
    co_packer_route: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_bol: Mapped[bool] = mapped_column(Boolean, default=True)
    requires_trailer_inspection: Mapped[bool] = mapped_column(Boolean, default=True)
    is_backup_source_only: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class Packet(Base):
    __tablename__ = "packets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_canonical: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    invoice_no: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    work_orders: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    year: Mapped[int] = mapped_column(Integer, default=lambda: _now().year, index=True)
    n_pages: Mapped[int] = mapped_column(Integer, default=0)
    n_sub_packets: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    # status: queued | running | passed | failed | error | archived | superseded
    overall_color: Mapped[str] = mapped_column(String(16), default="grey")
    n_pass: Mapped[int] = mapped_column(Integer, default=0)
    n_fail: Mapped[int] = mapped_column(Integer, default=0)
    n_info: Mapped[int] = mapped_column(Integer, default=0)
    storage_key_input_pdf: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    storage_key_verified_pdf: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    storage_key_matrix_xlsx: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    storage_key_issues_csv: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    storage_key_trace_json: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    uploaded_by_user_id: Mapped[Optional[str]] = mapped_column(String(36),
                                                               ForeignKey("users.id"), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # `superseded_by_packet_id` is set when a corrected rescan is uploaded.
    superseded_by_packet_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)

    runs: Mapped[list["PacketRun"]] = relationship(
        "PacketRun", back_populates="packet", cascade="all, delete-orphan")
    field_overrides: Mapped[list["FieldOverride"]] = relationship(
        "FieldOverride", back_populates="packet", cascade="all, delete-orphan")
    signoffs: Mapped[list["Signoff"]] = relationship(
        "Signoff", back_populates="packet", cascade="all, delete-orphan")


class PacketRun(Base):
    __tablename__ = "packet_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    packet_id: Mapped[str] = mapped_column(String(36), ForeignKey("packets.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running")
    vision_provider: Mapped[str] = mapped_column(String(32), default="mock")
    n_pages_processed: Mapped[int] = mapped_column(Integer, default=0)
    n_vision_pages: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd_cents: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trace_json_storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    packet: Mapped[Packet] = relationship("Packet", back_populates="runs")


class FieldOverride(Base):
    """
    A correction Vicky made to a flagged value. The verifier re-applies these
    on every subsequent run (so a rescan keeps her corrections).
    """
    __tablename__ = "field_overrides"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    packet_id: Mapped[str] = mapped_column(String(36), ForeignKey("packets.id"), index=True)
    page_no: Mapped[int] = mapped_column(Integer, nullable=False)
    field_key: Mapped[str] = mapped_column(String(128), nullable=False)
    new_value: Mapped[str] = mapped_column(Text, nullable=False)
    propagate_to_pages: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON list
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edited_by_user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    edited_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    packet: Mapped[Packet] = relationship("Packet", back_populates="field_overrides")


class Signoff(Base):
    __tablename__ = "signoffs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    packet_id: Mapped[str] = mapped_column(String(36), ForeignKey("packets.id"), index=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    signed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    signature_image_png: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The PDF storage key for the stamped/archived version
    archived_pdf_storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    packet: Mapped[Packet] = relationship("Packet", back_populates="signoffs")


class AuditLog(Base):
    """Append-only audit log — never delete. SQF auditors love this stuff."""
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class BillingEvent(Base):
    __tablename__ = "billing_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    packet_id: Mapped[str] = mapped_column(String(36), ForeignKey("packets.id"), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    n_pages: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd_cents: Mapped[float] = mapped_column(Float, default=0.0)
    stripe_usage_record_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    stripe_status: Mapped[str] = mapped_column(String(32), default="pending")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
