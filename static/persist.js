/* CircuitLoop persistence — session auth + per-record sync. Never writes the demo seed. */
(function () {
  const api = (method, path, body) => {
    const ctrl = new AbortController();
    const timer = setTimeout(function () {
      ctrl.abort();
    }, 20000);
    return fetch(path, {
      method,
      cache: "no-store",
      credentials: "include",
      signal: ctrl.signal,
      headers: {
        Accept: "application/json",
        "Cache-Control": "no-cache",
        ...(body ? { "Content-Type": "application/json" } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          const detail = data.error || data.detail;
          const err = new Error(detail || "Request failed (" + res.status + ")");
          err.status = res.status;
          err.payload = data;
          throw err;
        }
        return data;
      })
      .catch((err) => {
        if (err && err.name === "AbortError") {
          const timeout = new Error("Sign-in timed out. Check your connection and try again.");
          timeout.status = 0;
          throw timeout;
        }
        throw err;
      })
      .finally(function () {
        clearTimeout(timer);
      });
  };

  function clone(v) {
    return JSON.parse(JSON.stringify(v));
  }

  let persistTimer = null;
  let persistInFlight = null;
  let persistQueued = false;
  let ready = false;
  let applyingRemote = false;
  let lastSnap = null;
  let dirty = false;
  const dbSeed = typeof DB !== "undefined" ? clone(DB) : {};
  const SIGNED_OUT_KEY = "clSignedOut";

  function readSignedOut() {
    try {
      if (sessionStorage.getItem(SIGNED_OUT_KEY) === "1") return true;
    } catch (err) {}
    try {
      if (localStorage.getItem(SIGNED_OUT_KEY) === "1") return true;
    } catch (err) {}
    return false;
  }

  function markClientSignedOut() {
    ready = false;
    try {
      sessionStorage.setItem(SIGNED_OUT_KEY, "1");
    } catch (err) {}
    try {
      localStorage.setItem(SIGNED_OUT_KEY, "1");
    } catch (err) {}
  }

  function clearClientSignedOut() {
    try {
      sessionStorage.removeItem(SIGNED_OUT_KEY);
    } catch (err) {}
    try {
      localStorage.removeItem(SIGNED_OUT_KEY);
    } catch (err) {}
  }

  function forceLoginScreen() {
    ready = false;
    try {
      window.__clUser = null;
    } catch (err) {}
    try {
      window.ME = null;
    } catch (err) {}
    try {
      ME = null;
    } catch (err) {}
    try {
      if (typeof window.leaveField === "function") window.leaveField();
    } catch (err) {}
    const loginview = document.getElementById("loginview");
    const appview = document.getElementById("appview");
    if (appview) appview.classList.add("hide");
    if (loginview) loginview.classList.remove("hide");
    showAuth();
  }

  async function liveSessionUser() {
    try {
      const sess = await api("GET", "/api/session");
      return sess && sess.user ? sess.user : null;
    } catch (err) {
      return null;
    }
  }

  async function revokeServerSession() {
    try {
      await fetch("/api/session", {
        method: "DELETE",
        cache: "no-store",
        credentials: "include",
        keepalive: true,
        headers: { Accept: "application/json" },
      });
    } catch (err) {}
  }

  function ensureLists() {
    if (typeof DB === "undefined") return;
    ["users", "clients", "projects", "assets", "manifests", "categories"].forEach(function (k) {
      if (!Array.isArray(DB[k])) DB[k] = Array.isArray(dbSeed[k]) ? clone(dbSeed[k]) : [];
    });
    if (!DB.seq || typeof DB.seq !== "object") DB.seq = clone(dbSeed.seq || { asset: 1, usn: 50001, project: 1001, client: 1, user: 3, blancco: 1, manifest: 1 });
    if (!DB.company || typeof DB.company !== "object") DB.company = clone(dbSeed.company || { name: "Urbeno Technologies Pvt Ltd", brand: "CircuitLoop Field", currency: "INR" });
    if (!DB.testParams || typeof DB.testParams !== "object") DB.testParams = clone(dbSeed.testParams || {});
    if (!DB.specFields || typeof DB.specFields !== "object") DB.specFields = clone(dbSeed.specFields || {});
    if (!Array.isArray(DB.blanccoCategories)) DB.blanccoCategories = clone(dbSeed.blanccoCategories || ["Laptop"]);
  }

  function applyState(state) {
    if (!state || typeof state !== "object") return;
    Object.keys(DB).forEach((k) => delete DB[k]);
    Object.assign(DB, dbSeed, state);
    ensureLists();
    lastSnap = clone(DB);
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
    if (data.state && typeof data.state === "object") {
      applyState(data.state);
      return Array.isArray(DB.projects);
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

  function copyText(text, btn) {
    const label = btn && btn.textContent;
    const done = function () {
      if (btn) {
        btn.textContent = "Copied";
        setTimeout(function () {
          btn.textContent = label;
        }, 1400);
      }
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () {});
    }
  }

  function inviteFromLocation() {
    let search = "";
    let hash = "";
    try {
      search = String(window.location.search || "").replace(/^\?/, "");
    } catch (err) {}
    try {
      hash = String(window.location.hash || "").replace(/^#/, "");
    } catch (err) {}
    const query = new URLSearchParams(search);
    const frag = new URLSearchParams(hash.replace(/^[&#]/, ""));
    return {
      email: String(query.get("email") || frag.get("email") || "").trim().toLowerCase(),
      invite: String(query.get("invite") || frag.get("invite") || "").trim(),
    };
  }

  function drawEnrollQr(uri, host) {
    if (!host) return;
    host.innerHTML = "";
    if (!uri) {
      host.innerHTML =
        '<div class="warn" style="margin:0">No otpauth URL — type the secret into your authenticator.</div>';
      return;
    }
    if (typeof qrcode !== "function") {
      host.innerHTML =
        '<div class="warn" style="margin:0">QR library did not load — copy the secret or otpauth URL below.</div>';
      return;
    }
    try {
      const qr = qrcode(0, "M");
      qr.addData(uri);
      qr.make();
      host.innerHTML = qr.createSvgTag(5, 2);
      const svg = host.querySelector("svg");
      if (svg) {
        svg.setAttribute("role", "img");
        svg.setAttribute("aria-label", "CircuitLoop authenticator QR code");
        svg.style.width = "168px";
        svg.style.height = "168px";
        svg.style.maxWidth = "100%";
        svg.style.display = "block";
      }
    } catch (err) {
      host.innerHTML =
        '<div class="warn" style="margin:0">Could not draw QR — copy the secret or otpauth URL below.</div>';
    }
  }

  function showAuth(prefill) {
    const box = document.getElementById("loginusers");
    if (!box) return;
    const emailVal = (prefill && prefill.email) || "";
    box.innerHTML = "";
    const form = el(
      '<form id="authform" novalidate>' +
        '<label class="f">Work email</label>' +
        '<input id="auth_email" type="email" autocomplete="username" required placeholder="you@urbeno.in">' +
        '<div id="auth_hint" class="warn" style="margin-top:12px">If you already enrolled, continue with your authenticator. First sign-in needs an invite a Super Admin sent you — not a QR from this card.</div>' +
        '<div id="auth_extra"></div>' +
        '<label class="f" style="margin-top:12px">Authenticator invite (first sign-in)</label>' +
        '<input id="auth_invite" type="text" autocomplete="off" placeholder="Paste the invite token">' +
        '<button class="btn btn-p" type="submit" style="width:100%;justify-content:center;margin-top:14px" id="auth_go">Continue with authenticator</button>' +
        '<button class="btn" type="button" style="width:100%;justify-content:center;margin-top:8px" id="auth_email_btn" disabled>Email me a code</button>' +
        '<div class="muted" id="auth_msg" style="font-size:12px;margin-top:12px"></div>' +
        "</form>"
    );
    box.appendChild(form);
    const email = form.querySelector("#auth_email");
    email.value = emailVal;
    const extra = form.querySelector("#auth_extra");
    const msg = form.querySelector("#auth_msg");
    const go = form.querySelector("#auth_go");
    const emailBtn = form.querySelector("#auth_email_btn");
    const hint = form.querySelector("#auth_hint");
    const inviteInput = form.querySelector("#auth_invite");
    const fromLink = inviteFromLocation();
    if (fromLink.email && !email.value) email.value = fromLink.email;
    if (fromLink.invite && inviteInput) inviteInput.value = fromLink.invite;
    let phase = "pick";
    let emailOtpLive = false;
    let emailHint = "";

    function setHint() {
      if (!hint) return;
      if (emailOtpLive) {
        hint.className = emailHint && /Railway|RESEND|blocked/i.test(emailHint) ? "warn" : "info";
        hint.style.marginTop = "12px";
        hint.textContent =
          emailHint ||
          "Choose authenticator (Google Authenticator / Authy / 1Password) or email a 6-digit code.";
        emailBtn.disabled = false;
      } else {
        hint.className = "warn";
        hint.style.marginTop = "12px";
        hint.textContent =
          emailHint ||
          "Authenticator is the working factor if you already enrolled. First-time setup uses a Super Admin invite, not a QR from this card.";
        emailBtn.disabled = true;
      }
    }

    api("GET", "/api/health")
      .then(function (h) {
        emailOtpLive = !!(h && h.emailOtp);
        emailHint = (h && h.emailDelivery && h.emailDelivery.hint) || "";
        setHint();
      })
      .catch(function () {
        emailOtpLive = false;
        setHint();
      });

    function showError(text) {
      msg.textContent = text || "Sign-in failed.";
      msg.style.color = "var(--red)";
    }

    function showInfo(text) {
      msg.style.color = "";
      msg.textContent = text || "";
    }

    function setBusy(on, label) {
      go.disabled = !!on;
      emailBtn.disabled = on ? true : !emailOtpLive || emailBtn.style.display === "none";
      if (label) go.textContent = label;
    }

    function showPrimaryActions(showEmail) {
      go.style.display = "";
      emailBtn.style.display = showEmail ? "" : "none";
    }

    function hideHint() {
      if (hint) hint.style.display = "none";
    }

    function renderEnroll(pending) {
      hideHint();
      extra.innerHTML =
        '<div class="info" style="margin-top:12px">Scan this QR in <b>Google Authenticator</b>, Authy, or 1Password. Keep one CircuitLoop entry — extra entries from earlier tries will not match.</div>' +
        '<div id="auth_qr" style="display:flex;justify-content:center;margin:12px 0;padding:12px;background:#fff;border:1px solid var(--line);border-radius:10px"></div>' +
        '<label class="f">Secret (type if you cannot scan)</label>' +
        '<div class="flex" style="gap:6px"><input id="auth_secret" readonly style="font-family:ui-monospace,Menlo,monospace"><button type="button" class="btn btn-sm" id="auth_copy_secret">Copy</button></div>' +
        '<label class="f">otpauth URL</label>' +
        '<div class="muted" style="font-size:11px;margin:6px 0 8px;word-break:break-all" id="auth_otpauth"></div>' +
        '<button type="button" class="btn btn-sm" id="auth_copy_otpauth" style="margin-bottom:8px">Copy otpauth URL</button>' +
        '<label class="f">Authenticator code</label>' +
        '<input id="auth_code" name="otp" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="6-digit code">';
      extra.querySelector("#auth_secret").value = pending.secret || "";
      extra.querySelector("#auth_otpauth").textContent = pending.otpauth || "";
      drawEnrollQr(pending.otpauth, extra.querySelector("#auth_qr"));
      extra.querySelector("#auth_copy_secret").addEventListener("click", function () {
        copyText(pending.secret || "", extra.querySelector("#auth_copy_secret"));
      });
      extra.querySelector("#auth_copy_otpauth").addEventListener("click", function () {
        copyText(pending.otpauth || "", extra.querySelector("#auth_copy_otpauth"));
      });
      go.textContent = "Confirm authenticator";
      showPrimaryActions(false);
      showInfo(pending.message || "");
      extra.querySelector("#auth_code").focus();
    }

    function renderCode(pending, kind) {
      hideHint();
      const preview = pending && String(pending.previewCode || "").replace(/\D/g, "").slice(0, 8);
      extra.innerHTML =
        (preview
          ? '<div class="okbox" style="margin-top:12px">Preview only — email was not sent. Code: <b id="auth_preview_code" style="font-family:ui-monospace,Menlo,monospace;letter-spacing:.16em;font-size:22px">' +
            preview +
            "</b></div>"
          : "") +
        '<label class="f" style="margin-top:12px">' +
        (kind === "email" ? "Email code" : "Authenticator code") +
        "</label>" +
        '<input id="auth_code" name="otp" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="6-digit code">' +
        (kind === "email"
            ? '<button type="button" class="btn" id="auth_resend" style="width:100%;justify-content:center;margin-top:10px">Email a new code</button>'
            : "");
      if (preview) extra.querySelector("#auth_code").value = preview;
      const resend = extra.querySelector("#auth_resend");
      if (resend) {
        resend.addEventListener("click", function () {
          startWith("email");
        });
      }
      go.textContent = "Verify and sign in";
      showPrimaryActions(false);
      showInfo(pending.message || "");
      extra.querySelector("#auth_code").focus();
    }

    async function startWith(method) {
      const addr = String(email.value || "").trim().toLowerCase();
      if (!addr) {
        showError("Enter your Urbeno email.");
        return;
      }
      setBusy(true, method === "email" ? "Sending email code…" : "Continuing…");
      try {
        const pending = await api("POST", "/api/auth/start", {
          email: addr,
          method: method,
          inviteToken: (inviteInput && inviteInput.value) || fromLink.invite || "",
        });
        phase = pending.factor || "totp";
        extra.innerHTML = "";
        if (phase === "enroll") renderEnroll(pending);
        else renderCode(pending, phase);
      } catch (err) {
        showError(err.message);
        emailBtn.disabled = !emailOtpLive;
      } finally {
        setBusy(false);
        if (phase === "enroll") go.textContent = "Confirm authenticator";
        else if (phase === "pick") go.textContent = "Continue with authenticator";
        else go.textContent = "Verify and sign in";
      }
    }

    form.addEventListener("submit", async function (ev) {
      ev.preventDefault();
      ev.stopPropagation();
      const addr = String(email.value || "").trim().toLowerCase();
      if (!addr) {
        showError("Enter your Urbeno email.");
        return;
      }
      if (phase === "pick") {
        await startWith("totp");
        return;
      }
      const code = String((extra.querySelector("#auth_code") || {}).value || "").trim().replace(/\s+/g, "");
      if (!/^\d{6,8}$/.test(code)) {
        showError("Enter the 6-digit code from your authenticator (or email).");
        return;
      }
      const prevLabel = go.textContent;
      setBusy(true, "Signing in…");
      try {
        const data = await api("POST", "/api/auth/verify", { email: addr, code: code });
        if (!data || !data.user || !data.user.id) {
          throw new Error("Sign-in did not return a session user.");
        }
        await afterSignIn(data.user, showError);
      } catch (err) {
        showError(err.message);
      } finally {
        setBusy(false, prevLabel || "Verify and sign in");
      }
    });

    emailBtn.addEventListener("click", async function () {
      if (!emailOtpLive) {
        showError("Email OTP is not configured. Use authenticator.");
        return;
      }
      await startWith("email");
    });

    if (fromLink.invite && email.value) {
      startWith("totp");
    }
  }

  function sessionUserFrom(payload) {
    const raw = payload && (payload.user || payload);
    if (!raw || typeof raw !== "object") return null;
    const id = raw.id || raw.userId;
    if (!id) return null;
    return {
      id: id,
      userId: id,
      name: raw.name || "",
      email: raw.email || "",
      role: /super\s*admin/i.test(String(raw.role || "")) ? "Super Admin" : "Field Engineer",
      phone: raw.phone || "",
      active: raw.active !== false,
    };
  }

  function ensureUserRow(user) {
    if (typeof DB === "undefined") return;
    if (!Array.isArray(DB.users)) DB.users = [];
    let row = DB.users.find(function (u) {
      return u && u.id === user.id;
    });
    if (!row) {
      row = {
        id: user.id,
        name: user.name,
        email: user.email,
        role: user.role,
        phone: user.phone || "",
        active: true,
      };
      DB.users.push(row);
    } else {
      if (user.name) row.name = user.name;
      if (user.email) row.email = user.email;
      if (user.role) row.role = user.role;
    }
  }

  function openFieldApp(user) {
    const session = sessionUserFrom(user);
    if (!session) return;
    try {
      window.__clUser = session;
    } catch (err) {}
    ensureUserRow(session);
    if (typeof window.enterField === "function") {
      window.enterField(session);
      return;
    }
    const fn = window.__circuitloopLogin || window.login;
    if (typeof fn === "function") {
      try {
        fn(session.id, session);
      } catch (err) {
        if (typeof toast === "function") toast(err.message || String(err));
      }
    }
    try {
      ME = session;
    } catch (err) {}
    const loginview = document.getElementById("loginview");
    const appview = document.getElementById("appview");
    if (loginview) loginview.classList.add("hide");
    if (appview) appview.classList.remove("hide");
    const who = document.getElementById("whoami");
    if (who) who.textContent = (session.name || "") + " · " + (session.role || "");
    const av = document.getElementById("whoavatar");
    if (av) {
      av.textContent =
        String(session.name || "U")
          .split(" ")
          .map(function (p) {
            return p.charAt(0);
          })
          .join("")
          .slice(0, 2) || "U";
    }
    const fab = document.getElementById("fab");
    if (fab) fab.classList.remove("hide");
    if (typeof buildNav === "function") {
      try {
        buildNav();
      } catch (err) {}
    }
    if (typeof show === "function") {
      try {
        show(session.role === "Field Engineer" ? "testing" : "dashboard");
      } catch (err) {
        const content = document.getElementById("content");
        if (content) {
          content.innerHTML =
            '<div class="errbox">Could not open Field: ' +
            String((err && err.message) || err) +
            "</div>";
        }
      }
    }
  }

  async function afterSignIn(user, onError) {
    let sessionUser = sessionUserFrom(user);
    if (!sessionUser) {
      try {
        const sess = await api("GET", "/api/session");
        sessionUser = sessionUserFrom(sess);
      } catch (err) {}
    }
    if (!sessionUser) {
      throw new Error("Sign-in succeeded but /api/session did not return your account. Refresh and try again.");
    }
    let hydrateErr = null;
    try {
      const ok = await hydrateFromServer();
      if (!ok) hydrateErr = new Error("Register did not load after sign-in.");
    } catch (err) {
      hydrateErr = err;
    }
    if (hydrateErr && hydrateErr.status === 401) {
      throw new Error(
        "Signed in but the browser did not keep the session cookie. Allow cookies for this site, then try again."
      );
    }
    openFieldApp(sessionUser);
    clearClientSignedOut();
    const app = document.getElementById("appview");
    if (!app || app.classList.contains("hide")) {
      const fail = new Error("Signed in but the console did not open. Refresh and try again.");
      if (typeof onError === "function") onError(fail.message);
      throw fail;
    }
    ready = true;
    if (hydrateErr && typeof toast === "function") toast(hydrateErr.message);
  }

  const pageLogin = window.login;
  window.__circuitloopLogin = pageLogin;
  window.login = function (uid, fallback) {
    if (typeof window.enterField === "function") {
      const row = fallback && typeof fallback === "object" ? fallback : { id: uid };
      return window.enterField(row);
    }
    if (typeof pageLogin === "function") return pageLogin(uid, fallback);
    const user = sessionUserFrom(fallback) || sessionUserFrom({ id: uid });
    if (user) openFieldApp(user);
  };

  const origLogout = window.logout;
  window.logout = function () {
    markClientSignedOut();
    try {
      if (typeof origLogout === "function") origLogout();
    } catch (err) {}
    forceLoginScreen();
    return revokeServerSession().then(function () {
      forceLoginScreen();
    });
  };

  const origRerender = window.rerender;
  window.rerender = function () {
    persistSoon();
    if (typeof origRerender === "function") origRerender();
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
    if (document.visibilityState !== "visible") return;
    if (readSignedOut()) {
      forceLoginScreen();
      return;
    }
    pullIfNewer();
  });
  window.addEventListener("pageshow", function () {
    if (readSignedOut()) {
      forceLoginScreen();
      revokeServerSession();
      return;
    }
    liveSessionUser().then(function (user) {
      if (readSignedOut()) {
        forceLoginScreen();
        revokeServerSession();
        return;
      }
      if (!user) {
        forceLoginScreen();
        return;
      }
      pullIfNewer();
    });
  });

  window.CircuitLoopPersist = {
    flush: persistNow,
    soon: persistSoon,
    api: api,
    showAuth: showAuth,
    hydrate: hydrateFromServer,
    applyState: applyState,
    drawEnrollQr: drawEnrollQr,
  };

  async function bootFromServer() {
    const signedOut = readSignedOut();
    if (signedOut) {
      await revokeServerSession();
      forceLoginScreen();
      return;
    }
    try {
      const health = await api("GET", "/api/health");
      if (health && health.previewLogin && !readSignedOut()) {
        await api("POST", "/api/preview/login");
      }
    } catch (e) {}
    if (readSignedOut()) {
      await revokeServerSession();
      forceLoginScreen();
      return;
    }
    const sessionUser = await liveSessionUser();
    if (!sessionUser) {
      forceLoginScreen();
      return;
    }
    try {
      await hydrateFromServer();
    } catch (err) {
      if (typeof toast === "function") toast(err.message);
    }
    const user = sessionUserFrom(sessionUser);
    if (!user) {
      forceLoginScreen();
      return;
    }
    openFieldApp(user);
    ready = true;
    function paintLive(tries) {
      const dest = user.role === "Field Engineer" ? "testing" : "dashboard";
      if (typeof show !== "function") {
        if (tries > 0) setTimeout(function () { paintLive(tries - 1); }, 40);
        return;
      }
      try {
        show(dest);
      } catch (err) {}
      const content = document.getElementById("content");
      const html = content ? String(content.innerHTML || "") : "";
      const dummy = /Live counts load/.test(html) || /Use the sidebar for Dashboard/.test(html);
      if (dummy && tries > 0) setTimeout(function () { paintLive(tries - 1); }, 40);
    }
    paintLive(50);
  }

  bootFromServer();
})();
