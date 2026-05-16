# California Fruit Inc. — AI Sorting Quality Verifier (production app)

Web app wrapper around the proven `engine/` verifier. Turns Vicky's 30-min
manual cross-check into a 30-second AI pass with sign-off, cloud archive,
and audit trail.

## Layout

```
cfi_verifier_app/
├── app/                       FastAPI server (auth, packets, signoff, billing)
│   ├── main.py                Routes
│   ├── verifier_runner.py     Wraps engine.verifier.verify_pdf for background jobs
│   ├── auth.py                Clerk / Supabase / dev-mode JWT verification
│   ├── storage.py             Local / S3 / R2 storage adapter
│   ├── stamping.py            "Verified by AI on <date>" PDF stamp
│   ├── billing.py             Stripe pass-through billing
│   ├── models.py              SQLAlchemy ORM
│   ├── db.py                  DB session
│   ├── schemas.py             Pydantic request/response shapes
│   └── config.py              Env-driven settings
├── engine/                    UNCHANGED verifier engine from the handoff
│   ├── src/verifier.py        + src/arithmetic_rules.py (NEW)
│   ├── config/*.yaml
│   └── runs/                  Cached sample outputs
├── web/                       Single-page dashboard (vanilla JS, mobile-first)
│   ├── index.html
│   └── static/{app.js,app.css,california_fruit_logo.svg}
├── forms_blank/               Fillable PDFs for the three priority forms
│   ├── 01_extra_case_sqr_FILLABLE.pdf
│   ├── 02_loose_metal_detector_FILLABLE.pdf
│   ├── 03_case_metal_detector_FILLABLE.pdf
│   └── generate_fillable_pdfs.py     (regenerable from source)
├── infra/
│   ├── Dockerfile
│   ├── railway.toml
│   └── render.yaml
├── requirements.txt
├── .env.example
└── RUNBOOK.md                 Step-by-step deploy guide (start here)
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
# Open http://localhost:8000
```

The default config uses SQLite + local file storage + the mock vision cache,
so you can drag the bundled Pedrick sample PDF onto the upload zone and watch
the verifier run end-to-end with no cloud accounts.

## Going to production

See **RUNBOOK.md** — every account creation step, every env var, every gotcha.

## What changed vs the handoff verifier

- **`engine/src/arithmetic_rules.py`** — new module implementing the two
  rules called out in the handoff but not yet built:
  - Pull Ticket allocation sum = Total Quantity per WO
  - Sum of Extra Cases USED case counts = new WO's case count
- **`engine/src/verifier.py`** — patched in 3 lines: import the new module
  and call `run_arithmetic_rules` at the end of `run_subpacket_checks`.
- **`engine/config/rules.yaml`** — added two rule toggles for the above.

The verifier engine is otherwise byte-for-byte identical to what shipped in
the handoff. The 4 sample runs (`engine/runs/`) reproduce exactly.

## Verified end-to-end

Re-running the Pedrick sample through the engine after the arithmetic-rule
addition produces the two known flags exactly as the handoff specified, plus
4 new arithmetic-rule check messages (info-level — OCR couldn't read all the
case-count fields, which is expected behavior and not a regression):

```
Sulfur spec on p6: 3458 ppm outside spec [1500, 3000]
Sulfur ppm cross-page [WO 11592]: 3136.0 on pages [13] disagrees with 3126.0 on pages [5]
```
