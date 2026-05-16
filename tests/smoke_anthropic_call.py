"""Smoke test: prove the Anthropic vision backend really calls the API.

Run:
    set ANTHROPIC_API_KEY=sk-ant-api03-...
    python tests/smoke_anthropic_call.py

Expected: a JSON response printed to stdout, and one entry visible in your
Anthropic console under Usage.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine" / "src"))

from PIL import Image, ImageDraw  # type: ignore

from ocr_backend import AnthropicVisionBackend  # type: ignore


def make_test_image(path: Path) -> None:
    img = Image.new("RGB", (900, 500), "white")
    d = ImageDraw.Draw(img)
    lines = [
        "California Fruit Inc. - Sorting Quality Report",
        "WO# 11592",
        "Customer: Pedrick Produce",
        "Product: PEACHES-DICED-SINGLE",
        "Sulfur ppm: 3458",
        "Moisture %: 18.2",
        "Inspected by: VM   Date: 06/14/2026",
    ]
    for i, line in enumerate(lines):
        d.text((40, 40 + i * 50), line, fill="black")
    img.save(path)


def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY env var is not set.", file=sys.stderr)
        return 2

    img_path = HERE / "_smoke_test_page.png"
    make_test_image(img_path)

    backend = AnthropicVisionBackend()
    print(f"Calling Anthropic API ({backend.model}) with {img_path.name}...")
    result = backend.extract(str(img_path))

    print("--- API RESPONSE ---")
    for key in ("backend", "form_type_guess", "wo_numbers",
                "customer_name", "product_description",
                "sulfur_ppm", "moisture_pct", "initials_present"):
        print(f"  {key}: {result.get(key)!r}")
    print(f"  raw_text (first 200): {(result.get('raw_text') or '')[:200]!r}")
    print("OK - if you see real values above, the API call worked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
