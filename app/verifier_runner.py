"""Wraps engine/src/verifier.verify_pdf for the FastAPI app."""
from __future__ import annotations

import shutil
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

from .config import SETTINGS, ENGINE_DIR, ENGINE_SRC_DIR
from .db import db_session
from .models import (AuditLog, BillingEvent, FieldOverride, Packet, PacketRun)
from .storage import archive_key, storage
from .stamping import stamp_pdf

if str(ENGINE_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_SRC_DIR))


def _import_verifier():
    from verifier import verify_pdf  # type: ignore
    return verify_pdf


def _summarize_report(report) -> dict:
    n_pass = sum(1 for c in report.all_checks if c.status == "pass")
    n_fail = sum(1 for c in report.all_checks if c.status == "fail")
    n_info = sum(1 for c in report.all_checks if c.status == "info")
    overall = "passed" if n_fail == 0 else "failed"
    customer = (report.customer_profile.canonical
                if report.customer_profile else None)
    work_orders = sorted({sp.primary_wo for sp in report.sub_packets if sp.primary_wo})
    invoice_no = next(
        (p.fields.get("invoice_no") for p in report.pages
         if p.fields.get("invoice_no")), None)
    return {
        "n_pass": n_pass, "n_fail": n_fail, "n_info": n_info,
        "overall": overall, "customer": customer,
        "invoice_no": invoice_no,
        "work_orders": ", ".join(str(w) for w in work_orders) or None,
    }


def _apply_overrides(report, overrides) -> None:
    by_page = {}
    for o in overrides:
        by_page.setdefault(o["page_no"], {})[o["field_key"]] = o["new_value"]
    for p in report.pages:
        u = by_page.get(p.page_no)
        if not u:
            continue
        for k, v in u.items():
            p.fields[k] = v
            p.notes.append("OVERRIDE applied " + k + "=" + str(v))


def run_packet_verification(packet_id: str) -> None:
    """Run verifier for a packet; update DB; emit billing event."""
    started = time.time()
    with db_session() as db:
        packet = db.get(Packet, packet_id)
        if packet is None:
            return
        packet.status = "running"
        db.add(AuditLog(
            user_id=packet.uploaded_by_user_id,
            action="verify.start",
            target_type="packet", target_id=packet_id,
            details_json={"packet_name": packet.display_name},
        ))
        db.commit()

        run = PacketRun(packet_id=packet_id, status="running",
                        vision_provider=SETTINGS.vision_provider)
        db.add(run); db.commit(); db.refresh(run)
        run_id = run.id
        input_pdf_key = packet.storage_key_input_pdf
        packet_display_name = packet.display_name
        packet_year = packet.year

        try:
            input_pdf_bytes = storage().get(input_pdf_key)
        except Exception as e:
            packet.status = "error"
            packet.error_message = "Could not load input PDF: " + str(e)
            run.status = "error"; run.error_message = str(e)
            db.commit()
            return

        overrides = [
            {"page_no": o.page_no, "field_key": o.field_key, "new_value": o.new_value}
            for o in db.query(FieldOverride)
                       .filter(FieldOverride.packet_id == packet_id).all()
        ]

    workdir = Path(tempfile.mkdtemp(prefix="cfi-" + packet_id[:8] + "-"))
    try:
        input_pdf = workdir / "input.pdf"
        input_pdf.write_bytes(input_pdf_bytes)
        out_dir = workdir / "out"
        out_dir.mkdir(parents=True, exist_ok=True)
        verify_pdf = _import_verifier()
        try:
            report = verify_pdf(
                pdf_path=str(input_pdf),
                out_dir=str(out_dir),
                config_dir=str(ENGINE_DIR / "config"),
                ocr_provider=SETTINGS.vision_provider,
                vision_cache_path=SETTINGS.vision_cache_path,
                packet_name=Path(packet_display_name).stem or "packet",
                vision_model=SETTINGS.anthropic_model,
                vision_force=SETTINGS.vision_force,
            )
        except Exception as e:
            with db_session() as db:
                p = db.get(Packet, packet_id)
                p.status = "error"
                p.error_message = "Verifier crashed: " + str(e)
                r = db.get(PacketRun, run_id)
                r.status = "error"
                r.error_message = traceback.format_exc(limit=8)
                db.add(AuditLog(action="verify.error", target_type="packet",
                                target_id=packet_id, details_json={"error": str(e)}))
            return

        if overrides:
            _apply_overrides(report, overrides)

        summary = _summarize_report(report)

        name = report.packet_name
        verified_pdf = out_dir / (name + "_AI_VERIFIED.pdf")
        matrix_xlsx  = out_dir / (name + "_cross_reference_matrix.xlsx")
        issues_csv   = out_dir / (name + "_issues.csv")
        trace_json   = out_dir / (name + "_trace.json")

        stamped_pdf = out_dir / (name + "_STAMPED.pdf")
        try:
            stamp_pdf(verified_pdf, stamped_pdf,
                      stamp_text="AI-verified " + datetime.utcnow().strftime("%Y-%m-%d"),
                      sub_text="California Fruit Inc. AI Sorting Quality Verifier")
            archive_pdf_path = stamped_pdf
        except Exception:
            archive_pdf_path = verified_pdf

        with db_session() as db:
            p = db.get(Packet, packet_id)
            r = db.get(PacketRun, run_id)
            year = packet_year or datetime.utcnow().year
            wo_for_key = (summary.get("work_orders") or "").split(",")[0].strip() or "no-wo"
            cust = summary.get("customer") or "unassigned"
            keys = {
                "verified_pdf": archive_key(cust, year, wo_for_key, packet_id,
                                            name + "_AI_VERIFIED.pdf"),
                "matrix_xlsx":  archive_key(cust, year, wo_for_key, packet_id,
                                            name + "_cross_reference_matrix.xlsx"),
                "issues_csv":   archive_key(cust, year, wo_for_key, packet_id,
                                            name + "_issues.csv"),
                "trace_json":   archive_key(cust, year, wo_for_key, packet_id,
                                            name + "_trace.json"),
            }
            if archive_pdf_path.exists():
                storage().put_path(keys["verified_pdf"], archive_pdf_path,
                                   content_type="application/pdf")
            if matrix_xlsx.exists():
                storage().put_path(keys["matrix_xlsx"], matrix_xlsx,
                                   content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            if issues_csv.exists():
                storage().put_path(keys["issues_csv"], issues_csv,
                                   content_type="text/csv")
            if trace_json.exists():
                storage().put_path(keys["trace_json"], trace_json,
                                   content_type="application/json")

            p.customer_canonical = summary["customer"]
            p.invoice_no = summary["invoice_no"]
            p.work_orders = summary["work_orders"]
            p.n_pages = len(report.pages)
            p.n_sub_packets = len(report.sub_packets)
            p.n_pass = summary["n_pass"]
            p.n_fail = summary["n_fail"]
            p.n_info = summary["n_info"]
            p.status = summary["overall"]
            p.overall_color = "green" if summary["overall"] == "passed" else "orange"
            p.storage_key_verified_pdf = keys["verified_pdf"]
            p.storage_key_matrix_xlsx = keys["matrix_xlsx"]
            p.storage_key_issues_csv = keys["issues_csv"]
            p.storage_key_trace_json = keys["trace_json"]
            p.completed_at = datetime.utcnow()
            p.error_message = None

            n_vision = sum(1 for pg in report.pages
                           if (pg.ocr_backend_used or "") == "vision")
            cost_cents = round(n_vision * SETTINGS.cost_per_page_usd_cents, 4)

            r.status = summary["overall"]
            r.finished_at = datetime.utcnow()
            r.n_pages_processed = len(report.pages)
            r.n_vision_pages = n_vision
            r.cost_usd_cents = cost_cents
            r.trace_json_storage_key = keys["trace_json"]

            db.add(BillingEvent(packet_id=packet_id, n_pages=n_vision,
                                cost_usd_cents=cost_cents))
            details = {
                "status": p.status, "n_pass": p.n_pass,
                "n_fail": p.n_fail, "n_info": p.n_info,
                "duration_s": round(time.time() - started, 2),
                "vision_pages": n_vision,
            }
            db.add(AuditLog(
                user_id=p.uploaded_by_user_id,
                action="verify.complete",
                target_type="packet", target_id=packet_id,
                details_json=details,
            ))
    finally:
        if not str(workdir).endswith(".smoke_cache"):
            shutil.rmtree(workdir, ignore_errors=True)
