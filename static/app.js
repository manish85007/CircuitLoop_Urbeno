const $app = document.getElementById("app");

const state = {
  view: "jobs",
  tab: "today",
  crew: null,
  jobs: [],
  job: null,
  health: true,
  loading: true,
  error: "",
  notice: "",
  busy: false,
};

const TYPE_LABEL = {
  itad_pickup: "ITAD pickup",
  onsite_degauss: "On-site degauss",
  office_decommission: "Office decommission",
};

const STATUS_LABEL = {
  scheduled: "Scheduled",
  en_route: "En route",
  on_site: "On site",
  complete: "Complete",
};

const LOGO = `/static/favicon.svg`;

async function api(path, opts = {}) {
  const init = {
    credentials: "include",
    headers: { ...(opts.body instanceof FormData ? {} : { "Content-Type": "application/json" }) },
    ...opts,
  };
  if (opts.body && !(opts.body instanceof FormData) && typeof opts.body !== "string") {
    init.body = JSON.stringify(opts.body);
  }
  let res;
  try {
    res = await fetch(path, init);
  } catch (err) {
    state.health = false;
    throw new Error("CircuitLoop is offline. Check the signal and retry.");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `Request failed (${res.status})`);
  }
  return data;
}

function fmtWindow(job) {
  const start = new Date(job.window_start);
  const end = new Date(job.window_end);
  const same = start.toDateString() === new Date().toDateString();
  const day = same
    ? "Today"
    : start.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const t = (d) => d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${day} · ${t(start)}–${t(end)}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function banner() {
  if (state.error) return `<div class="banner error">${escapeHtml(state.error)}</div>`;
  if (state.notice) return `<div class="banner ok">${escapeHtml(state.notice)}</div>`;
  return "";
}

function topbar() {
  return `
    <header class="topbar">
      <div class="brand">
        <img src="${LOGO}" alt="" />
        <div>
          <h1>CircuitLoop</h1>
          <small>Urbeno field</small>
        </div>
      </div>
      <div class="live ${state.health ? "" : "down"}">
        <span class="dot"></span>
        ${state.health ? "Live" : "Offline"}
      </div>
    </header>
  `;
}

function nav(active) {
  if (!state.crew) return "";
  return `
    <nav class="bottom-nav">
      <button data-nav="jobs" class="${active === "jobs" ? "active" : ""}">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 9h8M8 13h5"/></svg>
        Jobs
      </button>
      <button data-nav="scan" class="${active === "scan" ? "active" : ""}">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 4H5a1 1 0 00-1 1v2M17 4h2a1 1 0 011 1v2M7 20H5a1 1 0 01-1-1v-2M17 20h2a1 1 0 001-1v-2"/><rect x="8" y="8" width="8" height="8" rx="1"/></svg>
        Scan
      </button>
    </nav>
  `;
}

function renderLock() {
  $app.innerHTML = `
    ${topbar()}
    <main class="shell">
      <section class="card lock">
        <h2>Sign in to the loop</h2>
        <p>Field collection for certified pickup, seals, and chain of custody.</p>
        ${banner()}
        <form id="lock-form">
          <div class="field">
            <label for="crewName">Crew name</label>
            <input id="crewName" name="crewName" type="text" autocomplete="username" placeholder="Priya Nair" required />
          </div>
          <div class="field">
            <label for="pin">Crew PIN</label>
            <input id="pin" name="pin" type="password" inputmode="numeric" autocomplete="current-password" placeholder="••••" required />
          </div>
          <div class="field">
            <button class="btn btn-primary" type="submit" ${state.busy ? "disabled" : ""}>Open today’s board</button>
          </div>
        </form>
      </section>
    </main>
  `;
  document.getElementById("lock-form").addEventListener("submit", onSignIn);
}

function renderJobs() {
  const list = state.jobs
    .map(
      (job) => `
      <button class="job" data-open="${job.id}">
        <div class="job-head">
          <div>
            <div class="code">${escapeHtml(job.code)} · ${escapeHtml(TYPE_LABEL[job.job_type] || job.job_type)}</div>
            <h3>${escapeHtml(job.title)}</h3>
          </div>
          <span class="chip ${job.status}">${STATUS_LABEL[job.status] || job.status}</span>
        </div>
        <div class="meta">${escapeHtml(job.client_name)} · ${escapeHtml(job.site_name)}<br>${escapeHtml(fmtWindow(job))}</div>
        <div class="counts">
          <span>${job.collected_units}/${job.expected_units} units</span>
          <span>${job.seal_count} seals</span>
        </div>
      </button>
    `
    )
    .join("");

  $app.innerHTML = `
    ${topbar()}
    <main class="shell">
      <div class="crew-line">
        <strong>${escapeHtml(state.crew.name)}</strong>
        <button type="button" id="sign-out">Sign out</button>
      </div>
      <div class="tabs">
        <button data-tab="today" class="${state.tab === "today" ? "active" : ""}">Today</button>
        <button data-tab="done" class="${state.tab === "done" ? "active" : ""}">Done</button>
      </div>
      ${banner()}
      ${state.loading ? `<p class="loading">Loading jobs…</p>` : ""}
      ${!state.loading && !state.jobs.length ? `<p class="empty">${state.tab === "done" ? "No completed jobs yet." : "No open pickups on this crew."}</p>` : list}
    </main>
    ${nav("jobs")}
  `;
  document.getElementById("sign-out")?.addEventListener("click", onSignOut);
  bindNav();
}

function renderJob() {
  const job = state.job;
  if (!job) return renderJobs();
  const onSite = job.status === "on_site";
  const complete = job.status === "complete";
  const gps = job.check_in_lat
    ? `${Number(job.check_in_lat).toFixed(4)}, ${Number(job.check_in_lng).toFixed(4)}`
    : "Not checked in";

  const assets = (job.assets || [])
    .map(
      (a) => `
      <div class="asset">
        <div>
          <strong>${escapeHtml(a.category)}</strong> · ${escapeHtml(a.serial_number || a.asset_tag)}<br>
          <span class="meta">${escapeHtml([a.manufacturer, a.model].filter(Boolean).join(" "))} ${a.data_bearing ? "· data-bearing" : ""} · ${escapeHtml(a.destruction_method)}</span>
        </div>
        ${complete ? "" : `<button class="btn btn-danger" data-del-asset="${a.id}">Remove</button>`}
      </div>
    `
    )
    .join("") || `<p class="meta">No devices logged yet.</p>`;

  const seals = (job.seals || [])
    .map((s) => `<div class="seal"><strong>${escapeHtml(s.code)}</strong><span class="meta">${escapeHtml(s.location || "crate")}</span></div>`)
    .join("") || `<p class="meta">No seals yet.</p>`;

  const photos = (job.photos || [])
    .map(
      (p) =>
        `<img src="/api/media/${encodeURIComponent(p.path)}" alt="${escapeHtml(p.caption || "Job photo")}" />`
    )
    .join("");

  $app.innerHTML = `
    ${topbar()}
    <main class="shell sheet">
      <button class="back" id="back">← Jobs</button>
      ${banner()}
      <h2>${escapeHtml(job.title)}</h2>
      <p class="sub">${escapeHtml(job.code)} · <span class="chip ${job.status}">${STATUS_LABEL[job.status]}</span></p>
      <section class="card">
        <dl class="kv">
          <dt>Client</dt><dd>${escapeHtml(job.client_name)}</dd>
          <dt>Site</dt><dd>${escapeHtml(job.site_name)}<br>${escapeHtml(job.address)}, ${escapeHtml(job.city)}</dd>
          <dt>Window</dt><dd>${escapeHtml(fmtWindow(job))}</dd>
          <dt>Contact</dt><dd>${escapeHtml(job.contact_name)} · ${escapeHtml(job.contact_phone)}</dd>
          <dt>GPS</dt><dd>${escapeHtml(gps)}</dd>
          <dt>Count</dt><dd>${job.collected_units} collected / ${job.expected_units} expected</dd>
        </dl>
        ${job.notes ? `<p class="meta" style="margin-top:.8rem">${escapeHtml(job.notes)}</p>` : ""}
        <div class="btn-row" style="margin-top:1rem">
          ${job.status === "scheduled" ? `<button class="btn btn-ghost" id="start-route">Start route</button>` : ""}
          ${job.status !== "complete" && job.status !== "on_site" ? `<button class="btn btn-primary" id="check-in">Check in on site</button>` : ""}
        </div>
      </section>

      <h3 class="section-title">Devices</h3>
      <section class="card">${assets}</section>
      ${onSite ? assetForm() : ""}

      <h3 class="section-title">Seals</h3>
      <section class="card">${seals}</section>
      ${onSite ? `
        <form id="seal-form" class="card">
          <div class="field"><label>Seal code</label><input name="code" required placeholder="URN-SEAL-11040" /></div>
          <div class="field"><label>Location</label><input name="location" placeholder="crate B" /></div>
          <button class="btn btn-primary" type="submit">Add seal</button>
        </form>` : ""}

      <h3 class="section-title">Photos</h3>
      <section class="card">
        ${photos ? `<div class="photos">${photos}</div>` : `<p class="meta">No photos yet.</p>`}
        ${onSite ? `
          <form id="photo-form" class="stack" style="margin-top:.8rem">
            <div class="field"><label>Evidence photo</label><input type="file" name="file" accept="image/*" capture="environment" required /></div>
            <div class="field"><label>Caption</label><input name="caption" placeholder="Loading bay / sealed crate" /></div>
            <button class="btn btn-primary" type="submit">Upload photo</button>
          </form>` : ""}
      </section>

      <h3 class="section-title">Client sign-off</h3>
      <section class="card">
        ${job.acknowledged ? `<p class="banner ok">Signed by ${escapeHtml(job.ack_signer_name)} (${escapeHtml(job.ack_signer_role || "client")}).</p>
          ${job.ack_signature_path ? `<img src="/api/media/${encodeURIComponent(job.ack_signature_path)}" alt="Signature" style="max-height:90px;background:#fff;border-radius:8px" />` : ""}` : ""}
        ${onSite && !job.acknowledged ? `
          <form id="ack-form">
            <div class="field"><label>Signer name</label><input name="signerName" required placeholder="${escapeHtml(job.contact_name)}" /></div>
            <div class="field"><label>Role</label><input name="signerRole" placeholder="Facilities / branch manager" /></div>
            <div class="field"><label>Signature</label><div class="sig-wrap"><canvas id="sig" width="400" height="140"></canvas></div>
              <button type="button" class="btn btn-ghost" id="clear-sig" style="margin-top:.5rem;width:auto">Clear</button></div>
            <button class="btn btn-primary" type="submit">Save acknowledgment</button>
          </form>` : ""}
      </section>

      ${onSite ? `
        <h3 class="section-title">Close job</h3>
        <form id="complete-form" class="card">
          ${job.collected_units < job.expected_units ? `<p class="banner warn">Collected ${job.collected_units} of ${job.expected_units}. Add an override note to close short.</p>
            <div class="field"><label>Override note</label><textarea name="overrideNote" placeholder="Remaining units not staged / client to reschedule"></textarea></div>` : ""}
          <button class="btn btn-primary" type="submit" ${state.busy ? "disabled" : ""}>Complete collection</button>
        </form>` : ""}
    </main>
    ${nav("jobs")}
  `;

  document.getElementById("back")?.addEventListener("click", () => {
    state.job = null;
    state.view = "jobs";
    loadJobs();
  });
  document.getElementById("start-route")?.addEventListener("click", () => act(`/api/jobs/${job.id}/start-route`));
  document.getElementById("check-in")?.addEventListener("click", onCheckIn);
  document.getElementById("seal-form")?.addEventListener("submit", onSeal);
  document.getElementById("photo-form")?.addEventListener("submit", onPhoto);
  document.getElementById("ack-form")?.addEventListener("submit", onAck);
  document.getElementById("complete-form")?.addEventListener("submit", onComplete);
  document.getElementById("asset-form")?.addEventListener("submit", onAsset);
  document.querySelectorAll("[data-del-asset]").forEach((btn) =>
    btn.addEventListener("click", () => deleteAsset(btn.dataset.delAsset))
  );
  setupSignature();
  bindNav();
}

function assetForm(compact = false) {
  return `
    <form id="asset-form" class="card">
      <div class="field"><label>Category</label>
        <select name="category" required>
          <option value="laptop">Laptop</option>
          <option value="desktop">Desktop</option>
          <option value="monitor">Monitor</option>
          <option value="hdd">HDD / SSD</option>
          <option value="server">Server</option>
          <option value="network">Network</option>
          <option value="phone">Phone / tablet</option>
          <option value="other">Other</option>
        </select>
      </div>
      <div class="field"><label>Serial number</label><input name="serialNumber" placeholder="Service tag / SN" /></div>
      <div class="field"><label>Asset tag</label><input name="assetTag" placeholder="Client tag" /></div>
      <div class="field"><label>Make / model</label>
        <div class="btn-row">
          <input name="manufacturer" placeholder="Dell" />
          <input name="model" placeholder="Latitude 5440" />
        </div>
      </div>
      <div class="field"><label>Condition</label>
        <select name="condition">
          <option value="used">Used</option>
          <option value="fair">Fair</option>
          <option value="damaged">Damaged</option>
          <option value="new">New / unused</option>
        </select>
      </div>
      <div class="field"><label>Destruction</label>
        <select name="destructionMethod">
          <option value="wipe">NIST wipe</option>
          <option value="degauss">Degauss</option>
          <option value="shred">Shred</option>
          <option value="recycle">Recycle only</option>
        </select>
      </div>
      <div class="field">
        <label><input type="checkbox" name="dataBearing" /> Data-bearing device</label>
      </div>
      <div class="field"><label>Notes</label><input name="notes" placeholder="Optional" /></div>
      <button class="btn btn-primary" type="submit">${compact ? "Log scanned device" : "Add device"}</button>
    </form>
  `;
}

function renderScan() {
  const onSite = state.jobs.filter((j) => j.status === "on_site");
  const target = state.job && state.job.status === "on_site" ? state.job : onSite[0];
  $app.innerHTML = `
    ${topbar()}
    <main class="shell">
      <h2 class="sheet" style="font-family:DM Serif Display,serif;font-size:1.45rem;margin:0.4rem 0 0.4rem">Scan into an open job</h2>
      ${banner()}
      ${target ? `<p class="meta">Logging to <strong>${escapeHtml(target.code)}</strong> — ${escapeHtml(target.client_name)}</p>${assetForm(true)}` : `<p class="empty">Check in on a job before scanning devices.</p>`}
    </main>
    ${nav("scan")}
  `;
  if (target) {
    state.job = state.job?.id === target.id ? state.job : null;
    document.getElementById("asset-form")?.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await submitAsset(target.id, e.target);
        state.job = null;
        state.notice = `Device logged to ${target.code}.`;
        state.error = "";
        e.target.reset();
      } catch (err) {
        state.error = err.message;
      }
      render();
    });
  }
  bindNav();
}

function bindNav() {
  document.querySelectorAll("[data-nav]").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.view = btn.dataset.nav;
      state.error = "";
      if (state.view === "jobs") loadJobs();
      else render();
    })
  );
  document.querySelectorAll("[data-tab]").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.tab = btn.dataset.tab;
      loadJobs();
    })
  );
  document.querySelectorAll("[data-open]").forEach((btn) =>
    btn.addEventListener("click", () => openJob(btn.dataset.open))
  );
}

function render() {
  if (!state.crew) return renderLock();
  if (state.view === "scan") return renderScan();
  if (state.job) return renderJob();
  return renderJobs();
}

async function ping() {
  try {
    await api("/api/health");
    state.health = true;
  } catch {
    state.health = false;
  }
}

async function boot() {
  await ping();
  try {
    const data = await api("/api/session");
    state.crew = data.crew;
    if (state.crew) await loadJobs();
    else {
      state.loading = false;
      render();
    }
  } catch (err) {
    state.loading = false;
    state.error = err.message;
    render();
  }
}

async function loadJobs(showLoading = true) {
  if (showLoading) state.loading = true;
  state.error = "";
  render();
  try {
    const data = await api(`/api/jobs?tab=${state.tab}`);
    state.jobs = data.jobs;
    state.crew = data.crew || state.crew;
  } catch (err) {
    state.error = err.message;
  } finally {
    state.loading = false;
    render();
  }
}

async function openJob(id) {
  state.error = "";
  state.notice = "";
  try {
    const data = await api(`/api/jobs/${id}`);
    state.job = data.job;
    state.view = "jobs";
    render();
  } catch (err) {
    state.error = err.message;
    render();
  }
}

async function act(path, body) {
  state.busy = true;
  state.error = "";
  try {
    const data = await api(path, { method: "POST", body: body || {} });
    state.job = data.job;
    state.notice = "Saved.";
  } catch (err) {
    state.error = err.message;
  } finally {
    state.busy = false;
    render();
  }
}

async function onSignIn(e) {
  e.preventDefault();
  const form = new FormData(e.target);
  state.busy = true;
  state.error = "";
  renderLock();
  try {
    const data = await api("/api/session", {
      method: "POST",
      body: { crewName: form.get("crewName"), pin: form.get("pin") },
    });
    state.crew = data.crew;
    state.view = "jobs";
    await loadJobs();
  } catch (err) {
    state.error = err.message;
    state.busy = false;
    renderLock();
  }
}

async function onSignOut() {
  await api("/api/session", { method: "DELETE" });
  state.crew = null;
  state.jobs = [];
  state.job = null;
  state.notice = "";
  render();
}

function gps() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve({ lat: null, lng: null, accuracy: null, reason: "GPS unavailable on this device" });
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy, reason: "" }),
      () => resolve({ lat: null, lng: null, accuracy: null, reason: "Crew declined GPS; checked in without coordinates" }),
      { enableHighAccuracy: true, timeout: 8000 }
    );
  });
}

async function onCheckIn() {
  state.busy = true;
  render();
  const body = await gps();
  await act(`/api/jobs/${state.job.id}/check-in`, body);
}

async function submitAsset(jobId, formEl) {
  const form = new FormData(formEl);
  await api(`/api/jobs/${jobId}/assets`, {
    method: "POST",
    body: {
      category: form.get("category"),
      serialNumber: form.get("serialNumber"),
      assetTag: form.get("assetTag"),
      manufacturer: form.get("manufacturer"),
      model: form.get("model"),
      condition: form.get("condition"),
      destructionMethod: form.get("destructionMethod"),
      dataBearing: form.get("dataBearing") === "on",
      notes: form.get("notes"),
    },
  }).then((data) => {
    state.job = data.job;
  });
}

async function onAsset(e) {
  e.preventDefault();
  try {
    await submitAsset(state.job.id, e.target);
    state.notice = "Device logged.";
    state.error = "";
  } catch (err) {
    state.error = err.message;
  }
  render();
}

async function deleteAsset(id) {
  try {
    const data = await api(`/api/jobs/${state.job.id}/assets/${id}`, { method: "DELETE" });
    state.job = data.job;
    state.notice = "Device removed.";
  } catch (err) {
    state.error = err.message;
  }
  render();
}

async function onSeal(e) {
  e.preventDefault();
  const form = new FormData(e.target);
  await act(`/api/jobs/${state.job.id}/seals`, { code: form.get("code"), location: form.get("location") });
}

async function onPhoto(e) {
  e.preventDefault();
  const form = new FormData(e.target);
  try {
    const data = await api(`/api/jobs/${state.job.id}/photos`, { method: "POST", body: form });
    state.job = data.job;
    state.notice = "Photo uploaded.";
    state.error = "";
  } catch (err) {
    state.error = err.message;
  }
  render();
}

let sigPad = null;

function setupSignature() {
  const canvas = document.getElementById("sig");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.strokeStyle = "#1a1f17";
  ctx.lineWidth = 2;
  ctx.lineCap = "round";
  let drawing = false;
  const pt = (ev) => {
    const r = canvas.getBoundingClientRect();
    const src = ev.touches ? ev.touches[0] : ev;
    return { x: ((src.clientX - r.left) / r.width) * canvas.width, y: ((src.clientY - r.top) / r.height) * canvas.height };
  };
  const start = (ev) => {
    drawing = true;
    const p = pt(ev);
    ctx.beginPath();
    ctx.moveTo(p.x, p.y);
    ev.preventDefault();
  };
  const move = (ev) => {
    if (!drawing) return;
    const p = pt(ev);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    ev.preventDefault();
  };
  const end = () => {
    drawing = false;
  };
  canvas.addEventListener("mousedown", start);
  canvas.addEventListener("mousemove", move);
  window.addEventListener("mouseup", end);
  canvas.addEventListener("touchstart", start, { passive: false });
  canvas.addEventListener("touchmove", move, { passive: false });
  canvas.addEventListener("touchend", end);
  sigPad = canvas;
  document.getElementById("clear-sig")?.addEventListener("click", () => ctx.clearRect(0, 0, canvas.width, canvas.height));
}

async function onAck(e) {
  e.preventDefault();
  const form = new FormData(e.target);
  const blank = document.createElement("canvas");
  blank.width = sigPad.width;
  blank.height = sigPad.height;
  if (sigPad.toDataURL() === blank.toDataURL()) {
    state.error = "Ask the client to sign before saving.";
    render();
    return;
  }
  await act(`/api/jobs/${state.job.id}/acknowledge`, {
    signerName: form.get("signerName"),
    signerRole: form.get("signerRole"),
    signatureDataUrl: sigPad.toDataURL("image/png"),
  });
}

async function onComplete(e) {
  e.preventDefault();
  const form = new FormData(e.target);
  await act(`/api/jobs/${state.job.id}/complete`, { overrideNote: form.get("overrideNote") || "" });
  if (!state.error) {
    state.notice = "Collection closed. Chain of custody is on the job.";
  }
}

boot();
