const assert = require("assert");
const fs = require("fs");
const path = require("path");
const AssetCsv = require("../static/asset-csv.js");

const ctx = {
  projects: [
    {
      id: "PRJ-1001",
      name: "Meridian Clinic Refresh — Phase 1",
      team: ["U-3"],
      managerId: "U-2",
    },
    { id: "PRJ-1002", name: "Vantage HQ", team: ["U-5"], managerId: "U-1" },
  ],
  assets: [
    {
      id: "AST-00001",
      usn: "URB-050001",
      serial: "DL5540-88213",
      projectId: "PRJ-1001",
      category: "Laptop",
    },
  ],
  users: [
    { id: "U-1", name: "Manish Kumar", email: "manish85007@gmail.com", role: "Super Admin" },
    { id: "U-3", name: "A. Verma", email: "a.verma@urbeno.in", role: "Field Engineer" },
  ],
  categories: ["Laptop", "Desktop", "Monitor", "Thin Client"],
  testParams: {
    Laptop: [
      { key: "poweron", label: "Powers on", critical: true },
      { key: "display", label: "Display", critical: true },
      { key: "sanitize", label: "Sanitization", critical: true, blancco: true },
    ],
    Monitor: [
      { key: "poweron", label: "Powers on", critical: true },
      { key: "panel", label: "Panel", critical: true },
    ],
  },
  specFields: {
    Laptop: ["Processor", "Generation", "RAM", "Storage", "Screen Size", "GPU", "Year"],
    Monitor: ["Screen Size", "Panel Type", "Resolution", "Year"],
  },
  blanccoCategories: ["Laptop"],
  seq: { asset: 2, usn: 50002, blancco: 9001 },
  me: { id: "U-1", name: "Manish Kumar", role: "Super Admin" },
  defaultProjectId: "PRJ-1001",
};

function csv(rows) {
  return AssetCsv.toCSV(AssetCsv.TEMPLATE_COLS, rows);
}

function baseRow(overrides) {
  const row = AssetCsv.TEMPLATE_COLS.map(() => "");
  const set = (name, val) => {
    row[AssetCsv.TEMPLATE_COLS.indexOf(name)] = val;
  };
  set("Serial*", "NEW-SN-001");
  set("Category*", "Laptop");
  set("Brand", "Dell");
  set("Model", "Latitude 5540");
  set("Project ID*", "PRJ-1001");
  set("Status", "Tested");
  set("Cosmetic", "B");
  Object.entries(overrides || {}).forEach(([k, v]) => set(k, v));
  return row;
}

const template = AssetCsv.templateCSV();
assert(template.includes("Serial*"));
assert(template.includes("Project ID*"));
assert(template.includes("Category*"));
assert.deepStrictEqual(AssetCsv.REQUIRED_COLS, ["Serial*", "Project ID*", "Category*"]);
assert(AssetCsv.TEMPLATE_COLS.includes("Test: poweron"));
assert(AssetCsv.TEMPLATE_COLS.includes("Test: sanitize"));
assert(AssetCsv.TEMPLATE_COLS.includes("Spec: Processor"));
assert(AssetCsv.TEMPLATE_COLS.includes("Spec: Screen Size"));
assert(AssetCsv.TEMPLATE_COLS.includes("Spec: RAM"));
assert(!AssetCsv.TEMPLATE_COLS.includes("Tests"));
assert(!AssetCsv.TEMPLATE_COLS.includes("Specifications"));
assert(AssetCsv.TEMPLATE_COLS.length > 40);

const parsedTemplate = AssetCsv.parseCSV(template);
assert.strictEqual(parsedTemplate.length, 2);
assert.strictEqual(parsedTemplate[0].serial, "DL5540-NEW01");
assert.strictEqual(parsedTemplate[0].project_id, "PRJ-1001");
assert.strictEqual(parsedTemplate[0].category, "Laptop");
assert.strictEqual(parsedTemplate[0].test_poweron, "Pass");
assert.strictEqual(parsedTemplate[0].spec_processor, "Intel Core i5-1335U");
assert.strictEqual(parsedTemplate[0].spec_ram, "16 GB");
assert.strictEqual(parsedTemplate[1].test_panel, "Pass");
assert.strictEqual(parsedTemplate[1].spec_panel_type, "IPS");

const previewOk = AssetCsv.preview(csv([baseRow({ "Test: poweron": "Pass", "Test: display": "Fail", "Spec: Processor": "Intel Core i7" })]), ctx);
assert.strictEqual(previewOk.ready.length, 1, JSON.stringify(previewOk));
assert.strictEqual(previewOk.skipped.length, 0);
assert.strictEqual(previewOk.errors.length, 0);
assert.strictEqual(previewOk.ready[0].asset.serial, "NEW-SN-001");
assert.strictEqual(previewOk.ready[0].asset.status, "In Testing");
assert.strictEqual(previewOk.ready[0].asset.blancco, null);
assert.strictEqual(previewOk.ready[0].asset.tests.poweron, "Pass");
assert.strictEqual(previewOk.ready[0].asset.tests.display, "Fail");
assert.strictEqual(previewOk.ready[0].asset.specs.Processor, "Intel Core i7");
assert.ok(previewOk.ready[0].asset.usn.startsWith("URB-"));
assert.strictEqual(ctx.assets.length, 1, "preview must not mutate existing assets");

const fromTemplate = AssetCsv.preview(template, ctx);
assert.strictEqual(fromTemplate.ready.length, 2, JSON.stringify(fromTemplate.errors));
assert.strictEqual(fromTemplate.ready[0].asset.tests.poweron, "Pass");
assert.strictEqual(fromTemplate.ready[0].asset.specs.Processor, "Intel Core i5-1335U");
assert.strictEqual(fromTemplate.ready[1].serial, "NoSerial-1");
assert.strictEqual(fromTemplate.ready[1].asset.specs["Panel Type"], "IPS");

const legend = AssetCsv.specLegendFields(
  { Laptop: ["Processor", "RAM", "Storage"], Monitor: ["Panel Type"] },
  [{ specs: { Processor: "i7", "Warranty": "1y" } }]
);
assert.ok(legend.indexOf("Processor") < legend.indexOf("RAM"));
assert.ok(legend.indexOf("RAM") < legend.indexOf("Storage"));
assert.ok(legend.includes("Panel Type"));
assert.ok(legend.includes("Warranty"));
const cols = AssetCsv.specExportCols({ Laptop: ["Processor", "RAM", "Storage"] });
assert.ok(cols.includes("Spec: Processor"));
assert.ok(cols.includes("Spec: RAM"));
assert.ok(cols.includes("Spec: Storage"));
assert.ok(!cols.includes("Specifications"));
const vals = AssetCsv.specExportValues(
  { Processor: "Intel Core i7", RAM: "16 GB", Storage: "512 GB NVMe" },
  { Laptop: ["Processor", "RAM", "Storage"] }
);
assert.strictEqual(vals[cols.indexOf("Spec: Processor")], "Intel Core i7");
assert.strictEqual(vals[cols.indexOf("Spec: RAM")], "16 GB");
assert.strictEqual(vals[cols.indexOf("Spec: Storage")], "512 GB NVMe");
assert.ok(!String(vals.join("|")).includes("Processor: Intel"));

const dup = AssetCsv.preview(csv([baseRow({ "Serial*": "DL5540-88213" })]), ctx);
assert.strictEqual(dup.ready.length, 0, JSON.stringify(dup));
assert.strictEqual(dup.skipped.length, 1);
assert.match(dup.skipped[0].reason, /already in the register/i);

const fileDup = AssetCsv.preview(csv([baseRow(), baseRow()]), ctx);
assert.strictEqual(fileDup.ready.length, 1);
assert.strictEqual(fileDup.skipped.length, 1);
assert.match(fileDup.skipped[0].reason, /duplicate serial in this file/i);

const badProject = AssetCsv.preview(csv([baseRow({ "Project ID*": "PRJ-9999" })]), ctx);
assert.strictEqual(badProject.errors.length, 1);
assert.match(badProject.errors[0].message, /unknown project/i);

const noSerial = AssetCsv.preview(csv([baseRow({ "Serial*": "NoSerial", "Category*": "Monitor" })]), ctx);
assert.strictEqual(noSerial.ready.length, 1, JSON.stringify(noSerial));
assert.strictEqual(noSerial.ready[0].serial, "NoSerial-1");

const fieldCtx = Object.assign({}, ctx, {
  me: { id: "U-3", name: "A. Verma", role: "Field Engineer" },
});
const fieldBlocked = AssetCsv.preview(csv([baseRow({ "Project ID*": "PRJ-1002" })]), fieldCtx);
assert.strictEqual(fieldBlocked.errors.length, 1);
assert.match(fieldBlocked.errors[0].message, /not assigned/i);

const fieldOk = AssetCsv.preview(csv([baseRow({ Status: "Verified" })]), fieldCtx);
assert.strictEqual(fieldOk.ready.length, 1);
assert.strictEqual(fieldOk.ready[0].status, "In Testing", "Field cannot import as Verified; missing tests stay blank");

const gradeA = AssetCsv.preview(csv([baseRow({ Cosmetic: "A", "Test: poweron": "Pass", "Test: display": "Pass", "Test: keyboard": "Pass", "Test: touchpad": "Pass", "Test: battery": "Pass", "Test: ports": "Pass", "Test: webcam": "Pass", "Test: audio": "Pass", "Test: wifi": "Pass", "Test: charger": "Pass", "Test: biosclear": "Pass", "Test: sanitize": "Pass" })]), ctx);
assert.strictEqual(gradeA.ready[0].asset.cosmetic, "A");
assert.strictEqual(gradeA.ready[0].asset.grade, "A");
assert.strictEqual(gradeA.ready[0].asset.blancco, null);

const returning = AssetCsv.preview(
  csv([baseRow({ "Serial*": "DL5540-88213", "Project ID*": "PRJ-1002" })]),
  ctx
);
assert.strictEqual(returning.ready.length, 1, "same serial allowed on a different project");

const blanccoCsv = AssetCsv.preview(csv([baseRow({ "Blancco Status": "Erased", "Blancco Report": "BL-FAKE" })]), ctx);
assert.strictEqual(blanccoCsv.ready[0].asset.blancco, null);

const bom = "\uFEFF" + csv([baseRow({ "Serial*": "BOM-1" })]);
const bomPrev = AssetCsv.preview(bom, ctx);
assert.strictEqual(bomPrev.ready.length, 1);
assert.strictEqual(bomPrev.ready[0].serial, "BOM-1");

const filePath = path.join(__dirname, "../static/circuitloop_asset_import_template.csv");
const disk = fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, "").trim();
assert.strictEqual(disk, template.trim());

console.log("ok", previewOk.ready.length, "ready;", dup.skipped.length, "duplicate skipped");
