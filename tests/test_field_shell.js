#!/usr/bin/env node
/* Smoke the Field shell after a partial hydrate (missing masters / odd roles). */
const fs = require("fs");
const path = require("path");
const htmlPath = path.join(__dirname, "..", "static", "index.html");
const persistPath = path.join(__dirname, "..", "static", "persist.js");
const html = fs.readFileSync(htmlPath, "utf8");
const persist = fs.readFileSync(persistPath, "utf8");

function assert(cond, msg) {
  if (!cond) {
    console.error("fail:", msg);
    process.exit(1);
  }
}

assert(html.includes("function enterField("), "enterField in index");
assert(html.includes("function leaveField("), "leaveField in index");
assert(html.includes("function paintNav("), "paintNav in index");
assert(html.includes("persist.js?v=prod7"), "prod7 cache bust");
assert(persist.includes("Object.assign(DB, dbSeed, state)"), "applyState merges seed");
assert(persist.includes("window.enterField"), "persist calls enterField");
assert(persist.includes("window.leaveField"), "persist calls leaveField");
assert(persist.includes("DELETE") && persist.includes("/api/session"), "logout deletes session");

function fakeDom() {
  const ids = {};
  function el(tag, id) {
    const node = {
      id: id || "",
      tagName: String(tag).toUpperCase(),
      className: "",
      classList: {
        _c: new Set(),
        add(c) {
          this._c.add(c);
          node.className = Array.from(this._c).join(" ");
        },
        remove(c) {
          this._c.delete(c);
          node.className = Array.from(this._c).join(" ");
        },
        contains(c) {
          return this._c.has(c);
        },
        toggle(c, on) {
          if (on) this.add(c);
          else this.remove(c);
        },
      },
      innerHTML: "",
      textContent: "",
      style: {},
      children: [],
      querySelector() {
        return null;
      },
      querySelectorAll() {
        return [];
      },
    };
    if (id) ids[id] = node;
    return node;
  }
  const appview = el("div", "appview");
  appview.classList.add("hide");
  const loginview = el("div", "loginview");
  const nav = el("nav", "nav");
  const content = el("div", "content");
  const pagetitle = el("h1", "pagetitle");
  pagetitle.textContent = "Dashboard";
  const pagecrumb = el("div", "pagecrumb");
  const whoami = el("span", "whoami");
  const whoavatar = el("div", "whoavatar");
  const fab = el("button", "fab");
  fab.classList.add("hide");
  const bottombar = el("div", "bottombar");
  const toastBox = el("div", "toast");
  ids.appview = appview;
  ids.loginview = loginview;
  ids.nav = nav;
  ids.content = content;
  ids.pagetitle = pagetitle;
  ids.pagecrumb = pagecrumb;
  ids.whoami = whoami;
  ids.whoavatar = whoavatar;
  ids.fab = fab;
  ids.bottombar = bottombar;
  ids.toast = toastBox;
  ids.scrim = el("div", "scrim");
  return {
    getElementById(id) {
      return ids[id] || null;
    },
    querySelector(sel) {
      if (sel && sel.startsWith("#")) return ids[sel.slice(1)] || null;
      if (sel === ".sidebar") return el("aside");
      if (sel === ".nav a") return null;
      return null;
    },
    querySelectorAll(sel) {
      if (sel === ".nav a") return [];
      if (sel === "#content table") return [];
      return [];
    },
    createElement(tag) {
      const node = el(tag || "div");
      node.appendChild = function (child) {
        this.children.push(child);
        return child;
      };
      node.remove = function () {};
      return node;
    },
    _ids: ids,
  };
}

const documentRef = fakeDom();
documentRef.addEventListener = function () {};
documentRef.body = { appendChild() {} };
for (const node of Object.values(documentRef._ids)) {
  node.appendChild = function (child) {
    this.children.push(child);
    return child;
  };
  node.remove = function () {};
}
const windowRef = {
  innerWidth: 1280,
  scrollTo() {},
  addEventListener() {},
};

// Extract the inline script (first big app script, not persist).
const scripts = html.split("<script").slice(1).map((s) => s.slice(s.indexOf(">") + 1).split("</script>")[0]);
const appScript = scripts.find((s) => s.includes("const DB=") && s.includes("function enterField"));
assert(appScript, "inline Field script");

const vm = require("vm");
windowRef.document = documentRef;
windowRef.window = windowRef;
windowRef.console = console;
windowRef.Chart = undefined;
windowRef.Html5Qrcode = undefined;
windowRef.JsBarcode = undefined;
windowRef.AssetCsv = { parseCSV() { return []; } };
windowRef.toast = function () {};
windowRef.innerWidth = 1280;
windowRef.setTimeout = function (fn) {
  return 0;
};
windowRef.clearTimeout = clearTimeout;
windowRef.setInterval = setInterval;
windowRef.clearInterval = clearInterval;
const ctx = vm.createContext(windowRef);
try {
  vm.runInContext(appScript, ctx, { timeout: 5000 });
} catch (err) {
  console.error("script eval failed", err);
  process.exit(1);
}

vm.runInContext(
  "DB.users=[];DB.projects=undefined;DB.assets=undefined;DB.clients=undefined;DB.blanccoCategories=undefined;DB.testParams=undefined;",
  ctx
);
const ok = vm.runInContext(
  'enterField({id:"U-1",name:"Manish Kumar",email:"manish@urbeno.in",role:"SuperAdmin"})',
  ctx
);
assert(ok === true, "enterField returns true");
const role = vm.runInContext("ME && ME.role", ctx);
assert(role === "Super Admin", "stale SuperAdmin role becomes Super Admin, got " + role);
assert(!documentRef._ids.appview.classList.contains("hide"), "appview visible");
assert(documentRef._ids.loginview.classList.contains("hide"), "login hidden");
assert(documentRef._ids.nav.innerHTML.includes("Dashboard"), "nav has Dashboard, got: " + documentRef._ids.nav.innerHTML.slice(0, 200));
assert(documentRef._ids.nav.innerHTML.includes("Projects"), "nav has Projects");
assert(documentRef._ids.nav.innerHTML.includes("Asset Register"), "nav has Asset Register");
assert(documentRef._ids.content.innerHTML.includes("kpi") || documentRef._ids.content.innerHTML.includes("Open projects") || documentRef._ids.content.innerHTML.includes("Project testing"), "dashboard rendered, got: " + documentRef._ids.content.innerHTML.slice(0, 240));
assert(documentRef._ids.whoami.textContent.includes("Super Admin"), "whoami Super Admin");

vm.runInContext("leaveField()", ctx);
assert(documentRef._ids.appview.classList.contains("hide"), "leaveField hides app");
assert(!documentRef._ids.loginview.classList.contains("hide"), "leaveField shows login");
assert(vm.runInContext("ME", ctx) === null, "ME cleared");

console.log("ok");
