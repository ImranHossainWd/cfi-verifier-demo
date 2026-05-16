"""
Build fillable-PDF versions of California Fruit's three priority handwritten
forms:

  1. Extra-Case Sorting Quality Report   (highest priority — touched on every
                                          extra-case order)
  2. Loose Metal Detector Findings
  3. Case Metal Detector Findings

Each form has named AcroForm text fields + checkboxes so Vicky (or anyone on
the floor with a tablet) can fill them out directly in any PDF reader, save,
and have the data show up cleanly in the verifier when the packet is uploaded.

Run:
    python forms_blank/generate_fillable_pdfs.py [--out forms_blank/]

The generator uses ReportLab's AcroForm API. Field names are namespaced
('xc_', 'lmd_', 'cmd_') so a downstream PDF parser can pull values out by
name without ambiguity.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


PAGE_W, PAGE_H = LETTER
MARGIN = 0.6 * inch
BRAND = colors.HexColor("#a82237")
SLATE = colors.HexColor("#475569")
LINE = colors.HexColor("#cbd5e1")


def _header(c: canvas.Canvas, title: str, subtitle: str, form_code: str):
    c.setFillColor(BRAND); c.rect(0, PAGE_H - 0.9 * inch, PAGE_W, 0.9 * inch,
                                  stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(MARGIN, PAGE_H - 0.45 * inch, "California Fruit, Inc.")
    c.setFont("Helvetica", 10)
    c.drawString(MARGIN, PAGE_H - 0.66 * inch, subtitle)
    c.setFont("Helvetica-Bold", 13)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.45 * inch, title)
    c.setFont("Helvetica", 8)
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.66 * inch,
                      f"Form code: {form_code} · v2026.05")


def _label(c, x, y, text, w=None):
    c.setFillColor(SLATE); c.setFont("Helvetica-Bold", 8)
    c.drawString(x, y, text.upper())


def _text_field(c, name, x, y, w, h=18, value=""):
    """Draw label background + AcroForm text field at (x, y)."""
    c.setStrokeColor(LINE); c.setFillColor(colors.white)
    c.rect(x, y - h + 2, w, h, stroke=1, fill=1)
    c.acroForm.textfield(
        name=name, x=x, y=y - h + 2, width=w, height=h,
        borderStyle="inset", borderWidth=0,
        fillColor=colors.white, textColor=colors.black,
        forceBorder=False, value=value, fontName="Helvetica", fontSize=10,
    )


def _checkbox(c, name, x, y, label):
    c.acroForm.checkbox(name=name, x=x, y=y, size=12, buttonStyle="check",
                        borderColor=BRAND, fillColor=colors.white,
                        textColor=colors.black, forceBorder=True)
    c.setFillColor(SLATE); c.setFont("Helvetica", 9)
    c.drawString(x + 18, y + 2, label)


def _section(c, x, y, title):
    c.setStrokeColor(BRAND); c.setLineWidth(1.5)
    c.line(x, y, PAGE_W - MARGIN, y)
    c.setFillColor(BRAND); c.setFont("Helvetica-Bold", 10)
    c.drawString(x, y + 4, title.upper())


# ---------------------------------------------------------------------------
# 1. Extra-Case Sorting Quality Report
# ---------------------------------------------------------------------------

def build_extra_case_sqr(out: Path) -> Path:
    c = canvas.Canvas(str(out), pagesize=LETTER)
    _header(c, "Extra-Case Sorting Quality Report",
            "Sanger CA · SQF Edition 9", "SQR_XC")

    y = PAGE_H - 1.3 * inch
    col = MARGIN
    half = (PAGE_W - 2 * MARGIN - 12) / 2

    _label(c, col, y, "Customer");                  _text_field(c, "xc_customer", col, y - 4, half)
    _label(c, col + half + 12, y, "Customer Code"); _text_field(c, "xc_cust_code", col + half + 12, y - 4, half)

    y -= 40
    _label(c, col, y, "WO #");          _text_field(c, "xc_wo", col, y - 4, half / 2 - 6)
    _label(c, col + half / 2 + 6, y, "PO #"); _text_field(c, "xc_po", col + half / 2 + 6, y - 4, half / 2 - 6)
    _label(c, col + half + 12, y, "Original WO #"); _text_field(c, "xc_orig_wo", col + half + 12, y - 4, half / 2 - 6)
    _label(c, col + half + half / 2 + 18, y, "Original Line"); _text_field(c, "xc_orig_line", col + half + half / 2 + 18, y - 4, half / 2 - 6)

    y -= 40
    _label(c, col, y, "Product Description"); _text_field(c, "xc_product", col, y - 4, half * 2 + 12)

    y -= 40
    _label(c, col, y, "Product Code"); _text_field(c, "xc_product_code", col, y - 4, half / 2 - 6)
    _label(c, col + half / 2 + 6, y, "Crop Year"); _text_field(c, "xc_crop_year", col + half / 2 + 6, y - 4, half / 2 - 6)
    _label(c, col + half + 12, y, "Original Crop Years"); _text_field(c, "xc_orig_crop_years", col + half + 12, y - 4, half - 6)

    y -= 40
    _label(c, col, y, "Production Date");     _text_field(c, "xc_prod_date", col, y - 4, half / 2 - 6)
    _label(c, col + half / 2 + 6, y, "Inspection Date"); _text_field(c, "xc_insp_date", col + half / 2 + 6, y - 4, half / 2 - 6)
    _label(c, col + half + 12, y, "Ship Date"); _text_field(c, "xc_ship_date", col + half + 12, y - 4, half - 6)

    # Quantities
    y -= 50
    _section(c, col, y, "Quantities")
    y -= 20
    _label(c, col, y, "Cases");      _text_field(c, "xc_cases", col, y - 4, 80)
    _label(c, col + 100, y, "Lbs / case"); _text_field(c, "xc_lbs_per_case", col + 100, y - 4, 80)
    _label(c, col + 200, y, "Total lbs"); _text_field(c, "xc_total_lbs", col + 200, y - 4, 100)
    _label(c, col + 320, y, "Pallets"); _text_field(c, "xc_pallets", col + 320, y - 4, 80)

    # Lab readings
    y -= 50
    _section(c, col, y, "Lab Readings")
    y -= 20
    _label(c, col, y, "Moisture %");    _text_field(c, "xc_moisture_pct", col, y - 4, 80)
    _label(c, col + 100, y, "Sulfur ppm"); _text_field(c, "xc_sulfur_ppm", col + 100, y - 4, 80)
    _label(c, col + 200, y, "Aflatoxin"); _text_field(c, "xc_aflatoxin", col + 200, y - 4, 100)
    _label(c, col + 320, y, "Defect %"); _text_field(c, "xc_defect_pct", col + 320, y - 4, 80)

    # Sort-out totals
    y -= 50
    _section(c, col, y, "Sort-Out Totals")
    y -= 20
    _label(c, col, y, "Sort-out lbs");      _text_field(c, "xc_sortout_lbs", col, y - 4, 100)
    _label(c, col + 120, y, "Defect bag count"); _text_field(c, "xc_defect_bags", col + 120, y - 4, 80)
    _label(c, col + 220, y, "Notes"); _text_field(c, "xc_sortout_notes", col + 220, y - 4, half * 2 - 80, h=18)

    # Sign-off
    y -= 60
    _section(c, col, y, "Sign-off")
    y -= 22
    _label(c, col, y, "Sorter initials"); _text_field(c, "xc_sorter_initials", col, y - 4, 80)
    _label(c, col + 100, y, "QC initials"); _text_field(c, "xc_qc_initials", col + 100, y - 4, 80)
    _label(c, col + 200, y, "Verification (Vicky)"); _text_field(c, "xc_vicky_initials", col + 200, y - 4, 80)
    _label(c, col + 300, y, "2nd Verification"); _text_field(c, "xc_2nd_initials", col + 300, y - 4, 80)
    _label(c, col + 400, y, "Date"); _text_field(c, "xc_signoff_date", col + 400, y - 4, 100)

    y -= 40
    _checkbox(c, "xc_all_specs_in_range", col, y, "All readings within customer spec")
    _checkbox(c, "xc_initials_complete", col + 220, y, "All required initials present")
    y -= 20
    _checkbox(c, "xc_crossouts_initialed", col, y, "All cross-outs initialed")
    _checkbox(c, "xc_defect_photos_attached", col + 220, y, "Defect bag photos attached for every defect")

    c.setFont("Helvetica", 8); c.setFillColor(SLATE)
    c.drawString(MARGIN, MARGIN - 0.2 * inch,
                 f"Generated {datetime.utcnow():%Y-%m-%d} · California Fruit, Inc.")
    c.showPage(); c.save()
    return out


# ---------------------------------------------------------------------------
# 2. Loose Metal Detector Findings
# ---------------------------------------------------------------------------

def build_loose_metal_detector(out: Path) -> Path:
    c = canvas.Canvas(str(out), pagesize=LETTER)
    _header(c, "Loose Metal Detector Findings",
            "Production floor · daily log", "LMD")
    y = PAGE_H - 1.3 * inch
    col = MARGIN
    half = (PAGE_W - 2 * MARGIN - 12) / 2

    _label(c, col, y, "WO #");           _text_field(c, "lmd_wo", col, y - 4, half)
    _label(c, col + half + 12, y, "Date"); _text_field(c, "lmd_date", col + half + 12, y - 4, half)

    y -= 40
    _label(c, col, y, "Product");        _text_field(c, "lmd_product", col, y - 4, half)
    _label(c, col + half + 12, y, "Operator"); _text_field(c, "lmd_operator", col + half + 12, y - 4, half)

    y -= 40
    _section(c, col, y, "Calibration check")
    y -= 22
    _label(c, col, y, "Ferrous test piece (mm)"); _text_field(c, "lmd_ferrous_mm", col, y - 4, 80)
    _label(c, col + 100, y, "Non-ferrous (mm)"); _text_field(c, "lmd_nonferrous_mm", col + 100, y - 4, 80)
    _label(c, col + 200, y, "SS (mm)"); _text_field(c, "lmd_ss_mm", col + 200, y - 4, 80)
    _label(c, col + 300, y, "Sensitivity setting"); _text_field(c, "lmd_sensitivity", col + 300, y - 4, 100)

    y -= 50
    _section(c, col, y, "Findings")
    y -= 22
    _checkbox(c, "lmd_no_findings", col, y, "NO FINDINGS")
    _checkbox(c, "lmd_findings", col + 130, y, "FINDINGS — describe below")
    y -= 30
    _label(c, col, y, "Description"); _text_field(c, "lmd_findings_desc", col, y - 4, half * 2 + 12)
    y -= 30
    _label(c, col, y, "Action taken"); _text_field(c, "lmd_action", col, y - 4, half * 2 + 12)

    y -= 50
    _section(c, col, y, "Sign-off")
    y -= 22
    _label(c, col, y, "Operator initials"); _text_field(c, "lmd_op_initials", col, y - 4, 80)
    _label(c, col + 100, y, "Supervisor initials"); _text_field(c, "lmd_sup_initials", col + 100, y - 4, 80)
    _label(c, col + 200, y, "Time"); _text_field(c, "lmd_time", col + 200, y - 4, 100)
    _label(c, col + 320, y, "Verification (Vicky)"); _text_field(c, "lmd_vicky_initials", col + 320, y - 4, 100)

    c.setFont("Helvetica", 8); c.setFillColor(SLATE)
    c.drawString(MARGIN, MARGIN - 0.2 * inch,
                 f"Generated {datetime.utcnow():%Y-%m-%d} · California Fruit, Inc.")
    c.showPage(); c.save()
    return out


# ---------------------------------------------------------------------------
# 3. Case Metal Detector Findings
# ---------------------------------------------------------------------------

def build_case_metal_detector(out: Path) -> Path:
    c = canvas.Canvas(str(out), pagesize=LETTER)
    _header(c, "Case Metal Detector Findings",
            "Case-line check · per shift", "CMD")
    y = PAGE_H - 1.3 * inch
    col = MARGIN
    half = (PAGE_W - 2 * MARGIN - 12) / 2

    _label(c, col, y, "WO #");            _text_field(c, "cmd_wo", col, y - 4, half / 2 - 6)
    _label(c, col + half / 2 + 6, y, "PO #"); _text_field(c, "cmd_po", col + half / 2 + 6, y - 4, half / 2 - 6)
    _label(c, col + half + 12, y, "Date"); _text_field(c, "cmd_date", col + half + 12, y - 4, half)

    y -= 40
    _label(c, col, y, "Customer");        _text_field(c, "cmd_customer", col, y - 4, half)
    _label(c, col + half + 12, y, "Product"); _text_field(c, "cmd_product", col + half + 12, y - 4, half)

    y -= 40
    _section(c, col, y, "Calibration check (start of shift)")
    y -= 22
    _label(c, col, y, "Ferrous (mm)"); _text_field(c, "cmd_ferrous_mm", col, y - 4, 80)
    _label(c, col + 100, y, "Non-ferrous (mm)"); _text_field(c, "cmd_nonferrous_mm", col + 100, y - 4, 80)
    _label(c, col + 200, y, "SS (mm)"); _text_field(c, "cmd_ss_mm", col + 200, y - 4, 80)
    _label(c, col + 300, y, "Sensitivity setting"); _text_field(c, "cmd_sensitivity", col + 300, y - 4, 100)
    _label(c, col + 420, y, "Conveyor speed"); _text_field(c, "cmd_conveyor_speed", col + 420, y - 4, 80)

    y -= 50
    _section(c, col, y, "Hourly checks")
    y -= 22
    cols = [40, 110, 180, 250, 320, 390, 460]
    times = ["08:00", "10:00", "12:00", "14:00", "16:00", "18:00", "20:00"]
    for i, t in enumerate(times):
        c.setFont("Helvetica-Bold", 8); c.setFillColor(SLATE)
        c.drawString(col + cols[i], y, t)
        _text_field(c, f"cmd_check_{t.replace(':','')}", col + cols[i], y - 16, 60, h=14)

    y -= 50
    _section(c, col, y, "Findings")
    y -= 22
    _checkbox(c, "cmd_no_findings", col, y, "NO FINDINGS this shift")
    _checkbox(c, "cmd_findings", col + 200, y, "FINDINGS — describe below")
    y -= 30
    _label(c, col, y, "Description / case affected"); _text_field(c, "cmd_findings_desc", col, y - 4, half * 2 + 12)
    y -= 30
    _label(c, col, y, "Disposition (rework / hold / discard)"); _text_field(c, "cmd_disposition", col, y - 4, half * 2 + 12)

    y -= 50
    _section(c, col, y, "Sign-off")
    y -= 22
    _label(c, col, y, "Operator"); _text_field(c, "cmd_op_initials", col, y - 4, 80)
    _label(c, col + 100, y, "Supervisor"); _text_field(c, "cmd_sup_initials", col + 100, y - 4, 80)
    _label(c, col + 200, y, "Verification (Vicky)"); _text_field(c, "cmd_vicky_initials", col + 200, y - 4, 100)
    _label(c, col + 320, y, "Notes"); _text_field(c, "cmd_notes", col + 320, y - 4, half - 50)

    c.setFont("Helvetica", 8); c.setFillColor(SLATE)
    c.drawString(MARGIN, MARGIN - 0.2 * inch,
                 f"Generated {datetime.utcnow():%Y-%m-%d} · California Fruit, Inc.")
    c.showPage(); c.save()
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).parent),
                    help="Output directory (default: forms_blank/)")
    args = ap.parse_args()
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        build_extra_case_sqr(out_dir / "01_extra_case_sqr_FILLABLE.pdf"),
        build_loose_metal_detector(out_dir / "02_loose_metal_detector_FILLABLE.pdf"),
        build_case_metal_detector(out_dir / "03_case_metal_detector_FILLABLE.pdf"),
    ]
    for p in paths:
        print(f"  wrote {p}")


if __name__ == "__main__":
    main()
