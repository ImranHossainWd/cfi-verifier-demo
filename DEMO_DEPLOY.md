# Demo Deploy - Render free tier (no auth, no Stripe)

Goal: get the verifier dashboard live on a public URL in about 30 minutes
so you can scan packets, upload them, and watch the AI surface flags.

## What you need

- A free GitHub account (sign up at https://github.com if you do not have one)
- A free Render account (https://render.com - sign in with GitHub one click)
- Your Anthropic API key from https://console.anthropic.com (one is already
  generated - hold on to it, you will paste it into Render in step 8)

That is it. No credit card on Render free tier. Anthropic took your card for
the API key but you have a hard cap so it cannot exceed your set budget.

---

## Step 1 - Create a new GitHub repository

1. Go to https://github.com/new while signed in.
2. Repository name: `cfi-verifier-demo`
3. Description: anything, e.g. "California Fruit Inc verifier demo"
4. Set it to **Private** (only you can see it - safer for a work project)
5. Do NOT tick "Add a README file" - we are uploading our own
6. Click **Create repository**

You will land on an empty repo page with instructions. Ignore those.

## Step 2 - Upload the code

On the empty repo page, look for the link **"uploading an existing file"**
(it is mid-page, in the "or quick setup" block). Click it.

Now drag the **entire contents** of the `cfi_verifier_demo_bundle/` folder
into the upload zone:

  - app/             (folder)
  - engine/          (folder)
  - forms_blank/     (folder)
  - infra/           (folder)
  - tests/           (folder)
  - web/             (folder)
  - .env.example
  - .gitignore
  - README.md
  - RUNBOOK.md
  - requirements.txt

GitHub will show all 49 files queued. At the bottom:

  - Commit message: `initial commit`
  - Click **Commit changes**

Wait ~30 seconds for the upload. The repo now has all the code.

## Step 3 - Sign up for Render

1. Go to https://render.com
2. Click **Get Started** -> **Sign in with GitHub**
3. Authorize Render to read your repos

## Step 4 - Create a new Blueprint deploy

Render reads the `infra/render.yaml` we put in the repo and provisions
everything automatically.

1. In Render dashboard, click **New +** (top right) -> **Blueprint**
2. **Connect a repository** -> find `cfi-verifier-demo` -> click **Connect**
3. Render reads `infra/render.yaml` and shows: 1 web service to be created.
4. Blueprint name: `cfi-verifier-demo` (default is fine)
5. Click **Apply**

Render starts the build. Click into the service to watch progress.

## Step 5 - Wait for the first build

The first build takes **8-12 minutes** because Docker is downloading
Tesseract, Poppler, Python, and all the dependencies. You will see logs
streaming. Watch for the line `Uvicorn running on http://0.0.0.0:...`
That means the service is up.

If the build fails, copy the last ~50 lines of the log and paste them back
to me - usually a one-line fix.

## Step 6 - Add your Anthropic API key

The deployed service is running but vision OCR will fail without your key.

1. In the Render dashboard, click your `cfi-verifier-demo` service.
2. Left sidebar -> **Environment**
3. Click **Add Environment Variable**:
     - Key:   `ANTHROPIC_API_KEY`
     - Value: paste your Anthropic key (starts with `sk-ant-api03-...`)
4. Click **Save Changes**

Render will redeploy automatically (~1 minute) with the key in place.

## Step 7 - Get your URL

In the Render service overview, top of the page, look for the URL like:
`https://cfi-verifier-demo.onrender.com`

This is your live dashboard. Open it in a browser. You should see the
California Fruit header with the burgundy banner and a `Recent packets`
tab showing "No packets yet."

## Step 8 - Test it

Scan a packet on the office scanner (200-300 DPI, color or grayscale,
single PDF). Then on the dashboard:

1. Click the **Upload** tab.
2. Drag the PDF onto the dropzone, or click and select.
3. Optional: type a display name like "Test packet 1"
4. Click **Verify**.

The packet enters `queued` -> `running` status. Wait 60-120 seconds
(printed-text OCR + handwriting OCR). The status flips to `passed` or
`failed`. Click into the packet card to see:

- Cross-reference matrix (every field across every page)
- Check list (each cross-reference, with pass/fail status)
- Pages list (clickable, with backup-source pages dimmed)
- Download links for the verified PDF and the Excel matrix

For a real California Fruit packet you should see a few flags surface -
math errors, missing initials, sulfur readings out of spec, etc. The
exact flags depend on what the original paperwork has wrong.

## Important caveats for free tier

- **Spin-down after 15 min idle.** First click after idle waits ~30 seconds
  for cold start. Subsequent clicks are instant.
- **Data is ephemeral.** Render free tier has no persistent disk. If the
  service restarts (deploy or crash), uploaded packets are lost. For demo
  this is fine; for production you upgrade to Render Standard ($7/mo)
  with a 1GB disk, or you wire up S3/R2 storage.
- **Anyone with the URL can use it.** No login. Do not share the URL on
  public channels until auth is wired up.
- **Memory cap 512 MB.** Very large packets (>50 pages or >50 MB) may run
  out of memory. The Pedrick test packet (12 MB, 27 pages) fits comfortably.

## When you have tested enough

Come back and we will:
- Add login (Clerk or Supabase)
- Add S3/R2 storage so data survives restarts
- Wire Stripe pass-through billing
- Move to a paid plan (~$7/mo) so the URL never spins down
