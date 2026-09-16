/* CircuitLoop persistence — talks to the FastAPI store the field UI mutates. */
(function () {
  const api = (method, path, body) =>
    fetch(path, {
      method,
      credentials: "include",
      headers: body ? { "Content-Type": "application/json" } : {},
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
  let ready = false;

  function applyState(state) {
    if (!state || typeof state !== "object") return;
    Object.keys(DB).forEach((k) => delete DB[k]);
    Object.assign(DB, state);
  }

  function persistSoon() {
    if (!ready) return;
    clearTimeout(persistTimer);
    persistTimer = setTimeout(persistNow, 400);
  }

  async function hydrateFromServer() {
    const data = await api("GET", "/api/state");
    if (data.state && Array.isArray(data.state.projects)) {
      applyState(data.state);
      return true;
    }
    return false;
  }

  async function persistNow() {
    if (typeof DB === "undefined") return;
    persistTimer = null;
    try {
      const data = await api("PUT", "/api/state", { state: DB });
      if (data.state) applyState(data.state);
    } catch (err) {
      if (err.status === 409) {
        try {
          await hydrateFromServer();
        } catch (e) {}
        if (typeof toast === "function") {
          toast("Register was updated elsewhere. Reloaded the saved copy.");
        }
        if (typeof origRerender === "function") origRerender();
        return;
      }
      if (typeof toast === "function") toast("Could not save to CircuitLoop: " + err.message);
    }
  }

  const origLogin = window.login;
  window.login = function (uid) {
    origLogin(uid);
    api("POST", "/api/session", { userId: uid }).catch(() => {});
    persistSoon();
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
    persistSoon();
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
    if (!ready || typeof DB === "undefined") return;
    try {
      fetch("/api/state", {
        method: "PUT",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ state: DB }),
        keepalive: true,
      });
    } catch (e) {}
  });

  async function bootFromServer() {
    let hydrated = false;
    try {
      hydrated = await hydrateFromServer();
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
