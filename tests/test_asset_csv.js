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
  specFields: {},
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
assert.strictEqual(AssetCsv.TEMPLATE_COLS.length, 26);

const parsedTemplate = AssetCsv.parseCSV(template);
assert.strictEqual(parsedTemplate.length, 2);
assert.strictEqual(parsedTemplate[0].serial, "DL5540-NEW01");
assert.strictEqual(parsedTemplate[0].project_id, "PRJ-1001");
assert.strictEqual(parsedTemplate[0].category, "Laptop");

const previewOk = AssetCsv.preview(csv([baseRow()]), ctx);
assert.strictEqual(previewOk.ready.length, 1, JSON.stringify(previewOk));
assert.strictEqual(previewOk.skipped.length, 0);
assert.strictEqual(previewOk.errors.length, 0);
assert.strictEqual(previewOk.ready[0].asset.serial, "NEW-SN-001");
assert.strictEqual(previewOk.ready[0].asset.status, "Tested");
assert.ok(previewOk.ready[0].asset.usn.startsWith("URB-"));
assert.strictEqual(ctx.assets.length, 1, "preview must not mutate existing assets");

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
assert.strictEqual(fieldOk.ready[0].status, "Tested", "Field cannot import as Verified");

const bom = "\uFEFF" + csv([baseRow({ "Serial*": "BOM-1" })]);
const bomPrev = AssetCsv.preview(bom, ctx);
assert.strictEqual(bomPrev.ready.length, 1);
assert.strictEqual(bomPrev.ready[0].serial, "BOM-1");

const filePath = path.join(__dirname, "../static/circuitloop_asset_import_template.csv");
const disk = fs.readFileSync(filePath, "utf8").replace(/^\uFEFF/, "").trim();
assert.strictEqual(disk, template.trim());

console.log("ok", previewOk.ready.length, "ready;", dup.skipped.length, "duplicate skipped");
