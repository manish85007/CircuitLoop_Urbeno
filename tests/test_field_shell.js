#!/usr/bin/env node
/* Smoke the Field shell after a partial hydrate (missing masters / odd roles). */
const fs = require("fs");
const path = require("path");
const htmlPath = path.join(__dirname, "..", "static", "index.html");
const persistPath = path.join(__dirname, "..", "static", "persist.js");
const fieldPath = path.join(__dirname, "..", "static", "field.js");
const html = fs.readFileSync(htmlPath, "utf8");
const persist = fs.readFileSync(persistPath, "utf8");
const field = fs.readFileSync(fieldPath, "utf8");

function assert(cond, msg) {
  if (!cond) {
    console.error("fail:", msg);
    process.exit(1);
  }
}

assert(field.includes("function enterField("), "enterField in field.js");
assert(field.includes("data-act=\"addUser\""), "Add user action");
assert(!field.includes("New users cannot be added"), "create users enabled");
assert(field.includes("function leaveField("), "leaveField in field.js");
assert(field.includes("function paintNav("), "paintNav in field.js");
assert(html.includes("field.js?v=prod23"), "field.js cache bust");
assert(html.includes("persist.js?v=prod21"), "prod21 cache bust");
assert(html.includes("asset-csv.js?v=prod2"), "asset-csv cache bust");
assert(persist.includes("Object.assign(DB, dbSeed, state)"), "applyState merges seed");
assert(persist.includes("function mergeSeq("), "applyState keeps seq from going backwards");
assert(persist.includes("function mergeMasters("), "hydrate repairs swapped spec/test legends");
assert(persist.includes("copy._create = true"), "new asset rows are marked _create");
assert(persist.includes("window.enterField"), "persist calls enterField");
assert(persist.includes("window.leaveField"), "persist calls leaveField");
assert(persist.includes("DELETE") && persist.includes("/api/session"), "logout deletes session");
assert(persist.includes("clSignedOut"), "logout survives refresh");
assert(persist.includes("localStorage"), "signed-out flag survives new tabs");
assert(persist.includes("keepalive"), "logout fetch survives unload");
assert(persist.includes("forceLoginScreen"), "refresh keeps login screen");
assert(field.includes("leaveField()"), "show() without session leaves Field");
assert(field.includes("function specExportCols("), "spec columns helper");
assert(field.includes("function assetCols("), "dynamic asset CSV columns");
assert(field.includes("Spec: Processor"), "Processor spec column");
assert(field.includes("Spec: RAM"), "RAM spec column");
assert(field.includes("Spec: Storage"), "Storage spec column");
assert(!field.includes("'Specifications','Remarks','Rejection Note'"), "no packed Specifications column");
assert(!field.includes("Object.entries(a.specs||{}).map(([k,v])=>k+': '+v).join('; ')"), "specs not packed into one CSV cell");
assert(field.includes("function isReviewer("), "isReviewer helper");
assert(field.includes("function askDeleteAssets("), "askDeleteAssets helper");
assert(field.includes("function confirmDeleteAssets("), "confirmDeleteAssets helper");
assert(field.includes("function bulkDeleteShown("), "bulkDeleteShown helper");
assert(field.includes("function undoLastImport("), "undoLastImport helper");
assert(field.includes("Undo last import"), "Undo last import control");
assert(field.includes("Delete shown"), "Delete shown control");
assert(field.includes("/api/assets/delete"), "delete API");
assert(field.includes("LAST_IMPORT_IDS"), "last import ids");
assert(field.includes("Super Admin can Delete or Undo last import"), "import toast undo");
assert(field.includes('data-act="confirmDeleteAssets"'), "confirm delete uses data-act");
assert(field.includes('data-act="askDeleteOne"'), "row delete uses data-act");
assert(!field.includes('onclick="confirmDeleteAssets(${JSON.stringify'), "confirm onclick not broken by JSON quotes");
assert(persist.includes("previewCode"), "preview email OTP shown on-screen");

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
  ids.modalbg = el("div", "modalbg");
  ids.modalbox = el("div", "modalbox");
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

const appScript = field;
assert(appScript.includes("const DB="), "Field data model");

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

const seedTestParams = vm.runInContext("JSON.parse(JSON.stringify(DB.testParams))", ctx);
const seedSpecFields = vm.runInContext("JSON.parse(JSON.stringify(DB.specFields))", ctx);

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

const leadOk = vm.runInContext(
  'enterField({id:"U-2",name:"Darshak",email:"darshak@urbeno.in",role:"Lead Engineer"})',
  ctx
);
assert(leadOk === true, "enterField Lead Engineer returns true");
assert(vm.runInContext("ME && ME.role", ctx) === "Lead Engineer", "Lead Engineer role preserved");
assert(documentRef._ids.nav.innerHTML.includes("Projects"), "Lead nav has Projects");
assert(documentRef._ids.nav.innerHTML.includes("Asset Register"), "Lead nav has Asset Register");
assert(documentRef._ids.nav.innerHTML.includes("Reports"), "Lead nav has Reports");
assert(!documentRef._ids.nav.innerHTML.includes(">Users<") && !documentRef._ids.nav.innerHTML.includes("Users</a>"), "Lead nav hides Users, got: " + documentRef._ids.nav.innerHTML);
assert(!documentRef._ids.nav.innerHTML.includes("Masters"), "Lead nav hides Masters");
assert(documentRef._ids.whoami.textContent.includes("Lead Engineer"), "whoami Lead Engineer");
vm.runInContext("show('register')", ctx);
assert(!documentRef._ids.content.innerHTML.includes("Delete shown"), "Lead Engineer has no Delete shown");
assert(!documentRef._ids.content.innerHTML.includes("Undo last import"), "Lead Engineer has no Undo last import");
assert(!documentRef._ids.content.innerHTML.includes(">Delete</button>"), "Lead Engineer has no row Delete");

vm.runInContext("leaveField()", ctx);
vm.runInContext(
  'enterField({id:"U-1",name:"Manish Kumar",email:"manish@urbeno.in",role:"Super Admin"})',
  ctx
);
vm.runInContext("show('register')", ctx);
assert(documentRef._ids.content.innerHTML.includes("Delete shown"), "Super Admin has Delete shown, got: " + documentRef._ids.content.innerHTML.slice(0, 400));
assert(documentRef._ids.content.innerHTML.includes("Undo last import"), "Super Admin has Undo last import");
assert(documentRef._ids.content.innerHTML.includes("mistaken bulk-upload"), "Super Admin register explains delete");

vm.runInContext(
  'DB.assets=[{id:"AST-1",serial:"SN-1",usn:"USN-1",category:"Laptop",brand:"Dell",model:"X",projectId:"PRJ-1",status:"Registered",assetTag:"",testedBy:"",testedAt:"",grade:"",blancco:null,tests:{},history:[]}]; show("register")',
  ctx
);
assert(documentRef._ids.content.innerHTML.includes('data-act="askDeleteOne"'), "register row delete uses data-act");
assert(!documentRef._ids.content.innerHTML.includes('onclick="askDeleteAssets(['), "register row delete is not a broken onclick");
vm.runInContext("askDeleteAssets(['AST-1'],'Delete SN-1 from the register?')", ctx);
const modalHtml = documentRef._ids.modalbox.innerHTML;
assert(modalHtml.includes('data-act="confirmDeleteAssets"'), "confirm Delete uses data-act, got: " + modalHtml.slice(0, 500));
assert(!/onclick="confirmDeleteAssets\(\[/.test(modalHtml), "confirm Delete onclick is not broken by JSON quotes: " + modalHtml);
assert(modalHtml.includes("data-ids="), "confirm Delete carries ids");
const idsAttr = (modalHtml.match(/data-ids="([^"]*)"/) || [])[1] || "";
const decoded = idsAttr.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
let parsedIds;
try {
  parsedIds = JSON.parse(decoded);
} catch (err) {
  parsedIds = null;
}
assert(parsedIds && parsedIds[0] === "AST-1", "confirm data-ids parses, got: " + decoded);

vm.runInContext(
  'DB.projects=[{id:"PRJ-1001",name:"Keep me",status:"Active",team:[],scope:[],clientId:"",site:"",mode:"",start:"",due:"",managerId:"U-1"}]; DB.seq.project=1001;',
  ctx
);
const newPid = vm.runInContext("nextProjectId()", ctx);
assert(newPid !== "PRJ-1001", "next project id must not reuse the active project, got " + newPid);
assert(/^PRJ-1002$/.test(newPid), "next project id after PRJ-1001 is PRJ-1002, got " + newPid);
const newPid2 = vm.runInContext("nextProjectId()", ctx);
assert(newPid2 !== newPid && newPid2 !== "PRJ-1001", "second nextProjectId is unique, got " + newPid2);
vm.runInContext("show('projects')", ctx);
assert(documentRef._ids.content.innerHTML.includes('data-act="newProject"'), "Projects has New project action");
assert(!documentRef._ids.content.innerHTML.includes("onclick=\"editProject()\""), "New project is not editProject()");

vm.runInContext("leaveField()", ctx);

vm.runInContext(
  'enterField({id:"U-1",name:"Manish Kumar",email:"manish@urbeno.in",role:"Super Admin"})',
  ctx
);
vm.runInContext(
  "DB.testParams=" + JSON.stringify(seedTestParams) + ";DB.specFields=" + JSON.stringify(seedSpecFields) + ";",
  ctx
);
assert(vm.runInContext("specsFor('Laptop').indexOf('Processor')>=0", ctx), "Laptop specs include Processor");
assert(vm.runInContext("specsFor('Laptop').indexOf('Panel Type')<0", ctx), "Laptop specs are not Monitor");
assert(vm.runInContext("specsFor('Monitor').indexOf('Panel Type')>=0", ctx), "Monitor specs include Panel Type");
assert(vm.runInContext("specsFor('Desktop').indexOf('Form Factor')>=0", ctx), "Desktop specs include Form Factor");
assert(vm.runInContext("specsFor('Printer').indexOf('Mono/Colour')>=0", ctx), "Printer specs include Mono/Colour");
assert(vm.runInContext("paramsFor('Tablet').some(p=>p.key==='cameras')", ctx), "Tablet checklist has cameras");
assert(vm.runInContext("paramsFor('Server').some(p=>p.key==='raid')", ctx), "Server checklist has RAID");
assert(vm.runInContext("paramsFor('Laptop').some(p=>p.key==='keyboard')", ctx), "Laptop checklist has keyboard");
assert(vm.runInContext("!paramsFor('Laptop').some(p=>p.key==='panel')", ctx), "Laptop checklist is not Monitor");
assert(vm.runInContext("canonCategory('laptop')==='Laptop'", ctx), "canonCategory maps laptop");
assert(vm.runInContext("canonCategory('All-in-one')==='All-in-One'", ctx), "canonCategory maps All-in-One");

vm.runInContext(
  `DB.projects=[{id:"PRJ-1001",name:"Job",status:"Active",team:["U-1"],scope:[{category:"Laptop",expected:2},{category:"Monitor",expected:2}],clientId:"",site:"",mode:"",start:"",due:"",managerId:"U-1"}];
   ACTIVE_PROJECT="PRJ-1001";
   DB.seq.asset=1; DB.seq.usn=50001;
   DB.assets=[{id:"AST-00001",usn:"URB-050001",serial:"MON-1",category:"Monitor",brand:"Dell",model:"P2422H",projectId:"PRJ-1001",status:"Registered",tests:{},specs:{"Panel Type":"IPS"},history:[]}];
   show("testing");`,
  ctx
);
const testingHtml = documentRef._ids.content.innerHTML;
assert(testingHtml.includes("<th>Serial / USN</th>"), "testing table has Serial / USN header");
assert(testingHtml.includes("<th>Asset</th>"), "testing table has Asset header");
assert(testingHtml.includes("<th>Status</th>"), "testing table has Status header");
assert(testingHtml.includes("MON-1"), "testing table shows monitor serial");
assert(testingHtml.includes("Monitor"), "testing table shows Monitor category");
assert(testingHtml.includes("data-cat=\"Monitor\""), "testing row is tagged Monitor");

const minted = vm.runInContext("genAssetId()", ctx);
assert(minted !== "AST-00001", "genAssetId skips the Monitor id, got " + minted);
assert(/^AST-00002$/.test(minted), "next asset after AST-00001 is AST-00002, got " + minted);

vm.runInContext(
  `DB.assets.push({id:genAssetId(),usn:genUSN(),serial:"LAP-1",category:"Laptop",brand:"HP",model:"840",projectId:"PRJ-1001",status:"In Testing",tests:{},specs:{Processor:"i5"},history:[],_create:true});
   show("testing");`,
  ctx
);
const bothHtml = documentRef._ids.content.innerHTML;
assert(bothHtml.includes("LAP-1") && bothHtml.includes("Laptop"), "testing table shows the Laptop row");
assert(bothHtml.includes("MON-1") && bothHtml.includes("Monitor"), "testing table still shows the Monitor row");
assert(vm.runInContext("assetById(DB.assets.find(a=>a.serial==='LAP-1').id).category", ctx) === "Laptop", "Laptop row stays Laptop");
assert(vm.runInContext("assetById('AST-00001').category", ctx) === "Monitor", "Monitor id still Monitor");

const ids = {};
function inputEl(id, value) {
  const node = {
    id,
    value: value || "",
    tagName: "SELECT",
    className: "",
    innerHTML: "",
    textContent: "",
    style: {},
    dataset: {},
    children: [],
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  ids[id] = node;
  return node;
}
const raCat = inputEl("ra_cat", "Laptop");
const raSpecsBox = inputEl("ra_specs", "");
documentRef._ids.ra_cat = raCat;
documentRef._ids.ra_specs = raSpecsBox;
const origGet = documentRef.getElementById.bind(documentRef);
documentRef.getElementById = function (id) {
  return ids[id] || origGet(id);
};
const origQs = documentRef.querySelector.bind(documentRef);
documentRef.querySelector = function (sel) {
  if (sel === "#ra_cat") return raCat;
  if (sel === "#ra_specs") return raSpecsBox;
  return origQs(sel);
};

vm.runInContext("raSpecs()", ctx);
assert(raSpecsBox.innerHTML.includes("Processor"), "Laptop raSpecs shows Processor, got: " + raSpecsBox.innerHTML.slice(0, 240));
assert(!raSpecsBox.innerHTML.includes("Panel Type"), "Laptop raSpecs does not show Monitor Panel Type");
raCat.value = "Monitor";
vm.runInContext("raSpecs()", ctx);
assert(raSpecsBox.innerHTML.includes("Panel Type"), "switching to Monitor loads Panel Type");
assert(!raSpecsBox.innerHTML.includes("Processor"), "Monitor raSpecs does not keep Laptop Processor");
raCat.value = "Desktop";
vm.runInContext("raSpecs()", ctx);
assert(raSpecsBox.innerHTML.includes("Form Factor"), "Desktop raSpecs shows Form Factor");
raCat.value = "Printer";
vm.runInContext("raSpecs()", ctx);
assert(raSpecsBox.innerHTML.includes("Mono/Colour"), "Printer raSpecs shows Mono/Colour");
raCat.value = "Tablet";
vm.runInContext("raSpecs()", ctx);
assert(raSpecsBox.innerHTML.includes("Cellular"), "Tablet raSpecs shows Cellular");
raCat.value = "Server";
vm.runInContext("raSpecs()", ctx);
assert(raSpecsBox.innerHTML.includes("RAID"), "Server raSpecs shows RAID");

assert(field.includes("function nextAssetId("), "nextAssetId helper");
assert(field.includes("function canonCategory("), "canonCategory helper");
assert(field.includes("function assetById("), "assetById prefers last matching id");
assert(field.includes("_create:true"), "new captures are marked _create");
assert(field.includes("Select category"), "register requires an explicit category");

vm.runInContext("leaveField()", ctx);

console.log("ok");
