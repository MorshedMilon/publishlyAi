/* P12 Review Dashboard — frontend. Vanilla JS, talks only to the localhost backend (which holds
 * the Supabase service key). No credentials, no DB access here (SPEC-P12 Security). */

"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const http = {
  async get(path) {
    const r = await fetch(path);
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  },
};

let _toastTimer = null;
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.toggle("err", isErr);
  t.hidden = false;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => (t.hidden = true), 3200);
}

const fmtComposite = (v) => (v == null ? "—" : Number(v).toFixed(2));
const fmtScore = (v) => (v == null ? "—" : Math.round(Number(v) * 10) / 10);

// Skip = client-side dismissal only (no DB write — there is no 'skipped' niche status, §8.2).
const skipped = new Set(JSON.parse(sessionStorage.getItem("p12_skipped") || "[]"));
const persistSkipped = () =>
  sessionStorage.setItem("p12_skipped", JSON.stringify([...skipped]));

// ---------------------------------------------------------------------------
// View switching
// ---------------------------------------------------------------------------
function switchView(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.view === name));
  $("#view-select").hidden = name !== "select";
  $("#view-approve").hidden = name !== "approve";
  if (name === "select") loadSelect();
  else loadApprove();
}

$$(".tab").forEach((t) => t.addEventListener("click", () => switchView(t.dataset.view)));

// ---------------------------------------------------------------------------
// SELECT view
// ---------------------------------------------------------------------------
async function loadSelect() {
  const list = $("#select-list");
  list.innerHTML = "";
  let data;
  try {
    data = await http.get("/api/select-queue");
  } catch (e) {
    toast(e.message, true);
    return;
  }
  $("#operator").textContent = data.operator || "—";

  // Soft cap: warn, never block (SPEC-P12 Acceptance test).
  const banner = $("#cap-banner");
  banner.innerHTML = "";
  if (data.over_cap) {
    banner.innerHTML =
      `<div class="banner"><strong>Soft cap reached.</strong> ${data.selected_today} of ` +
      `${data.daily_cap}/day already selected. You can still select more, but quality &gt; ` +
      `quantity — the cap floats down, never up (CLAUDE §4.5).</div>`;
  }
  $("#cap-line").innerHTML =
    `Selected today: <span class="num">${data.selected_today}</span> / ` +
    `<span class="num">${data.daily_cap}</span> soft cap`;

  const items = (data.items || []).filter((i) => !skipped.has(i.product_id));
  $("#select-count").textContent = items.length ? `(${items.length})` : "";
  if (!items.length) {
    list.innerHTML =
      `<div class="empty"><h2>Nothing to select</h2>` +
      `<p>No validated candidates are waiting. A quiet queue is the funnel working (CLAUDE §2).</p></div>`;
    return;
  }
  items.forEach((item) => list.appendChild(renderSelectCard(item)));
}

function renderSelectCard(item) {
  const node = $("#tpl-select-card").content.firstElementChild.cloneNode(true);
  $(".sub-niche", node).textContent = item.sub_niche || "(unnamed niche)";
  $(".channel", node).textContent = item.channel || "—";
  $(".composite", node).textContent = "composite " + fmtComposite(item.validation_composite);
  $(".buyer", node).textContent = item.target_buyer || "—";
  $(".gap", node).textContent = item.gap_thesis || "—";

  const ul = $(".weak-list", node);
  if (!item.weaknesses || !item.weaknesses.length) {
    $(".weak", node).remove();
  } else {
    item.weaknesses.forEach((w) => {
      const li = document.createElement("li");
      li.innerHTML =
        `<span class="complaint">${esc(w.complaint || "")}</span> ` +
        `<span class="fix">${esc(w.fix || "")}</span>` +
        (w.measurable ? ` <span class="measurable">[${esc(w.measurable)}]</span>` : "");
      ul.appendChild(li);
    });
  }

  $(".act-select", node).addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      await http.post("/api/select", { product_id: item.product_id });
      toast(`Selected “${item.sub_niche}” to build.`);
      loadSelect();
    } catch (err) {
      e.target.disabled = false;
      toast(err.message, true);
    }
  });
  $(".act-skip", node).addEventListener("click", () => {
    skipped.add(item.product_id);
    persistSkipped();
    node.remove();
  });
  return node;
}

// ---------------------------------------------------------------------------
// APPROVE view
// ---------------------------------------------------------------------------
async function loadApprove() {
  const list = $("#approve-list");
  list.innerHTML = "";
  let data;
  try {
    data = await http.get("/api/approve-queue");
  } catch (e) {
    toast(e.message, true);
    return;
  }
  $("#operator").textContent = data.operator || "—";
  const items = data.items || [];
  $("#approve-count").textContent = items.length ? `(${items.length})` : "";
  if (!items.length) {
    list.innerHTML =
      `<div class="empty"><h2>Nothing to approve</h2>` +
      `<p>No products have cleared both gates yet.</p></div>`;
    return;
  }
  items.forEach((item) => list.appendChild(renderApproveCard(item)));
}

function renderApproveCard(item) {
  const node = $("#tpl-approve-card").content.firstElementChild.cloneNode(true);
  $(".title", node).textContent = item.title || item.gap_thesis || "(untitled product)";
  $(".channel", node).textContent = item.channel || "—";
  $(".qscore", node).textContent = "score " + fmtScore(item.quality_score);

  if (item.needs_human_attention) $(".attn-badge", node).hidden = false;

  // Rubric breakdown
  const rb = $(".rubric", node);
  const dims = ["differentiation", "design", "usability", "completeness", "value"];
  const rs = item.rubric_scores || {};
  if (dims.some((d) => rs[d] != null)) {
    dims.forEach((d) => {
      if (rs[d] == null) return;
      const row = document.createElement("div");
      row.className = "dim";
      row.innerHTML = `<span>${d}</span><b>${Number(rs[d]).toFixed(2)}</b>`;
      rb.appendChild(row);
    });
  } else {
    rb.remove();
  }

  // Interior preview — lazy-load the (heavy) PDF on demand (SPEC-P12 edge: stay responsive).
  const interior = $(".interior", node);
  if (item.has_interior) {
    const btn = document.createElement("button");
    btn.className = "lazybtn";
    btn.textContent = "Load interior PDF preview";
    btn.addEventListener("click", () => {
      const iframe = document.createElement("iframe");
      iframe.src = `/api/pdf?product_id=${encodeURIComponent(item.product_id)}&kind=interior`;
      iframe.title = "interior preview";
      interior.replaceChildren(iframe);
    });
    interior.appendChild(btn);
  } else {
    interior.innerHTML = `<div class="empty muted">no interior artifact</div>`;
  }

  // Cover (smaller — load directly)
  const cover = $(".cover", node);
  if (item.has_cover) {
    const cframe = document.createElement("iframe");
    cframe.src = `/api/pdf?product_id=${encodeURIComponent(item.product_id)}&kind=cover`;
    cframe.title = "cover preview";
    cover.appendChild(cframe);
  } else {
    cover.innerHTML = `<div class="empty muted">no cover</div>`;
  }

  // Per-channel listing copy
  const lc = $(".listings", node);
  const listings = item.listings || {};
  const channels = Object.keys(listings);
  if (channels.length) {
    const head = document.createElement("div");
    head.className = "eyebrow";
    head.textContent = "Listing copy (forked per channel, §5.1)";
    lc.appendChild(head);
    channels.forEach((ch) => {
      const b = listings[ch] || {};
      const cf = b.channel_fields || {};
      const tags = cf.tags || cf.keywords || [];
      const block = document.createElement("div");
      block.className = "lblock";
      block.innerHTML =
        `<div class="ch eyebrow">${esc(ch)}</div>` +
        `<div class="lt">${esc(b.title || "")}</div>` +
        (b.subtitle ? `<div class="muted">${esc(b.subtitle)}</div>` : "") +
        `<div class="ld">${esc(b.description || "")}</div>` +
        (tags.length ? `<div class="tags">${esc(tags.join(" · "))}</div>` : "");
      lc.appendChild(block);
    });
  } else {
    lc.remove();
  }

  // KDP package + manual mark-published (KDP is uploaded by hand — CLAUDE §3.1)
  if (item.has_kdp) {
    const pkg = $(".kdp-pkg", node);
    pkg.hidden = false;
    pkg.innerHTML =
      `<div class="eyebrow">KDP package (manual upload)</div><ul>` +
      `<li>${item.has_interior ? "Print-ready interior PDF" : "⚠ interior PDF missing"}</li>` +
      `<li>${item.has_cover ? "Wraparound cover PDF" : "⚠ cover missing"}</li>` +
      `<li>Metadata + 7 keywords / 2 categories (from listing copy)</li>` +
      `<li>AI-content declaration: ${esc(JSON.stringify(item.ai_disclosure || {}))}</li>` +
      `<li>Human checklist: trim · ≥24 pages · low-content box · AI declaration · pricing</li>` +
      `</ul>`;
    $(".act-kdp", node).hidden = false;
  }

  wireApproveActions(node, item);
  return node;
}

function wireApproveActions(node, item) {
  const pid = item.product_id;
  const forms = {
    edit: $(".form-edit", node),
    reject: $(".form-reject", node),
    kdp: $(".form-kdp", node),
  };
  const closeForms = () => Object.values(forms).forEach((f) => (f.hidden = true));

  // Approve
  $(".act-approve", node).addEventListener("click", async (e) => {
    e.target.disabled = true;
    try {
      await http.post("/api/approve", { product_id: pid });
      toast("Approved.");
      if (item.has_kdp) {
        // KDP next step is a manual upload — keep the card and open the mark-published form.
        $(".act-approve", node).textContent = "✓ Approved";
        $(".act-edit", node).disabled = true;
        $(".act-reject", node).disabled = true;
        closeForms();
        forms.kdp.hidden = false;
      } else {
        node.remove();
        refreshApproveCount();
      }
    } catch (err) {
      e.target.disabled = false;
      toast(err.message, true);
    }
  });

  // Edit
  $(".act-edit", node).addEventListener("click", () => {
    const open = forms.edit.hidden;
    closeForms();
    forms.edit.hidden = !open;
    if (open) {
      $(".f-title", node).value = item.title || "";
      $(".f-subtitle", node).value = item.subtitle || "";
      $(".f-description", node).value = item.description || "";
      $(".f-keywords", node).value = (item.keywords || []).join(", ");
    }
  });
  $(".act-edit-cancel", node).addEventListener("click", closeForms);
  $(".act-edit-save", node).addEventListener("click", async (e) => {
    e.target.disabled = true;
    const fields = {
      title: $(".f-title", node).value.trim(),
      subtitle: $(".f-subtitle", node).value.trim(),
      description: $(".f-description", node).value.trim(),
      keywords: $(".f-keywords", node).value.split(",").map((s) => s.trim()).filter(Boolean),
    };
    try {
      await http.post("/api/edit", { product_id: pid, fields });
      Object.assign(item, fields);
      $(".title", node).textContent = item.title || "(untitled product)";
      toast("Edits saved.");
      closeForms();
    } catch (err) {
      toast(err.message, true);
    } finally {
      e.target.disabled = false;
    }
  });

  // Reject
  $(".act-reject", node).addEventListener("click", () => {
    const open = forms.reject.hidden;
    closeForms();
    forms.reject.hidden = !open;
  });
  $(".act-reject-cancel", node).addEventListener("click", closeForms);
  $(".act-reject-confirm", node).addEventListener("click", async (e) => {
    const reason = $(".f-reason", node).value.trim();
    if (!reason) return toast("A reject reason is required.", true);
    e.target.disabled = true;
    try {
      await http.post("/api/reject", { product_id: pid, reason });
      toast("Rejected.");
      node.remove();
      refreshApproveCount();
    } catch (err) {
      e.target.disabled = false;
      toast(err.message, true);
    }
  });

  // KDP mark-published — ASIN required (confirm stays disabled until entered)
  $(".act-kdp", node).addEventListener("click", () => {
    const open = forms.kdp.hidden;
    closeForms();
    forms.kdp.hidden = !open;
  });
  $(".act-kdp-cancel", node).addEventListener("click", closeForms);
  const asin = $(".f-asin", node);
  const confirm = $(".act-kdp-confirm", node);
  asin.addEventListener("input", () => (confirm.disabled = !asin.value.trim()));
  confirm.addEventListener("click", async (e) => {
    if (!asin.value.trim()) return;
    e.target.disabled = true;
    const price = $(".f-price", node).value;
    try {
      await http.post("/api/kdp-publish", {
        product_id: pid,
        asin: asin.value.trim(),
        listing_url: $(".f-url", node).value.trim() || null,
        price: price ? Number(price) : null,
      });
      toast("KDP ledger row written (status=live).");
      closeForms();
      $(".act-kdp", node).textContent = "✓ Published";
      $(".act-kdp", node).disabled = true;
    } catch (err) {
      e.target.disabled = false;
      toast(err.message, true);
    }
  });
}

function refreshApproveCount() {
  const n = $$("#approve-list .card").length;
  $("#approve-count").textContent = n ? `(${n})` : "";
  if (!n) {
    $("#approve-list").innerHTML =
      `<div class="empty"><h2>Nothing to approve</h2><p>Queue cleared.</p></div>`;
  }
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

// Boot on the default (Select) view.
switchView("select");
