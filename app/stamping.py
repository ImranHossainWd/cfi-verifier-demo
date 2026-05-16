"""
PDF stamping — adds the small "Verified by AI on <date> by <user>" badge
to every page of an archived PDF. Uses pypdf (already a project dep via
the verifier engine) plus reportlab to draw the stamp.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Optional


def _build_stamp_overlay(stamp_text: str, sub_text: Optional[str],
                         signature_png: Optional[bytes],
                         page_width_pts: float, page_height_pts: float) -> bytes:
    """Return a single-page PDF with just the stamp graphic."""
    from reportlab.pdfgen import canvas      # type: ignore
    from reportlab.lib.colors import Color
    from reportlab.lib.utils import ImageReader

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(page_width_pts, page_height_pts))

    # Bottom-right corner badge
    pad = 12
    badge_w = 200
    badge_h = 56 if signature_png else 38
    x = page_width_pts - badge_w - pad
    y = pad

    # Soft-burgundy background
    c.setFillColor(Color(0.658, 0.133, 0.215, alpha=0.85))   # #a82237 @ 85%
    c.roundRect(x, y, badge_w, badge_h, 6, fill=1, stroke=0)

    c.setFillColor(Color(1, 1, 1))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x + 10, y + badge_h - 16, stamp_text)
    if sub_text:
        c.setFont("Helvetica", 7)
        c.drawString(x + 10, y + badge_h - 28, sub_text[:40])

    # Optional signature PNG (drawn small, top-right of badge)
    if signature_png:
        try:
            img = ImageReader(io.BytesIO(signature_png))
            c.drawImage(img, x + badge_w - 60, y + 4, width=54, height=18,
                        mask="auto", preserveAspectRatio=True)
        except Exception:
            pass

    c.showPage(); c.save()
    return buf.getvalue()


def stamp_pdf(input_pdf: Path, output_pdf: Path, *,
              stamp_text: str,
              sub_text: Optional[str] = None,
              signature_png: Optional[bytes] = None) -> Path:
    """
    Overlay the stamp on every page of input_pdf and write to output_pdf.
    """
    from pypdf import PdfReader, PdfWriter   # type: ignore

    reader = PdfReader(str(input_pdf))
    writer = PdfWriter()
    for page in reader.pages:
        # mediabox dims are in PDF points
        w = float(page.mediabox.width)
        h = float(page.mediabox.height)
        overlay_bytes = _build_stamp_overlay(stamp_text, sub_text,
                                              signature_png, w, h)
        overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
        page.merge_page(overlay_reader.pages[0])
        writer.add_page(page)
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf.open("wb") as f:
        writer.write(f)
    return output_pdf


def stamp_signoff(input_pdf: Path, output_pdf: Path, *,
                  user_name: str, signed_at: Optional[datetime] = None,
                  signature_png: Optional[bytes] = None) -> Path:
    """Convenience wrapper for sign-off stamps that include the user."""
    when = signed_at or datetime.utcnow()
    return stamp_pdf(
        input_pdf, output_pdf,
        stamp_text=f"Verified by {user_name}",
        sub_text=f"on {when:%Y-%m-%d %H:%M UTC} via AI Sorting Quality Verifier",
        signature_png=signature_png,
    )
