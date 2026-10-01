/* CircuitLoop persistence — session auth + per-record sync. Never writes the demo seed. */
(function () {
  const api = (method, path, body) =>
    fetch(path, {
      method,
      cache: "no-store",
      credentials: "include",
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-cache",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    }).then(async (res) => {
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const err = new Error(data.error || data.detail || "Request failed (" + res.status + ")");
        err.status = res.status;
        err.payload = data;
        throw err;
      }
      return data;
    });

  let persistTimer = null;
  let persistInFlight = null;
  let persistQueued = false;
  let ready = false;
  let applyingRemote = false;
  let lastSnap = null;
  let dirty = false;

  function clone(v) {
    return JSON.parse(JSON.stringify(v));
  }

  function applyState(state) {
    if (!state || typeof state !== "object") return;
    Object.keys(DB).forEach((k) => delete DB[k]);
    Object.assign(DB, state);
    lastSnap = clone(state);
    dirty = false;
  }

  function refreshView() {
    if (typeof origRerender !== "function") return;
    applyingRemote = true;
    try {
      origRerender();
    } finally {
      applyingRemote = false;
    }
  }

  function persistSoon() {
    if (!ready || applyingRemote) return;
    dirty = true;
    clearTimeout(persistTimer);
    persistTimer = setTimeout(persistNow, 250);
  }

  function recordMap(list) {
    const out = {};
    (list || []).forEach((row) => {
      if (row && row.id) out[row.id] = row;
    });
    return out;
  }

  function changedRows(localList, remoteList) {
    const remote = recordMap(remoteList);
    const out = [];
    (localList || []).forEach((row) => {
      if (!row || !row.id) return;
      const prev = remote[row.id];
      if (!prev || JSON.stringify(prev) !== JSON.stringify(row)) out.push(row);
    });
    return out;
  }

  function mastersChanged() {
    if (!lastSnap) return true;
    const keys = ["company", "categories", "testParams", "specFields", "blanccoCategories", "blanccoConfig"];
    return keys.some((k) => JSON.stringify(DB[k] || null) !== JSON.stringify(lastSnap[k] || null));
  }

  async function hydrateFromServer() {
    const data = await api("GET", "/api/state?ts=" + Date.now());
    if (data.state && Array.isArray(data.state.projects)) {
      applyState(data.state);
      return true;
    }
    return false;
  }

  async function writeChanged() {
    if (typeof DB === "undefined") return;
    const upserts = {};
    upserts.assets = changedRows(DB.assets, lastSnap && lastSnap.assets);
    upserts.clients = changedRows(DB.clients, lastSnap && lastSnap.clients);
    upserts.projects = changedRows(DB.projects, lastSnap && lastSnap.projects);
    upserts.users = changedRows(DB.users, lastSnap && lastSnap.users);
    upserts.manifests = changedRows(DB.manifests, lastSnap && lastSnap.manifests);
    if (mastersChanged()) {
      upserts.company = DB.company;
      upserts.categories = DB.categories;
      upserts.testParams = DB.testParams;
      upserts.specFields = DB.specFields;
      upserts.blanccoCategories = DB.blanccoCategories;
      if (DB.blanccoConfig) {
        const cfg = Object.assign({}, DB.blanccoConfig);
        delete cfg.apiKey;
        upserts.blanccoConfig = cfg;
      }
    }
    const has =
      (upserts.assets && upserts.assets.length) ||
      (upserts.clients && upserts.clients.length) ||
      (upserts.projects && upserts.projects.length) ||
      (upserts.users && upserts.users.length) ||
      (upserts.manifests && upserts.manifests.length) ||
      mastersChanged();
    if (!has) {
      dirty = false;
      return;
    }
    const data = await api("POST", "/api/sync", { upserts: upserts });
    if (data.state) applyState(data.state);
    else dirty = false;
  }

  async function persistNow() {
    if (typeof DB === "undefined") return;
    persistTimer = null;
    if (persistInFlight) {
      persistQueued = true;
      return persistInFlight;
    }
    persistInFlight = (async () => {
      try {
        await writeChanged();
      } catch (err) {
        if (err.status === 409) {
          if (typeof toast === "function") toast("Not saved — " + (err.message || "a newer copy is on the server."));
          return;
        }
        if (err.status === 401) {
          if (typeof toast === "function") toast("Session expired — sign in again.");
          showAuth();
          return;
        }
        if (typeof toast === "function") toast("Could not save to CircuitLoop: " + err.message);
      }
    })();
    try {
      return await persistInFlight;
    } finally {
      persistInFlight = null;
      if (persistQueued) {
        persistQueued = false;
        persistNow();
      }
    }
  }

  async function pullIfNewer() {
    if (!ready || persistInFlight || applyingRemote) return false;
    if (dirty) {
      await persistNow();
    }
    try {
      const data = await api("GET", "/api/state?ts=" + Date.now());
      const remote = data.state;
      if (!remote || !Array.isArray(remote.projects)) return false;
      const remoteRev = Number(remote._rev || 0);
      const localRev = Number(DB._rev || 0);
      if (remoteRev > localRev) {
        if (dirty) {
          if (typeof toast === "function") toast("Server has a newer copy; keeping your unsaved edits until they save.");
          return false;
        }
        applyState(remote);
        refreshView();
        return true;
      }
    } catch (e) {}
    return false;
  }

  function el(html) {
    const d = document.createElement("div");
    d.innerHTML = html;
    return d.firstElementChild;
  }

  function showAuth(prefill) {
    const box = document.getElementById("loginusers");
    if (!box) return;
    const emailVal = (prefill && prefill.email) || "";
    box.innerHTML = "";
    const form = el(
      '<form id="authform">' +
        '<label class="f">Work email</label>' +
        '<input id="auth_email" type="email" autocomplete="username" required placeholder="you@urbeno.in">' +
        '<div id="auth_extra"></div>' +
        '<button class="btn btn-p" type="submit" style="width:100%;justify-content:center;margin-top:14px" id="auth_go">Continue</button>' +
        '<div class="muted" id="auth_msg" style="font-size:12px;margin-top:12px"></div>' +
        "</form>"
    );
    box.appendChild(form);
    const email = form.querySelector("#auth_email");
    email.value = emailVal;
    const extra = form.querySelector("#auth_extra");
    const msg = form.querySelector("#auth_msg");
    const go = form.querySelector("#auth_go");
    let phase = "email";
    let pending = null;

    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const addr = String(email.value || "").trim().toLowerCase();
      if (!addr) return;
      go.disabled = true;
      try {
        if (phase === "email") {
          pending = await api("POST", "/api/auth/start", { email: addr });
          phase = pending.factor;
          extra.innerHTML = "";
          if (phase === "enroll") {
            extra.innerHTML =
              '<div class="info" style="margin-top:12px">First-time setup: add <b>CircuitLoop</b> in Google Authenticator, Authy, or 1Password.</div>' +
              '<label class="f">Secret</label><input id="auth_secret" readonly>' +
              '<div class="muted" style="font-size:11px;margin:6px 0 8px;word-break:break-all" id="auth_otpauth"></div>' +
              '<label class="f">Authenticator code</label>' +
              '<input id="auth_code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="6-digit code">';
            extra.querySelector("#auth_secret").value = pending.secret || "";
            extra.querySelector("#auth_otpauth").textContent = pending.otpauth || "";
            go.textContent = "Confirm authenticator";
            msg.textContent = pending.message || "";
            extra.querySelector("#auth_code").focus();
          } else {
            extra.innerHTML =
              '<label class="f" style="margin-top:12px">' +
              (phase === "email" ? "Email code" : "Authenticator code") +
              "</label>" +
              '<input id="auth_code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="6-digit code">';
            go.textContent = "Verify and sign in";
            msg.textContent = pending.message || "";
            extra.querySelector("#auth_code").focus();
          }
        } else {
          const code = String((extra.querySelector("#auth_code") || {}).value || "").trim();
          const data = await api("POST", "/api/auth/verify", { email: addr, code: code });
          await afterSignIn(data.user);
        }
      } catch (err) {
        msg.textContent = err.message;
        msg.style.color = "var(--red)";
      } finally {
        go.disabled = false;
      }
    });
  }

  async function afterSignIn(user) {
    try {
      await hydrateFromServer();
    } catch (err) {
      if (typeof toast === "function") toast(err.message);
      return;
    }
    if (typeof origLogin === "function" && user && user.id) origLogin(user.id);
    ready = true;
  }

  const origLogin = window.login;
  window.login = function (uid) {
    origLogin(uid);
  };

  const origLogout = window.logout;
  window.logout = function () {
    origLogout();
    api("DELETE", "/api/session").catch(() => {});
    ready = false;
    showAuth();
  };

  const origRerender = window.rerender;
  window.rerender = function () {
    persistSoon();
    origRerender();
  };

  if (window.BLANCCO && BLANCCO.fetchBySerial) {
    BLANCCO.fetchBySerial = async function (serial, category, assetId) {
      try {
        return await api("POST", "/api/blancco/lookup", { serial: serial, category: category, assetId: assetId || "" });
      } catch (err) {
        return { ok: false, error: err.message };
      }
    };
  }

  window.addEventListener("beforeunload", () => {
    if (!ready || !dirty || typeof DB === "undefined") return;
    try {
      const upserts = { assets: changedRows(DB.assets, lastSnap && lastSnap.assets) };
      navigator.sendBeacon(
        "/api/sync",
        new Blob([JSON.stringify({ upserts: upserts })], { type: "application/json" })
      );
    } catch (e) {}
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") pullIfNewer();
  });
  window.addEventListener("pageshow", () => {
    pullIfNewer();
  });

  window.CircuitLoopPersist = {
    flush: persistNow,
    soon: persistSoon,
    api: api,
    showAuth: showAuth,
  };

  async function bootFromServer() {
    let sessionUser = null;
    try {
      const sess = await api("GET", "/api/session");
      sessionUser = sess.user;
    } catch (e) {}
    if (!sessionUser) {
      showAuth();
      ready = false;
      return;
    }
    try {
      await hydrateFromServer();
    } catch (err) {
      if (typeof toast === "function") toast(err.message);
      showAuth();
      return;
    }
    if (typeof origLogin === "function") origLogin(sessionUser.id);
    ready = true;
  }

  bootFromServer();
})();
