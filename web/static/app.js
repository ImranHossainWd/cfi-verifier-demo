/* California Fruit verifier — single-file vanilla JS dashboard.
   No build step. Talks to /api/* endpoints. Mobile-first. */

const $  = (q, root = document) => root.querySelector(q);
const $$ = (q, root = document) => Array.from(root.querySelectorAll(q));

let TOKEN = null;
let CURRENT_USER = null;
let CURRENT_PACKET = null;       // currently-open detail
let LIVE_TRACE = null;           // currently-open packet's trace JSON

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

async function loadToken() {
  // For Clerk / Supabase the token is fetched from their JS SDK client-side.
  // For dev mode we don't need a token. Read from localStorage if present.
  TOKEN = localStorage.getItem("cfi_token");
}

function authHeaders() {
  return TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {};
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...(opts.headers || {}) },
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`${r.status} ${r.statusText} — ${text}`);
  }
  if (r.status === 204) return null;
  return r.json();
}

async function apiUpload(path, formData) {
  const r = await fetch(path, { method: "POST", body: formData, headers: authHeaders() });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function loadMe() {
  CURRENT_USER = await api("/api/me");
  const chip = $("#user-chip");
  chip.hidden = false;
  $(".user-name", chip).textContent = CURRENT_USER.full_name || CURRENT_USER.email;
  if (CURRENT_USER.role === "admin") document.body.classList.add("is-admin");
}

// ---------------------------------------------------------------------------
// View routing
// ---------------------------------------------------------------------------

function showView(name) {
  $$(".view").forEach(v => { v.classList.toggle("active", v.id === `view-${name}`); v.hidden = v.id !== `view-${name}`; });
  $$(".tab").forEach(t => t.classList.toggle("active", t.dataset.view === name));
  if (name === "recent") loadPackets();
  if (name === "customers") loadCustomers();
  if (name === "audit") loadAuditLog();
}

$$(".tab").forEach(t => t.addEventListener("click", () => showView(t.dataset.view)));

// ---------------------------------------------------------------------------
// Recent packets
// ---------------------------------------------------------------------------

async function loadPackets() {
  const grid = $("#packet-grid");
  grid.innerHTML = `<div class="empty-state">Loading…</div>`;
  try {
    const packets = await api("/api/packets?limit=200");
    renderKpis(packets);
    renderPacketGrid(packets);
  } catch (e) {
    grid.innerHTML = `<div class="empty-state">Couldn't load packets — ${e.message}</div>`;
  }
}

function renderKpis(packets) {
  const totalPass = packets.reduce((a, p) => a + (p.n_pass || 0), 0);
  const totalFail = packets.reduce((a, p) => a + (p.n_fail || 0), 0);
  $("#kpi-packets").textContent = packets.length;
  $("#kpi-pass").textContent = totalPass.toLocaleString();
  $("#kpi-fail").textContent = totalFail.toLocaleString();
  $("#kpi-cost").textContent = "—";   // populated by future /api/billing/summary
}

function renderPacketGrid(packets) {
  const grid = $("#packet-grid");
  if (!packets.length) {
    grid.innerHTML = `<div class="empty-state">No packets yet — upload one to get started.</div>`;
    return;
  }
  grid.innerHTML = packets.map(p => {
    const pillClass = (p.status === "passed") ? "pass"
                    : (p.status === "failed") ? "fail"
                    : (p.status === "archived") ? "archived"
                    : (p.status === "error") ? "error"
                    : (p.status === "superseded") ? "superseded"
                    : "queued";
    return `
      <div class="packet-card" data-id="${p.id}">
        <div class="pc-head">
          <div class="pc-title">${escapeHtml(p.customer_canonical || "Unassigned")}</div>
          <span class="pill ${pillClass}">${p.status}</span>
        </div>
        <div class="pc-sub">${escapeHtml(p.display_name)} · ${p.n_pages || "?"} pages · ${p.n_sub_packets || "?"} sub-packet${(p.n_sub_packets!==1)?'s':''}</div>
        <div class="pc-stats">
          <div class="pc-stat"><div class="pc-stat-value pass">${p.n_pass}</div><div>Pass</div></div>
          <div class="pc-stat"><div class="pc-stat-value fail">${p.n_fail}</div><div>Fail</div></div>
          <div class="pc-stat"><div class="pc-stat-value info">${p.n_info}</div><div>Info</div></div>
        </div>
      </div>`;
  }).join("");
  $$(".packet-card", grid).forEach(card =>
    card.addEventListener("click", () => openDetail(card.dataset.id)));
}

// ---------------------------------------------------------------------------
// Customer index
// ---------------------------------------------------------------------------

async function loadCustomers() {
  const grid = $("#customer-grid");
  grid.innerHTML = `<div class="empty-state">Loading…</div>`;
  try {
    const customers = await api("/api/customers");
    if (!customers.length) {
      grid.innerHTML = `<div class="empty-state">No verifications yet.</div>`;
      return;
    }
    grid.innerHTML = customers.map(c => `
      <div class="customer-card" data-name="${escapeAttr(c.canonical_name)}">
        <h3>${escapeHtml(c.canonical_name)}</h3>
        <div class="meta">
          <span>📦 ${c.n_packets} packet${c.n_packets!==1?'s':''}</span>
          <span style="color:var(--green)">✓ ${c.n_passed}</span>
          <span style="color:var(--orange)">✗ ${c.n_failed}</span>
          <span>${c.last_upload_at ? new Date(c.last_upload_at).toLocaleDateString() : ''}</span>
        </div>
      </div>`).join("");
    $$(".customer-card", grid).forEach(card =>
      card.addEventListener("click", () => openCustomerPackets(card.dataset.name)));
  } catch (e) {
    grid.innerHTML = `<div class="empty-state">${e.message}</div>`;
  }
}

async function openCustomerPackets(name) {
  showView("recent");
  const packets = await api(`/api/packets?customer=${encodeURIComponent(name)}`);
  renderKpis(packets);
  renderPacketGrid(packets);
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------

const dz = $("#dropzone");
const fileInput = $("#upload-file");
let queuedFile = null;
dz.addEventListener("click", () => fileInput.click());
dz.addEventListener("dragover", e => { e.preventDefault(); dz.classList.add("over"); });
dz.addEventListener("dragleave", () => dz.classList.remove("over"));
dz.addEventListener("drop", e => {
  e.preventDefault();
  dz.classList.remove("over");
  if (e.dataTransfer.files[0]) {
    queuedFile = e.dataTransfer.files[0];
    $(".dz-text", dz).textContent = `Ready: ${queuedFile.name}`;
  }
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) {
    queuedFile = fileInput.files[0];
    $(".dz-text", dz).textContent = `Ready: ${queuedFile.name}`;
  }
});

$("#upload-form").addEventListener("submit", async e => {
  e.preventDefault();
  if (!queuedFile) { alert("Choose or drop a PDF first"); return; }
  const status = $("#upload-status");
  status.textContent = "Uploading…";
  const fd = new FormData();
  fd.append("pdf", queuedFile);
  if ($("#upload-name").value) fd.append("display_name", $("#upload-name").value);
  try {
    const p = await apiUpload("/api/packets", fd);
    status.innerHTML = `Queued — packet <b>${escapeHtml(p.display_name)}</b> verifying. Watch progress in <a href="#" id="goto-detail">the detail view</a>.`;
    $("#goto-detail").addEventListener("click", e => { e.preventDefault(); openDetail(p.id); });
    pollPacketUntilDone(p.id);
  } catch (e) {
    status.textContent = `Upload failed: ${e.message}`;
  }
});

async function pollPacketUntilDone(id) {
  for (let i = 0; i < 240; i++) {     // up to 8 min @ 2s
    await sleep(2000);
    const p = await api(`/api/packets/${id}`);
    if (p.status === "passed" || p.status === "failed" || p.status === "error") {
      loadPackets(); return p;
    }
  }
}

// ---------------------------------------------------------------------------
// Packet detail
// ---------------------------------------------------------------------------

async function openDetail(id) {
  showView("detail");
  $("#view-recent").classList.remove("active"); $("#view-recent").hidden = true;
  $("#view-detail").classList.add("active"); $("#view-detail").hidden = false;
  const p = await api(`/api/packets/${id}`);
  CURRENT_PACKET = p;
  $("#detail-title").textContent = p.customer_canonical || "(customer pending)";
  $("#detail-sub").textContent =
    `${p.display_name} · ${p.invoice_no || "no invoice #"} · WO ${p.work_orders || "?"} · status ${p.status}`;
  $("#detail-pdf").href = p.storage_url_verified_pdf || "#";
  $("#detail-xlsx").href = p.storage_url_matrix_xlsx || "#";
  $("#detail-pdf").style.display = p.storage_url_verified_pdf ? "" : "none";
  $("#detail-xlsx").style.display = p.storage_url_matrix_xlsx ? "" : "none";

  if (p.status === "queued" || p.status === "running") {
    $("#subpackets").innerHTML = `<div class="empty-state">Verifying…</div>`;
    setTimeout(() => openDetail(id), 3000);
    return;
  }

  if (p.storage_url_trace_json) {
    LIVE_TRACE = await api(`/api/packets/${p.id}/trace`);
    renderSubpackets(LIVE_TRACE);
    renderMatrix(LIVE_TRACE);
    renderChecks(LIVE_TRACE);
    renderPages(LIVE_TRACE);
  }
  renderOverrides(p.id);
}

$("#detail-back").addEventListener("click", () => showView("recent"));

$("#detail-rescan").addEventListener("click", async () => {
  if (!CURRENT_PACKET) return;
  const fd = new FormData();          // no PDF → re-run on existing input
  await apiUpload(`/api/packets/${CURRENT_PACKET.id}/rescan`, fd);
  setTimeout(() => openDetail(CURRENT_PACKET.id), 1500);
});
$("#detail-rescan-new").addEventListener("click", () => {
  if (!CURRENT_PACKET) return;
  const inp = document.createElement("input");
  inp.type = "file"; inp.accept = "application/pdf";
  inp.addEventListener("change", async () => {
    if (!inp.files[0]) return;
    const fd = new FormData(); fd.append("pdf", inp.files[0]);
    const newP = await apiUpload(`/api/packets/${CURRENT_PACKET.id}/rescan`, fd);
    openDetail(newP.id);
  });
  inp.click();
});

// --- subpackets / matrix / checks / pages ---

function renderSubpackets(trace) {
  const wrap = $("#subpackets");
  wrap.innerHTML = trace.sub_packets.map(sp => `
    <div class="subpacket">
      <b>Sub-packet #${sp.index + 1}</b> · WO ${sp.primary_wo || "?"} · PO ${sp.primary_po || "?"} · ${sp.primary_customer || "?"} · ${sp.primary_product || "?"} · ${sp.cases || "?"} cases
    </div>`).join("");
}

function renderMatrix(trace) {
  const t = $("#matrix");
  const fields = uniqueFields(trace);
  const pages = trace.pages.map(p => p.page_no);
  let html = `<thead><tr><th class="field-cell">Field</th>` +
    pages.map(n => `<th>p${n}</th>`).join("") + `</tr></thead><tbody>`;
  for (const f of fields) {
    html += `<tr><td class="field-cell">${escapeHtml(f.label)}</td>`;
    for (const p of trace.pages) {
      const v = (p.fields || {})[f.key];
      if (v === undefined || v === null || v === "") {
        html += `<td class="empty">—</td>`;
      } else {
        html += `<td class="match editable" data-page="${p.page_no}" data-field="${escapeAttr(f.key)}" data-current="${escapeAttr(v)}" title="Click to correct">${escapeHtml(stringify(v))}</td>`;
      }
    }
    html += `</tr>`;
  }
  html += `</tbody>`;
  t.innerHTML = html;
  $$(".matrix .editable", t).forEach(td => td.addEventListener("click", () => openEditModal(td)));
}

function uniqueFields(trace) {
  const known = ["wo", "po", "customer", "product", "cases", "unit_lbs",
                 "total_lbs", "moisture_pct", "sulfur_ppm", "crop_year",
                 "invoice_no", "bol_no", "carrier", "total_defect_pct"];
  const labels = { wo: "WO #", po: "PO #", customer: "Customer", product: "Product",
                   cases: "Cases", unit_lbs: "Lbs / case", total_lbs: "Total lbs",
                   moisture_pct: "Moisture %", sulfur_ppm: "Sulfur ppm",
                   crop_year: "Crop year", invoice_no: "Invoice #", bol_no: "BOL #",
                   carrier: "Carrier", total_defect_pct: "Total defect %" };
  const seen = new Set(known);
  for (const p of trace.pages) {
    for (const k of Object.keys(p.fields || {})) {
      if (typeof p.fields[k] !== "object" && !seen.has(k)) {
        seen.add(k); known.push(k); labels[k] = humanize(k);
      }
    }
  }
  return known.map(k => ({ key: k, label: labels[k] || humanize(k) }));
}

function humanize(k) {
  return k.replace(/_/g, " ").replace(/\b\w/g, m => m.toUpperCase());
}

function stringify(v) {
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function renderChecks(trace) {
  const all = [];
  for (const sp of trace.sub_packets) (sp.checks || []).forEach(c => all.push(c));
  (trace.packet_level_checks || []).forEach(c => all.push(c));
  $("#checks-count").textContent = all.length;
  $("#checks-list").innerHTML = all.map(c => `
    <div class="check ${c.status}">
      <span class="name">${escapeHtml(c.name)}</span>
      ${escapeHtml(c.detail || "")}
      <span class="pages">pages ${(c.pages || []).join(", ") || "—"}</span>
    </div>`).join("");
}

function renderPages(trace) {
  $("#pages-list").innerHTML = trace.pages.map(p => {
    const flags = (p.notes || []).length;
    const isBack = (p.fields || {}).is_backup_source;
    return `<div class="page-item ${flags ? 'has-flag' : ''} ${isBack ? 'is-backup' : ''}"
                  title="${escapeAttr((p.notes || []).join('\n'))}">
              p${p.page_no} · ${escapeHtml(p.form_label || p.form_code || '?')}
            </div>`;
  }).join("");
}

async function renderOverrides(packetId) {
  const list = $("#overrides-list");
  try {
    const rows = await api(`/api/packets/${packetId}/overrides`);
    list.innerHTML = rows.length ? rows.map(o => `
      <div class="override-row">
        <b>${escapeHtml(o.field_key)}</b> on p${o.page_no} → ${escapeHtml(o.new_value)}
        <div class="who">by ${escapeHtml(o.edited_by_email || "?")} · ${new Date(o.edited_at).toLocaleString()}</div>
        ${o.rationale ? `<div class="muted">${escapeHtml(o.rationale)}</div>` : ""}
      </div>`).join("") : `<div class="muted">No corrections yet.</div>`;
  } catch (e) {
    list.innerHTML = `<div class="muted">Could not load corrections.</div>`;
  }
}

// ---------------------------------------------------------------------------
// Edit modal
// ---------------------------------------------------------------------------

function openEditModal(td) {
  $("#edit-field").value = td.dataset.field;
  $("#edit-page").value = `p${td.dataset.page}`;
  $("#edit-current").value = td.dataset.current;
  $("#edit-new").value = "";
  $("#edit-rationale").value = "";
  showModal("edit");
}

$("#edit-form").addEventListener("submit", async e => {
  e.preventDefault();
  if (!CURRENT_PACKET) return;
  const body = {
    page_no: parseInt($("#edit-page").value.replace(/^p/, ""), 10),
    field_key: $("#edit-field").value,
    new_value: $("#edit-new").value,
    rationale: $("#edit-rationale").value,
  };
  await api(`/api/packets/${CURRENT_PACKET.id}/overrides`, {
    method: "POST", body: JSON.stringify(body),
  });
  hideModal("edit");
  setTimeout(() => openDetail(CURRENT_PACKET.id), 1200);
});

// ---------------------------------------------------------------------------
// Sign-off
// ---------------------------------------------------------------------------

$("#signoff-btn").addEventListener("click", async () => {
  if (!CURRENT_PACKET) return;
  if (!CURRENT_USER.has_signature) {
    alert("Set up your signature first (✎ signature in the top bar).");
    return;
  }
  $("#signoff-status").textContent = "Stamping & archiving…";
  try {
    const out = await api(`/api/packets/${CURRENT_PACKET.id}/signoff`, {
      method: "POST",
      body: JSON.stringify({ notes: $("#signoff-notes").value, use_stored_signature: true }),
    });
    $("#signoff-status").innerHTML =
      `Archived — <a href="${out.archived_pdf_url}" target="_blank" rel="noopener">view stamped PDF</a>`;
    setTimeout(() => openDetail(CURRENT_PACKET.id), 1200);
  } catch (e) {
    $("#signoff-status").textContent = `Sign-off failed: ${e.message}`;
  }
});

// ---------------------------------------------------------------------------
// Signature pad
// ---------------------------------------------------------------------------

function setupSignaturePad() {
  const c = $("#sig-canvas"); const ctx = c.getContext("2d");
  let drawing = false;
  function pos(e) {
    const r = c.getBoundingClientRect();
    const t = e.touches ? e.touches[0] : e;
    return { x: ((t.clientX - r.left) / r.width) * c.width,
             y: ((t.clientY - r.top) / r.height) * c.height };
  }
  function start(e) { e.preventDefault(); drawing = true; const p = pos(e); ctx.beginPath(); ctx.moveTo(p.x, p.y); }
  function move(e)  { if (!drawing) return; e.preventDefault(); const p = pos(e); ctx.lineTo(p.x, p.y); ctx.stroke(); }
  function end()    { drawing = false; }
  ctx.lineWidth = 2.4; ctx.strokeStyle = "#1f2937"; ctx.lineCap = "round"; ctx.lineJoin = "round";
  ["mousedown","touchstart"].forEach(ev => c.addEventListener(ev, start));
  ["mousemove","touchmove"].forEach(ev => c.addEventListener(ev, move));
  ["mouseup","mouseleave","touchend","touchcancel"].forEach(ev => c.addEventListener(ev, end));

  $("#sig-clear").addEventListener("click", () => ctx.clearRect(0, 0, c.width, c.height));
  $("#sig-save").addEventListener("click", async () => {
    const blob = await new Promise(r => c.toBlob(r, "image/png"));
    const fd = new FormData(); fd.append("signature", blob, "signature.png");
    const r = await fetch("/api/me/signature", { method: "PUT", body: fd, headers: authHeaders() });
    if (!r.ok) { alert("Save failed"); return; }
    CURRENT_USER = await r.json();
    hideModal("signature");
  });
}

$("#signature-btn").addEventListener("click", () => showModal("signature"));

// ---------------------------------------------------------------------------
// Audit log
// ---------------------------------------------------------------------------

async function loadAuditLog() {
  if (CURRENT_USER && CURRENT_USER.role !== "admin") return;
  const tbody = $("#audit-table tbody");
  tbody.innerHTML = "";
  try {
    const rows = await api("/api/audit_log?limit=200");
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td>${new Date(r.at).toLocaleString()}</td>
        <td>${escapeHtml(r.user_email || "—")}</td>
        <td><b>${escapeHtml(r.action)}</b></td>
        <td>${escapeHtml(r.target_type || "")}<br>${escapeHtml(r.target_id || "")}</td>
        <td><code>${escapeHtml(JSON.stringify(r.details || {}))}</code></td>
      </tr>`).join("");
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="5">${e.message}</td></tr>`;
  }
}

// ---------------------------------------------------------------------------
// Modal helpers + utilities
// ---------------------------------------------------------------------------

function showModal(name) { $(`#modal-${name}`).classList.remove("hidden"); }
function hideModal(name) { $(`#modal-${name}`).classList.add("hidden"); }
$$("[data-close]").forEach(b => b.addEventListener("click", e => {
  e.target.closest(".modal-overlay").classList.add("hidden");
}));

function escapeHtml(s) { return String(s ?? "").replace(/[&<>"']/g, ch =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])); }
function escapeAttr(s) { return escapeHtml(s).replace(/"/g, "&quot;"); }
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

(async function boot() {
  await loadToken();
  try { await loadMe(); }
  catch (e) {
    document.body.innerHTML = `<div style="padding:40px;text-align:center;font-family:sans-serif">
      <h2>Sign in required</h2>
      <p>This deployment uses ${window.AUTH_PROVIDER || 'an external auth provider'}.
      Connect it to a frontend (Clerk's React SDK or supabase-js) and store the access token at
      <code>localStorage.cfi_token</code>.</p>
    </div>`;
    return;
  }
  setupSignaturePad();
  showView("recent");
})();
