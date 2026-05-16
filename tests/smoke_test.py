"""End-to-end smoke test against the live FastAPI app.

Uses a stub verifier (loads canned output from engine/runs/pedrick/) so the
test runs in a few seconds. The real verifier is exercised separately via
the engine/src CLI; this test exercises the FastAPI surface around it.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

TEST_ROOT = Path("/tmp/cfi_smoke_run")
if TEST_ROOT.exists():
    shutil.rmtree(TEST_ROOT)
TEST_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["DATABASE_URL"]      = "sqlite:///" + str(TEST_ROOT) + "/cfi_smoke.db"
os.environ["STORAGE_LOCAL_DIR"] = str(TEST_ROOT / "storage")
os.environ["BASE_URL"]          = "http://test.local"
os.environ["AUTH_PROVIDER"]     = "dev"
os.environ["VISION_PROVIDER"]   = "mock"
os.environ["STRIPE_ENABLED"]    = "false"

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine" / "src"))

# Stub the heavy verifier with one that copies pre-baked engine outputs into storage.
from app import verifier_runner as VR
from datetime import datetime
from app.db import db_session
from app.models import AuditLog, BillingEvent, Packet, PacketRun
from app.storage import archive_key, storage as storage_fn
from app.config import SETTINGS

PEDRICK_RUNS = ROOT / "engine" / "runs" / "pedrick"


def stub_run_packet_verification(packet_id):
    started = time.time()
    with db_session() as db:
        p = db.get(Packet, packet_id)
        if p is None:
            return
        p.status = "running"
        run = PacketRun(packet_id=packet_id, status="running", vision_provider="mock")
        db.add(run); db.commit(); db.refresh(run)
        run_id = run.id
        packet_year = p.year

    trace = json.loads((PEDRICK_RUNS / "pedrick_trace.json").read_text())
    n_pass = sum(1 for c in (
        [c for sp in trace["sub_packets"] for c in sp["checks"]] +
        trace["packet_level_checks"]) if c["status"] == "pass")
    n_fail = sum(1 for c in (
        [c for sp in trace["sub_packets"] for c in sp["checks"]] +
        trace["packet_level_checks"]) if c["status"] == "fail")
    n_info = sum(1 for c in (
        [c for sp in trace["sub_packets"] for c in sp["checks"]] +
        trace["packet_level_checks"]) if c["status"] == "info")
    customer = "Pedrick Produce"
    work_orders = "11592"
    invoice_no = "INV004584"

    name = "pedrick"
    year = packet_year or datetime.utcnow().year
    keys = {
        "verified_pdf": archive_key(customer, year, work_orders, packet_id, name + "_AI_VERIFIED.pdf"),
        "matrix_xlsx":  archive_key(customer, year, work_orders, packet_id, name + "_cross_reference_matrix.xlsx"),
        "issues_csv":   archive_key(customer, year, work_orders, packet_id, name + "_issues.csv"),
        "trace_json":   archive_key(customer, year, work_orders, packet_id, name + "_trace.json"),
    }
    src = {
        "verified_pdf": PEDRICK_RUNS / "pedrick_AI_VERIFIED.pdf",
        "matrix_xlsx":  PEDRICK_RUNS / "pedrick_cross_reference_matrix.xlsx",
        "issues_csv":   PEDRICK_RUNS / "pedrick_issues.csv",
        "trace_json":   PEDRICK_RUNS / "pedrick_trace.json",
    }
    for k, key in keys.items():
        if src[k].exists():
            storage_fn().put_path(key, src[k])

    with db_session() as db:
        p = db.get(Packet, packet_id)
        r = db.get(PacketRun, run_id)
        p.customer_canonical = customer
        p.invoice_no = invoice_no
        p.work_orders = work_orders
        p.n_pages = len(trace["pages"])
        p.n_sub_packets = len(trace["sub_packets"])
        p.n_pass = n_pass; p.n_fail = n_fail; p.n_info = n_info
        p.status = "passed" if n_fail == 0 else "failed"
        p.overall_color = "green" if n_fail == 0 else "orange"
        p.storage_key_verified_pdf = keys["verified_pdf"]
        p.storage_key_matrix_xlsx = keys["matrix_xlsx"]
        p.storage_key_issues_csv = keys["issues_csv"]
        p.storage_key_trace_json = keys["trace_json"]
        p.completed_at = datetime.utcnow()
        r.status = p.status
        r.finished_at = datetime.utcnow()
        r.n_pages_processed = p.n_pages
        r.n_vision_pages = 13
        r.cost_usd_cents = 13 * SETTINGS.cost_per_page_usd_cents
        r.trace_json_storage_key = keys["trace_json"]
        db.add(BillingEvent(packet_id=packet_id, n_pages=13,
                            cost_usd_cents=r.cost_usd_cents))
        db.add(AuditLog(action="verify.complete", target_type="packet",
                        target_id=packet_id,
                        details_json={"status": p.status, "n_pass": n_pass,
                                      "n_fail": n_fail, "n_info": n_info,
                                      "duration_s": round(time.time() - started, 2),
                                      "vision_pages": 13}))


VR.run_packet_verification = stub_run_packet_verification

# Also patch the import inside app.main so the BackgroundTask uses the stub
import app.main as APP_MAIN
APP_MAIN.run_packet_verification = stub_run_packet_verification

from fastapi.testclient import TestClient
from app.main import app

PEDRICK_PDF = Path("/sessions/confident-upbeat-curie/mnt/Cal Fruits/_handoff_extracted/Pedrick Produce Inv.#4584.pdf")


def banner(s):
    print()
    print("=" * 72)
    print("  " + s)
    print("=" * 72)


def main():
    banner("Smoke test - FastAPI verifier app, end-to-end (stubbed verifier)")
    with TestClient(app) as client:
        _run(client)


def _run(client):
    r = client.get("/healthz")
    print("[1] GET  /healthz                          -> " + str(r.status_code) + "  " + str(r.json()))
    assert r.status_code == 200

    r = client.get("/api/me")
    me = r.json()
    print("[2] GET  /api/me                           -> " + str(r.status_code) + "  " + me["email"] + " (role=" + me["role"] + ")")
    assert r.status_code == 200

    r = client.get("/api/packets")
    print("[3] GET  /api/packets   (initially empty)  -> " + str(r.status_code) + "  count=" + str(len(r.json())))
    assert r.status_code == 200 and r.json() == []

    print("[4] POST /api/packets   uploading " + PEDRICK_PDF.name + " (" + str(PEDRICK_PDF.stat().st_size // 1024) + " KB)...")
    with PEDRICK_PDF.open("rb") as f:
        r = client.post("/api/packets",
            files={"pdf": (PEDRICK_PDF.name, f, "application/pdf")},
            data={"display_name": "pedrick"})
    p = r.json()
    print("     -> " + str(r.status_code) + "  packet_id=" + p["id"][:8] + "...  status=" + p["status"])
    packet_id = p["id"]
    assert r.status_code == 202

    # poll
    deadline = time.time() + 30
    while time.time() < deadline:
        p = client.get("/api/packets/" + packet_id).json()
        if p["status"] in ("passed", "failed", "error"):
            break
        time.sleep(0.5)
    print("[5] verification finished                   status=" + p["status"] + "  pass=" + str(p["n_pass"]) + "  fail=" + str(p["n_fail"]) + "  info=" + str(p["n_info"]))
    print("     customer=" + str(p["customer_canonical"]) + "  WO=" + str(p["work_orders"]) + "  invoice=" + str(p["invoice_no"]))
    if p["status"] == "error":
        print("     ERROR: " + str(p.get("error_message")))
    assert p["status"] == "failed", "expected 'failed' (Pedrick has 2 known flags), got " + p["status"]

    r = client.get("/api/packets/" + packet_id + "/trace")
    trace = r.json()
    fails = [c for sp in trace["sub_packets"] for c in sp["checks"] if c["status"] == "fail"]
    fails += [c for c in trace["packet_level_checks"] if c["status"] == "fail"]
    print("[6] GET  /api/packets/{id}/trace           -> " + str(r.status_code) + "  " + str(len(trace["pages"])) + " pages, " + str(len(fails)) + " fail checks:")
    for c in fails:
        print("       X  " + c["name"] + ": " + c["detail"][:100])
    expected_flags = ["Sulfur spec on p6", "Sulfur ppm cross-page [WO 11592]"]
    found = [c["name"] for c in fails]
    for ef in expected_flags:
        assert ef in found, "missing expected flag: " + repr(ef)
    print("     OK both expected Pedrick flags present")

    r = client.post("/api/packets/" + packet_id + "/overrides",
        json={"page_no": 13, "field_key": "sulfur_ppm", "new_value": "3126",
              "rationale": "smoke test correction"})
    print("[7] POST /api/packets/{id}/overrides       -> " + str(r.status_code) + "  saved override")
    assert r.status_code == 201
    time.sleep(1)

    import io as _io
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (400, 120), (255, 255, 255, 0))
    d = ImageDraw.Draw(img)
    d.line([(20, 80), (60, 30), (110, 90), (160, 40), (220, 80), (280, 50), (350, 75)], fill="black", width=3)
    buf = _io.BytesIO(); img.save(buf, format="PNG"); sig_bytes = buf.getvalue()

    r = client.put("/api/me/signature",
                   files={"signature": ("vicky_sig.png", sig_bytes, "image/png")})
    print("[8] PUT  /api/me/signature                  -> " + str(r.status_code) + "  has_signature=" + str(r.json()["has_signature"]))

    r = client.post("/api/packets/" + packet_id + "/signoff",
                    json={"notes": "smoke test sign-off", "use_stored_signature": True})
    out = r.json()
    print("[9] POST /api/packets/{id}/signoff         -> " + str(r.status_code))
    print("     archived: " + str(out.get("archived_pdf_url")))
    assert r.status_code == 200

    r = client.get("/api/customers")
    cs = r.json()
    print("[10] GET /api/customers                     -> " + str(r.status_code) + "  customers with packets:")
    for c in cs:
        print("       " + c["canonical_name"] + ": " + str(c["n_packets"]) + " packet(s), " + str(c["n_passed"]) + " passed, " + str(c["n_failed"]) + " failed")

    r = client.get("/api/audit_log?limit=20")
    audit = r.json()
    print("[11] GET /api/audit_log                     -> " + str(r.status_code) + "  " + str(len(audit)) + " events:")
    for ev in audit[:8]:
        print("       " + ev["at"][:19] + "  " + str(ev["user_email"] or "")[:25] + "  " + ev["action"])

    banner("OK - Smoke test passed")
    print("  Packet ID:           " + packet_id)
    print("  Status:              " + p["status"])
    print("  Pass / Fail / Info:  " + str(p["n_pass"]) + " / " + str(p["n_fail"]) + " / " + str(p["n_info"]))
    key = (p.get("storage_url_verified_pdf") or "?").split("/storage/")[-1]
    print("  Verified PDF key:    " + key)


if __name__ == "__main__":
    main()
