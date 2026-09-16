/* CircuitLoop persistence — talks to the FastAPI store the field UI mutates. */
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

  function applyState(state) {
    if (!state || typeof state !== "object") return;
    Object.keys(DB).forEach((k) => delete DB[k]);
    Object.assign(DB, state);
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
    clearTimeout(persistTimer);
    persistTimer = setTimeout(persistNow, 400);
  }

  async function hydrateFromServer() {
    const data = await api("GET", "/api/state?ts=" + Date.now());
    if (data.state && Array.isArray(data.state.projects)) {
      applyState(data.state);
      return true;
    }
    return false;
  }

  async function pullIfNewer() {
    if (!ready || persistInFlight || applyingRemote) return false;
    try {
      const data = await api("GET", "/api/state?ts=" + Date.now());
      const remote = data.state;
      if (!remote || !Array.isArray(remote.projects)) return false;
      const remoteRev = Number(remote._rev || 0);
      const localRev = Number(DB._rev || 0);
      if (remoteRev > localRev) {
        applyState(remote);
        refreshView();
        return true;
      }
    } catch (e) {}
    return false;
  }

  function isStaleConflict(err) {
    if (!err) return false;
    if (err.status === 409) return true;
    return /newer copy of the register/i.test(String(err.message || ""));
  }

  function rosterKey(state) {
    const ids = (list) => (list || []).map((row) => row && row.id).filter(Boolean).join(",");
    return ids(state.projects) + "|" + ids(state.users) + "|" + ids(state.assets);
  }

  async function writeState() {
    if (typeof DB === "undefined") return;
    const revAtSend = DB._rev;
    const before = rosterKey(DB);
    const data = await api("PUT", "/api/state", { state: DB });
    if (!data.state) return;
    if (revAtSend == null || DB._rev === revAtSend) {
      applyState(data.state);
      if (rosterKey(data.state) !== before) refreshView();
      return;
    }
    // Local edits landed while the PUT was in flight — keep them, take the new rev.
    DB._rev = data.state._rev;
    DB._savedAt = data.state._savedAt;
    persistSoon();
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
        await writeState();
      } catch (err) {
        if (isStaleConflict(err)) {
          if (err.payload && err.payload.state) applyState(err.payload.state);
          else {
            try {
              await hydrateFromServer();
            } catch (e) {}
          }
          refreshView();
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

  const origLogin = window.login;
  window.login = function (uid) {
    origLogin(uid);
    api("POST", "/api/session", { userId: uid }).catch(() => {});
    pullIfNewer();
  };

  const origLogout = window.logout;
  window.logout = function () {
    origLogout();
    api("DELETE", "/api/session").catch(() => {});
  };

  const origRerender = window.rerender;
  window.rerender = function () {
    persistSoon();
    origRerender();
  };

  const origShow = window.show;
  window.show = function (v) {
    origShow(v);
  };

  if (window.BLANCCO && BLANCCO.fetchBySerial) {
    const origFetch = BLANCCO.fetchBySerial.bind(BLANCCO);
    BLANCCO.fetchBySerial = async function (serial, category) {
      const cfg = DB.blanccoConfig || {};
      if (cfg.mode === "Live") {
        try {
          return await api("POST", "/api/blancco/lookup", { serial, category });
        } catch (err) {
          return { ok: false, error: err.message };
        }
      }
      return origFetch(serial, category);
    };
  }

  window.addEventListener("beforeunload", () => {
    if (!ready || typeof DB === "undefined" || DB._rev == null) return;
    if (persistInFlight) return;
    try {
      fetch("/api/state", {
        method: "PUT",
        cache: "no-store",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: DB }),
        keepalive: true,
      });
    } catch (e) {}
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") pullIfNewer();
  });
  window.addEventListener("pageshow", () => {
    pullIfNewer();
  });

  async function bootFromServer() {
    let hydrated = false;
    try {
      hydrated = await hydrateFromServer();
      // Only write the compiled demo seed when the server file is truly empty.
      if (!hydrated) {
        await persistNow();
      }
    } catch (err) {
      if (typeof toast === "function") toast(err.message);
      if (typeof renderLogin === "function") renderLogin();
      return;
    }
    let sessionUser = null;
    try {
      const sess = await api("GET", "/api/session");
      sessionUser = sess.user;
    } catch (e) {}
    if (sessionUser && DB.users && DB.users.some((u) => u.id === sessionUser.id && u.active !== false)) {
      origLogin(sessionUser.id);
    } else if (typeof renderLogin === "function") {
      renderLogin();
    }
    ready = true;
  }

  bootFromServer();
})();
