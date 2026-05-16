# Production Deployment Runbook
California Fruit, Inc. — AI Sorting Quality Verifier

This runbook walks you through every account creation and config step needed
to take this repo from a folder on your laptop to a live, multi-user web app
serving Vicky and her shipping coordinator. Target: production-ready a few
weeks ahead of the SQF audit window opening July 2026.

---

## What you're deploying

A FastAPI web app that wraps the proven `engine/` verifier and adds:

- Multi-user login (Clerk or Supabase Auth)
- Per-user digital signatures
- Edit-and-propagate corrections (Vicky fixes one cell, AI re-checks every related page)
- Cloud-folder auto-archive (S3 or Cloudflare R2)
- Customer-index dashboard view
- Per-packet rescan
- Mobile/tablet-friendly UI for floor verification
- Stripe pass-through billing of Anthropic vision OCR (~$0.04/packet, no markup)
- Append-only audit log for SQF compliance

Total monthly cost target: **$80–230/customer** depending on packet volume.

---

## 0. Local smoke test (15 min)

Verify it runs on your laptop before touching the cloud.

```bash
cd cfi_verifier_app
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env             # defaults are fine for dev
uvicorn app.main:app --reload
```

Open http://localhost:8000/. You should see the dashboard. Drag a sample
packet PDF (e.g. `_handoff_extracted/Pedrick Produce Inv.#4584.pdf`) onto the
upload zone. After ~60 seconds the packet appears with 2 flags (matching the
known Pedrick flags — sulfur spec on Nectarine COA + sulfur transcription
error on WO 11592). Click into the packet to see the matrix and check details.

---

## 1. Pick your auth provider — Clerk or Supabase (15 min)

Both work. Clerk is more polished for the user-facing flows; Supabase bundles
the database too if you want one fewer vendor.

### Option A — Clerk (recommended for non-technical end users)

1. Sign up at https://clerk.com (free tier covers <10k MAU).
2. **Create application** → name it "California Fruit Verifier".
3. Sign-in methods: enable **Email + password** (Vicky's preference) and disable social logins.
4. Settings → API Keys: copy the **Publishable Key** and **Secret Key**.
5. Settings → JWT Templates: leave the default; the verifier validates against the JWKS endpoint.
6. Set these env vars in your hosting provider:
   ```
   AUTH_PROVIDER=clerk
   CLERK_SECRET_KEY=sk_live_...
   CLERK_JWKS_URL=https://<your-clerk-frontend>.clerk.accounts.dev/.well-known/jwks.json
   ```
7. Pre-create the two users (Settings → Users → Add user):
   - Vicky: `vicky@californiafruit.com`, role `admin`
   - Shipping coordinator: their email, role `verifier`
   (Roles are set in the Verifier dashboard once each user signs in once.)

### Option B — Supabase (one vendor for auth + db)

1. Sign up at https://supabase.com.
2. Create project "cfi-verifier-prod".
3. Settings → API: copy `Project URL`, `anon` key, `service_role` key, and `JWT Secret`.
4. Set env vars:
   ```
   AUTH_PROVIDER=supabase
   SUPABASE_URL=https://...supabase.co
   SUPABASE_ANON_KEY=...
   SUPABASE_SERVICE_ROLE_KEY=...
   SUPABASE_JWT_SECRET=...     # the HS256 secret under Settings → API
   ```
5. In Supabase, Authentication → Users → invite Vicky and the shipping coordinator.

---

## 2. Provision storage (10 min)

You can pick S3 or Cloudflare R2 (cheaper, no egress fees, S3-compatible API).

### Option A — Cloudflare R2 (recommended)

1. Sign up at https://cloudflare.com.
2. R2 → Create bucket: `cfi-verifier-prod`.
3. R2 → Manage API Tokens: create a token with R2 Read+Write on this bucket.
4. Set env vars:
   ```
   STORAGE_BACKEND=r2
   S3_BUCKET=cfi-verifier-prod
   S3_REGION=auto
   S3_ENDPOINT_URL=https://<accountid>.r2.cloudflarestorage.com
   S3_ACCESS_KEY_ID=<token-id>
   S3_SECRET_ACCESS_KEY=<token-secret>
   ```

### Option B — AWS S3

1. Console → S3 → Create bucket `cfi-verifier-prod`, block public access.
2. IAM → Create user `cfi-verifier-app` with policy granting Get/Put/Delete on the bucket.
3. Set env vars:
   ```
   STORAGE_BACKEND=s3
   S3_BUCKET=cfi-verifier-prod
   S3_REGION=us-west-2
   S3_ACCESS_KEY_ID=AKIA...
   S3_SECRET_ACCESS_KEY=...
   ```

### Optional — auto-mirror to Adobe Document Cloud

If California Fruit wants verified PDFs to land in their existing Adobe folder:

1. Adobe Developer Console → create credentials for `documentcloud_api`.
2. Set:
   ```
   ADOBE_CLOUD_ENABLED=true
   ADOBE_CLIENT_ID=...
   ADOBE_CLIENT_SECRET=...
   ```
3. The verifier already writes to S3/R2; the Adobe sync is a separate worker
   (left as a stub in `app/storage.py` — implement if/when needed). The
   primary archive lives in S3/R2 either way.

---

## 3. Get an Anthropic API key (5 min)

The vision OCR is what reads handwriting. Without this, the verifier falls
back to Tesseract for everything (printed text only).

1. Sign up at https://console.anthropic.com.
2. Settings → Billing → add a card. Set a low monthly hard cap ($25 covers
   typical usage; California Fruit averages ~$0.04/packet).
3. Settings → API keys → create key "cfi-verifier-prod".
4. Set env vars:
   ```
   VISION_PROVIDER=anthropic
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
   ```

---

## 4. Provision Postgres (10 min)

The dev SQLite database is fine for one user on one server. Production wants
Postgres so multiple workers can talk to one DB.

### If you're deploying on Railway

Add the **Postgres** service in your Railway project. Railway auto-injects
`DATABASE_URL` — no further config needed.

### If you're deploying on Render

Use the `infra/render.yaml` blueprint — it provisions a `cfi-verifier-db`
Postgres add-on and wires `DATABASE_URL` to the web service.

### Other options

- **Neon** (serverless Postgres) — $0/month free tier covers Vicky's volume.
- **Supabase Postgres** — comes with the auth setup if you chose Option B above.

Set:
```
DATABASE_URL=postgresql+psycopg://user:pass@host:5432/cfi
```

---

## 5. Set up Stripe pass-through billing (15 min)

We bill California Fruit at cost (~$0.04 per verified packet) with no markup.
Vicky's card on file gets charged monthly via metered usage.

1. Sign up at https://stripe.com → activate the account with business details.
2. Products → New: "AI Sorting Quality Verification" → metered price, $0.01 per unit
   (1 unit = 1¢ of OCR cost). Recurring monthly. Save the price ID.
3. Customers → Add California Fruit's customer with their card on file.
4. Subscriptions → Create subscription for that customer using the metered price.
   Note the **subscription_item_id** — you'll need it.
5. Developers → API keys: copy the **Secret Key** and create a webhook for
   `invoice.paid` events. Copy the webhook signing secret.
6. Set env vars:
   ```
   STRIPE_ENABLED=true
   STRIPE_SECRET_KEY=sk_live_...
   STRIPE_WEBHOOK_SECRET=whsec_...
   STRIPE_PRICE_ID_PER_PACKET=price_...
   COST_PER_PAGE_USD_CENTS=0.3
   ```
7. Update `app/billing.py` so each `BillingEvent` calls `report_usage` with
   California Fruit's `subscription_item_id` (currently passed as a parameter
   — store it on the `Customer` model for multi-tenant deploys).

If you want to soft-launch without billing, leave `STRIPE_ENABLED=false`.
The verifier will still log every cost event in the audit log so you can
backfill once Stripe is live.

---

## 6. Deploy the web app — Railway (recommended) or Render

### Railway path (~10 min)

```bash
# One-time:
brew install railway      # or npm install -g @railway/cli
railway login
railway init              # in the cfi_verifier_app/ folder
railway link
# Add Postgres add-on in the Railway dashboard, then:
railway up                # builds Dockerfile, deploys
```

In the Railway dashboard for the web service, add every env var from
`.env.example` (filled in with your real values from steps 1–5). Set
`STORAGE_BACKEND`, `AUTH_PROVIDER`, `VISION_PROVIDER` to their production
values (not "local"/"dev"/"mock").

### Render path

1. Push the repo to GitHub.
2. Render Dashboard → New + → Blueprint → connect the repo.
3. Render reads `infra/render.yaml`, provisions the Postgres add-on, and
   builds from `infra/Dockerfile`.
4. Add the remaining env vars (Clerk, S3, Anthropic, Stripe) in the Render
   Environment tab.

### Verify the deployment

Visit `<your-domain>/healthz`. You should see:
```json
{"ok": true, "version": "1.0.0", "env": "prod",
 "auth_provider": "clerk", "vision_provider": "anthropic",
 "storage_backend": "r2"}
```

---

## 7. First user setup — Vicky's signature

1. Vicky signs in at `<your-domain>/`.
2. Top-right → ✎ signature → draws her signature on the canvas → Save.
3. Repeat for the shipping coordinator.

Now every packet they sign off on gets stamped with the badge:

> **Verified by Vicky Melkonian**
> on 2026-06-15 18:42 UTC via AI Sorting Quality Verifier

The badge appears in the bottom-right corner of every page of the archived PDF.

---

## 8. End-to-end smoke test against the Pedrick sample

```
1. Sign in as Vicky.
2. Upload tab → drag "Pedrick Produce Inv.#4584.pdf".
3. Wait ~60-90 seconds. Status pill goes queued → running → failed
   (failed = "found flags" — that's what we want for this test packet).
4. Click into the detail view. Confirm:
   - 2 fails surfaced:
     · "Sulfur spec on p6" (Nectarine COA, 3458 > 3000 ppm)
     · "Sulfur ppm cross-page [WO 11592]" (3136 vs 3126)
   - Cross-reference matrix renders.
   - Pages list shows 27 pages.
5. Click any matrix cell → edit modal opens → save a correction.
   Status flips back to queued, then re-runs in ~10 seconds.
6. Sign-off: textarea → "tested deployment" → Sign off & archive.
   The archived PDF link opens with the verification stamp on every page.
7. Check the cloud archive — the file should be at
   customers/pedrick-produce/2026/11592/<packet-id>/<name>_ARCHIVED.pdf.
```

---

## 9. Going live — Vicky-side rollout

Train sequence (about an hour):

1. Walk Vicky through her first real packet using a tablet on the floor.
2. Show the edit-and-propagate flow on a packet she'd normally pen-mark.
3. Show the customer-index view — confirm her mental model lines up.
4. Show where the cloud archive lives (R2 / S3 console — read-only access).
5. Give the shipping coordinator a tablet with the same training.
6. Switch the audit binders policy: "verified by AI + signed off in app =
   the source of truth." The pen-marked binders become a backup-only
   workflow until the next SQF audit confirms the AI version is acceptable
   to the auditor.

---

## 10. Operations & monitoring

- **Logs:** Railway/Render both stream logs by default. Tail them during the
  first week of real packets.
- **DB backups:** Railway/Render Postgres add-ons take daily snapshots.
- **Cost watch:** check Anthropic console weekly for the first month — typical
  packet should be $0.03–$0.05. If you see $0.10+ packets, investigate (it's
  usually a high-page-count Balcorp-style order).
- **Stripe:** invoices auto-finalize on the 1st of the month. Email Vicky a
  copy when she's ready to receive them.
- **Audit log:** export `/api/audit_log` to CSV monthly and file with the
  SQF Document Register. The auditor will love it.

---

## What's NOT in this runbook (do these later)

- Multi-tenant: today this is one-customer. To onboard a second processor,
  add a `Tenant` model and scope every query by tenant_id.
- RQ/Celery worker split: in-process BackgroundTasks works for ≤20
  packets/day. Above that, set `JOB_RUNNER=rq` and run a separate worker
  process pointing at the same Postgres + Redis.
- Adobe Document Cloud auto-sync (stub in storage.py).
- Mobile native app (the web UI is already touch-friendly; a wrapped
  Capacitor/Expo build is a one-day job if Vicky asks).
- SQF Edition 9 → 10 clause migration mapping (Project 3 territory).

---

**Questions while deploying?** The handoff doc (HANDOFF_to_new_Claude.md)
has the full project history. Yusuf is on Slack/text per the original brief.
