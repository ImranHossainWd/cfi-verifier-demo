"""Pydantic response/request models. Kept minimal — we serialize ORM rows
through a tiny adapter rather than introducing pydantic-orm magic."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class UserOut(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    has_signature: bool


class PacketSummary(BaseModel):
    id: str
    display_name: str
    customer_canonical: Optional[str]
    invoice_no: Optional[str]
    work_orders: Optional[str]
    status: str
    overall_color: str
    n_pages: int
    n_sub_packets: int
    n_pass: int
    n_fail: int
    n_info: int
    uploaded_at: datetime
    completed_at: Optional[datetime]


class PacketDetail(PacketSummary):
    storage_url_verified_pdf: Optional[str]
    storage_url_matrix_xlsx: Optional[str]
    storage_url_issues_csv: Optional[str]
    storage_url_trace_json: Optional[str]
    error_message: Optional[str]


class CustomerSummary(BaseModel):
    canonical_name: str
    n_packets: int
    n_passed: int
    n_failed: int
    last_upload_at: Optional[datetime]


class FieldOverrideIn(BaseModel):
    page_no: int
    field_key: str
    new_value: str
    rationale: Optional[str] = None
    propagate_to_pages: Optional[List[int]] = None


class FieldOverrideOut(BaseModel):
    id: str
    page_no: int
    field_key: str
    new_value: str
    rationale: Optional[str]
    propagate_to_pages: Optional[List[int]]
    edited_by_email: Optional[str]
    edited_at: datetime


class SignoffIn(BaseModel):
    notes: Optional[str] = None
    use_stored_signature: bool = True
    signature_png_b64: Optional[str] = None     # if not using stored


class SignoffOut(BaseModel):
    id: str
    user_email: str
    signed_at: datetime
    archived_pdf_url: Optional[str]
    notes: Optional[str]
