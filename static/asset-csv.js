/* CircuitLoop Field — CSV import for already-tested devices.
   Appends to the live register. Never replaces or deletes existing assets. */
(function (root) {
  const STATUSES = ["Registered", "In Testing", "Tested", "Verified", "Rejected"];
  const COSMETIC = ["A", "B", "C", "D"];
  const ALIASES = {
    serial: ["serial", "sn", "serial_number", "serial_no", "serialnumber", "device_serial", "factory_serial"],
    usn: ["usn", "urb_sn", "urbeno_sn", "circuitloop_usn", "asset_usn"],
    project: ["project_id", "projectid", "prj", "project"],
    category: ["category", "cat", "asset_category", "type"],
    brand: ["brand", "make", "manufacturer"],
    model: ["model"],
    tag: ["client_asset_tag", "asset_tag", "tag", "client_tag"],
    cosmetic: ["cosmetic", "cosmetic_grade"],
    grade: ["grade"],
    status: ["status"],
    remarks: ["remarks", "notes", "remark", "comments"],
    tests: ["tests", "test_results", "test_params"],
    blancco_status: ["blancco_status", "blancco", "erasure_status"],
    blancco_report: ["blancco_report", "blancco_report_id", "report_id"],
    blancco_standard: ["erasure_standard", "blancco_standard", "standard"],
    specs: ["specifications", "specs"],
    tested_by: ["tested_by", "tester", "testedby"],
    tested_on: ["tested_on", "tested_at", "testedon"],
    verified_by: ["verified_by", "verifiedby"],
    verified_on: ["verified_on", "verified_at"],
    reject_note: ["rejection_note", "reject_note"],
  };

  /* CircuitLoop Scan & Test parameter keys (all categories). One CSV column each. */
  const TEST_PARAM_KEYS = [
    "poweron",
    "display",
    "keyboard",
    "touchpad",
    "battery",
    "ports",
    "webcam",
    "audio",
    "wifi",
    "charger",
    "biosclear",
    "sanitize",
    "ram",
    "storage",
    "psu",
    "gpu",
    "panel",
    "backlight",
    "buttons",
    "stand",
    "cables",
    "network",
    "adapter",
    "mount",
    "mgmt",
    "cpu",
    "drives",
    "raid",
    "rails",
    "console",
    "poe",
    "fans",
    "stack",
    "configerase",
    "touch",
    "cameras",
    "charging",
    "printtest",
    "trays",
    "consumable",
  ];
  const TEST_MEASURE_KEYS = ["battery", "ram", "storage", "cpu", "drives", "ports", "consumable"];
  /* CircuitLoop specFields names (all categories). One CSV column each. */
  const SPEC_FIELD_NAMES = [
    "Processor",
    "Generation",
    "RAM",
    "Storage",
    "Screen Size",
    "GPU",
    "Year",
    "Form Factor",
    "Panel Type",
    "Resolution",
    "Flash Storage",
    "OS",
    "CPU Count",
    "Drive Config",
    "RAID",
    "PSU",
    "Port Count",
    "Speed",
    "PoE",
    "Stackable",
    "Firmware",
    "Cellular",
    "Type",
    "Mono/Colour",
    "Duplex",
    "Network",
  ];
  const TEST_SPEC_COLLISION = {
    ram: 1,
    storage: 1,
    gpu: 1,
    psu: 1,
    raid: 1,
    poe: 1,
    network: 1,
  };

  function testColName(key) {
    return "Test: " + key;
  }
  function measureColName(key) {
    return "Measure: " + key;
  }
  function specColName(field) {
    return "Spec: " + field;
  }
  function slug(s) {
    return String(s || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_|_$/g, "");
  }

  const IDENTITY_COLS = [
    "Serial*",
    "USN",
    "Client Asset Tag",
    "Category*",
    "Brand",
    "Model",
    "Project ID*",
    "Project",
    "Client",
    "Status",
    "Grade",
    "Cosmetic",
  ];
  const TRAILING_COLS = [
    "Tested By",
    "Tested On",
    "Verified By",
    "Verified On",
    "Blancco Status",
    "Blancco Report",
    "Erasure Standard",
    "Remarks",
    "Rejection Note",
  ];
  const TEMPLATE_COLS = IDENTITY_COLS.concat(
    TEST_PARAM_KEYS.map(testColName),
    TEST_MEASURE_KEYS.map(measureColName),
    SPEC_FIELD_NAMES.map(specColName),
    TRAILING_COLS
  );
  const REQUIRED_COLS = ["Serial*", "Project ID*", "Category*"];

  function blankTemplateRow() {
    return TEMPLATE_COLS.map(function () {
      return "";
    });
  }
  function setTemplateCell(row, name, val) {
    const i = TEMPLATE_COLS.indexOf(name);
    if (i >= 0) row[i] = val;
  }
  function buildExampleRows() {
    const laptop = blankTemplateRow();
    setTemplateCell(laptop, "Serial*", "DL5540-NEW01");
    setTemplateCell(laptop, "Category*", "Laptop");
    setTemplateCell(laptop, "Brand", "Dell");
    setTemplateCell(laptop, "Model", "Latitude 5540");
    setTemplateCell(laptop, "Project ID*", "PRJ-1001");
    setTemplateCell(laptop, "Status", "Tested");
    setTemplateCell(laptop, "Cosmetic", "B");
    [
      "poweron",
      "display",
      "keyboard",
      "touchpad",
      "battery",
      "ports",
      "webcam",
      "audio",
      "wifi",
      "charger",
      "biosclear",
      "sanitize",
    ].forEach(function (k) {
      setTemplateCell(laptop, testColName(k), "Pass");
    });
    setTemplateCell(laptop, measureColName("battery"), "82");
    setTemplateCell(laptop, specColName("Processor"), "Intel Core i5-1335U");
    setTemplateCell(laptop, specColName("Generation"), "13th Gen");
    setTemplateCell(laptop, specColName("RAM"), "16 GB");
    setTemplateCell(laptop, specColName("Storage"), "512 GB NVMe");
    setTemplateCell(laptop, specColName("Screen Size"), "15.6\"");
    setTemplateCell(laptop, specColName("Year"), "2023");
    setTemplateCell(laptop, "Remarks", "Imported from Excel");

    const monitor = blankTemplateRow();
    setTemplateCell(monitor, "Serial*", "NoSerial");
    setTemplateCell(monitor, "Category*", "Monitor");
    setTemplateCell(monitor, "Brand", "Dell");
    setTemplateCell(monitor, "Model", "P2422H");
    setTemplateCell(monitor, "Project ID*", "PRJ-1001");
    setTemplateCell(monitor, "Status", "Tested");
    setTemplateCell(monitor, "Cosmetic", "A");
    ["poweron", "panel", "backlight", "ports", "buttons", "stand", "cables"].forEach(function (k) {
      setTemplateCell(monitor, testColName(k), "Pass");
    });
    setTemplateCell(monitor, specColName("Screen Size"), "24\"");
    setTemplateCell(monitor, specColName("Panel Type"), "IPS");
    setTemplateCell(monitor, specColName("Resolution"), "1920x1080");
    setTemplateCell(monitor, specColName("Year"), "2022");
    setTemplateCell(monitor, "Remarks", "No factory serial — physical check");
    return [laptop, monitor];
  }
  const TEMPLATE_ROWS = buildExampleRows();

  function csvEscape(v) {
    const s = String(v == null ? "" : v);
    const safe = /^[=+\-@\t\r]/.test(s) ? "'" + s : s;
    return '"' + safe.replace(/"/g, '""') + '"';
  }

  function toCSV(cols, rows) {
    return [cols.map(csvEscape).join(",")]
      .concat(rows.map((r) => r.map(csvEscape).join(",")))
      .join("\n");
  }

  function parseCSV(text) {
    const rows = [];
    let cur = "";
    let row = [];
    let inQ = false;
    text = String(text || "")
      .replace(/^\uFEFF/, "")
      .replace(/\r/g, "");
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (inQ) {
        if (ch === '"') {
          if (text[i + 1] === '"') {
            cur += '"';
            i++;
          } else inQ = false;
        } else cur += ch;
      } else if (ch === '"') inQ = true;
      else if (ch === ",") {
        row.push(cur);
        cur = "";
      } else if (ch === "\n") {
        row.push(cur);
        rows.push(row);
        row = [];
        cur = "";
      } else cur += ch;
    }
    if (cur !== "" || row.length) {
      row.push(cur);
      rows.push(row);
    }
    if (rows.length < 2) return [];
    const hdr = rows[0].map((h) =>
      h
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_|_$/g, "")
    );
    return rows
      .slice(1)
      .filter((r) => r.some((c) => String(c).trim() !== ""))
      .map((r) => {
        const o = {};
        hdr.forEach((h, i) => {
          o[h] = String(r[i] == null ? "" : r[i]).trim();
        });
        return o;
      });
  }

  function col(row, key) {
    const keys = ALIASES[key] || [key];
    for (let i = 0; i < keys.length; i++) {
      const k = keys[i];
      if (row[k] != null && String(row[k]).trim() !== "") return String(row[k]).trim();
    }
    return "";
  }

  function pad(n, w) {
    return String(n).padStart(w, "0");
  }

  function isBareNoSerial(serial) {
    const s = String(serial || "").trim().replace(/\s+/g, "");
    return !s || /^noserial$/i.test(s);
  }

  function parseNoSerialIndex(serial) {
    const m = /^noserial-(\d+)$/i.exec(String(serial || "").trim().replace(/\s+/g, ""));
    return m ? +m[1] : null;
  }

  function isNoSerialValue(serial) {
    return isBareNoSerial(serial) || parseNoSerialIndex(serial) != null;
  }

  function nextNoSerial(assets, projectId) {
    let max = 0;
    (assets || []).forEach((a) => {
      if (a.projectId !== projectId) return;
      const n = parseNoSerialIndex(a.serial);
      if (n) max = Math.max(max, n);
    });
    return "NoSerial-" + (max + 1);
  }

  function serialTaken(assets, serial, projectId) {
    const s = String(serial || "").trim().toLowerCase();
    if (!s) return false;
    return (assets || []).some((a) => {
      if (String(a.serial || "").toLowerCase() !== s) return false;
      if (a.projectId === projectId) return true;
      return false;
    });
  }

  function usnTaken(assets, usn) {
    const s = String(usn || "").trim().toLowerCase();
    if (!s) return false;
    return (assets || []).some((a) => String(a.usn || "").toLowerCase() === s);
  }

  function matchProject(projects, token) {
    const t = String(token || "").trim().toLowerCase();
    if (!t) return null;
    return (projects || []).find(
      (p) => String(p.id).toLowerCase() === t || String(p.name || "").toLowerCase() === t
    );
  }

  function matchCategory(categories, token) {
    const t = String(token || "").trim().toLowerCase();
    if (!t) return "";
    const hit = (categories || []).find((c) => String(c).toLowerCase() === t);
    return hit || "";
  }

  function matchUser(users, token) {
    const t = String(token || "").trim().toLowerCase();
    if (!t) return null;
    return (users || []).find(
      (u) =>
        String(u.id || "").toLowerCase() === t ||
        String(u.name || "").toLowerCase() === t ||
        String(u.email || "").toLowerCase() === t
    );
  }

  function normStatus(raw, role) {
    const s = String(raw || "").trim().toLowerCase();
    let out = "Tested";
    if (!s) out = "Tested";
    else if (["registered", "new", "captured"].includes(s)) out = "Registered";
    else if (["in testing", "testing", "in_testing", "open"].includes(s)) out = "In Testing";
    else if (["tested", "complete", "completed", "done", "pass", "passed"].includes(s)) out = "Tested";
    else if (["verified", "closed", "approved"].includes(s)) out = "Verified";
    else if (["rejected", "reject", "fail", "failed"].includes(s)) out = "Rejected";
    else if (STATUSES.includes(raw)) out = raw;
    if (out === "Verified" && role !== "Super Admin") out = "Tested";
    return out;
  }

  function normGradeLetter(raw) {
    const m = String(raw || "")
      .trim()
      .toUpperCase()
      .match(/\b([ABCD])\b/);
    return m ? m[1] : "";
  }

  function normTestResult(v) {
    const s = String(v || "").trim().toLowerCase();
    if (["pass", "passed", "ok", "yes", "p", "good"].includes(s)) return "Pass";
    if (["fail", "failed", "no", "f", "ng"].includes(s)) return "Fail";
    if (["n/a", "na", "not applicable", "skip", "none"].includes(s)) return "N/A";
    return "";
  }

  function paramsFor(ctx, cat) {
    const tp = (ctx && ctx.testParams) || {};
    return (
      tp[cat] || [
        { key: "poweron", label: "Powers on", critical: true },
        { key: "condition", label: "General condition acceptable", critical: false },
      ]
    );
  }

  function parseTests(row, cat, ctx) {
    const tests = {};
    const measures = {};
    const blob = col(row, "tests");
    if (blob) {
      if (blob.charAt(0) === "{") {
        try {
          const obj = JSON.parse(blob);
          Object.keys(obj || {}).forEach((k) => {
            const val = normTestResult(obj[k]);
            if (val) tests[k] = val;
          });
        } catch (e) {}
      } else {
        blob.split(/[;|]/).forEach((part) => {
          const bits = part.split(/[:=]/);
          if (bits.length >= 2) {
            const key = bits[0].trim().toLowerCase().replace(/[^a-z0-9]+/g, "");
            const val = normTestResult(bits.slice(1).join(":"));
            if (key && val) tests[key] = val;
          }
        });
      }
    }
    paramsFor(ctx, cat).forEach((p) => {
      const labelSlug = slug(String(p.label || "").replace(/&amp;/g, "&"));
      const raw =
        row["test_" + p.key] ||
        row[p.key + "_result"] ||
        row["test_" + labelSlug] ||
        (TEST_SPEC_COLLISION[p.key] ? "" : row[p.key]);
      const val = normTestResult(raw);
      if (val) tests[p.key] = val;
      const meas =
        row["measure_" + p.key] ||
        row[p.key + "_measured"] ||
        row[slug(p.measure || "")];
      if (meas) measures[p.key] = String(meas).trim();
    });
    return { tests, measures };
  }

  function parseSpecsBlob(text) {
    const out = {};
    String(text || "")
      .split(/[;|]/)
      .forEach((part) => {
        const i = part.indexOf(":");
        if (i < 1) return;
        const k = part.slice(0, i).trim();
        const v = part.slice(i + 1).trim();
        if (k && v) out[k] = v;
      });
    return out;
  }

  function specFieldsFor(ctx, cat) {
    const fromCtx = ctx && ctx.specFields && ctx.specFields[cat];
    if (fromCtx && fromCtx.length) return fromCtx;
    return SPEC_FIELD_NAMES;
  }

  function parseSpecsFromRow(row, cat, ctx) {
    const out = parseSpecsBlob(col(row, "specs"));
    specFieldsFor(ctx, cat).forEach((field) => {
      const raw = row["spec_" + slug(field)];
      if (raw) out[field] = String(raw).trim();
    });
    SPEC_FIELD_NAMES.forEach((field) => {
      const raw = row["spec_" + slug(field)];
      if (raw && !out[field]) out[field] = String(raw).trim();
    });
    return out;
  }

  function fillTestsIfTested(tests, cat, ctx, status) {
    return tests;
  }

  function gradeAsset(a, ctx) {
    const params = paramsFor(ctx, a.category);
    const fails = params.filter((p) => a.tests && a.tests[p.key] === "Fail");
    const critFails = fails.filter((p) => p.critical);
    const cosmetic = a.cosmetic || "B";
    if (critFails.length) {
      return {
        grade: "D",
        reason: "Critical failure: " + critFails.map((p) => String(p.label).replace(/&amp;/g, "&")).join(", "),
      };
    }
    const idx = { A: 0, B: 1, C: 2, D: 3 }[cosmetic] ?? 1;
    const demote = fails.length >= 3 ? 2 : fails.length >= 1 ? 1 : 0;
    const grade = "ABCD"[Math.min(3, idx + demote)];
    return {
      grade,
      reason: fails.length
        ? fails.length + " non-critical issue(s) + cosmetic " + cosmetic
        : "All tests passed, cosmetic " + cosmetic,
    };
  }

  function allowedProject(ctx, projectId) {
    if (!ctx || !ctx.me || ctx.me.role === "Super Admin") return true;
    const mine = (ctx.projects || []).filter(
      (p) => (p.team || []).indexOf(ctx.me.id) >= 0 || p.managerId === ctx.me.id
    );
    return mine.some((p) => p.id === projectId);
  }

  function bumpFromUsn(seq, usn) {
    const m = /^URB-(\d+)$/i.exec(String(usn || ""));
    if (m) seq.usn = Math.max(seq.usn || 0, +m[1] + 1);
  }

  function bumpFromAssetId(seq, id) {
    const m = /^AST-(\d+)$/i.exec(String(id || ""));
    if (m) seq.asset = Math.max(seq.asset || 0, +m[1] + 1);
  }

  function nextUsn(seq, assets) {
    let n = seq.usn || 1;
    const taken = new Set((assets || []).map((a) => String(a.usn || "").toLowerCase()));
    let usn = "URB-" + pad(n, 6);
    while (taken.has(usn.toLowerCase())) {
      n++;
      usn = "URB-" + pad(n, 6);
    }
    seq.usn = n + 1;
    return usn;
  }

  function nextAssetId(seq, assets) {
    let n = seq.asset || 1;
    const taken = new Set((assets || []).map((a) => String(a.id || "").toLowerCase()));
    let id = "AST-" + pad(n, 5);
    while (taken.has(id.toLowerCase())) {
      n++;
      id = "AST-" + pad(n, 5);
    }
    seq.asset = n + 1;
    return id;
  }

  function todayStamp() {
    return new Date().toISOString().slice(0, 10);
  }

  function clockStamp() {
    const d = new Date();
    return d.toISOString().slice(0, 10) + " " + d.toTimeString().slice(0, 5);
  }

  function preview(text, ctx) {
    const rows = parseCSV(text);
    const working = (ctx.assets || []).slice();
    const seq = Object.assign({}, ctx.seq || { asset: 1, usn: 50001, blancco: 9001 });
    const me = ctx.me || { id: "U-1", name: "Import", role: "Super Admin" };
    const out = {
      total: rows.length,
      ready: [],
      skipped: [],
      errors: [],
      seq: seq,
    };
    if (!rows.length) {
      out.errors.push({
        row: 0,
        serial: "",
        message: 'No rows found — include a header row. Required: serial (or NoSerial), project, category.',
      });
      return out;
    }

    const seenSerial = new Set();
    rows.forEach((row, idx) => {
      const line = idx + 2;
      const rawSerial = col(row, "serial");
      const projectTok = col(row, "project") || ctx.defaultProjectId || "";
      const project = matchProject(ctx.projects, projectTok);
      if (!project) {
        out.errors.push({
          row: line,
          serial: rawSerial || "(blank)",
          message: projectTok
            ? 'Unknown project "' + projectTok + '"'
            : "Project is required (column or active Scan & Test project)",
        });
        return;
      }
      if (!allowedProject(ctx, project.id)) {
        out.errors.push({
          row: line,
          serial: rawSerial || "(blank)",
          message: project.id + " is not assigned to you",
        });
        return;
      }

      let serial = rawSerial;
      if (isBareNoSerial(serial)) serial = nextNoSerial(working, project.id);
      else if (parseNoSerialIndex(serial) != null) serial = "NoSerial-" + parseNoSerialIndex(serial);
      else serial = String(serial).trim();

      const fileKey =
        (isNoSerialValue(serial) ? project.id + ":" : "") + String(serial).toLowerCase();
      if (seenSerial.has(fileKey)) {
        out.skipped.push({
          row: line,
          serial: serial,
          reason: "Duplicate serial in this file — skipped",
        });
        return;
      }
      if (serialTaken(working, serial, project.id)) {
        out.skipped.push({
          row: line,
          serial: serial,
          reason: "Serial already in the register — skipped (existing device kept)",
        });
        return;
      }
      seenSerial.add(fileKey);

      const category = matchCategory(ctx.categories, col(row, "category"));
      if (!category) {
        out.errors.push({
          row: line,
          serial: serial,
          message: col(row, "category")
            ? 'Unknown category "' + col(row, "category") + '"'
            : "Category is required",
        });
        return;
      }

      let usn = col(row, "usn");
      if (usn && usnTaken(working, usn)) {
        usn = "";
      }
      if (!usn) usn = nextUsn(seq, working);
      else bumpFromUsn(seq, usn);

      const status = normStatus(col(row, "status"), me.role);
      const cosmetic = normGradeLetter(col(row, "cosmetic")) || "B";
      const parsed = parseTests(row, category, ctx);
      const tests = fillTestsIfTested(parsed.tests, category, ctx, status);
      const specs = parseSpecsFromRow(row, category, ctx);
      const tester = me;
      let statusOut = status;
      const params = paramsFor(ctx, category);
      const allPresent = params.every((p) => tests[p.key]);
      if (["Tested", "Verified", "Rejected"].includes(statusOut) && !allPresent) {
        statusOut = "In Testing";
      }
      const verifier = null;
      const id = nextAssetId(seq, working);
      bumpFromAssetId(seq, id);

      const asset = {
        id: id,
        usn: usn,
        projectId: project.id,
        category: category,
        brand: col(row, "brand") || "—",
        model: col(row, "model") || "—",
        serial: serial,
        assetTag: col(row, "tag") || "",
        cosmetic: COSMETIC.indexOf(cosmetic) >= 0 ? cosmetic : "B",
        status: statusOut,
        tests: tests,
        measures: parsed.measures,
        specs: specs,
        remarks: col(row, "remarks").slice(0, 500),
        rejectNote: col(row, "reject_note") || "",
        testedBy: statusOut === "Registered" ? null : tester.id,
        testedAt: statusOut === "Registered" ? null : col(row, "tested_on") || todayStamp(),
        verifiedBy: null,
        verifiedAt: null,
        blancco: null,
        history: [
          {
            ts: clockStamp(),
            by: me.name,
            ev:
              "Imported from CSV as " +
              statusOut +
              " by " +
              me.name +
              (isNoSerialValue(serial) ? " (" + serial + ", no factory serial)" : " (" + serial + ")"),
          },
        ],
      };

      if (col(row, "blancco_status") || col(row, "blancco_report")) {
        asset.history.push({
          ts: clockStamp(),
          by: me.name,
          ev: "CSV Blancco columns ignored — only live Blancco API reports are stored",
        });
      }

      const g = gradeAsset(asset, ctx);
      asset.grade = g.grade;
      asset.gradeReason = g.reason;
      const wanted = normGradeLetter(col(row, "grade"));
      if (wanted && wanted !== asset.grade) {
        asset.history.push({
          ts: clockStamp(),
          by: me.name,
          ev: "CSV grade " + wanted + " noted; CircuitLoop grade is " + asset.grade + " from tests + cosmetic",
        });
      }

      working.push(asset);
      out.ready.push({ row: line, serial: serial, usn: usn, projectId: project.id, category: category, status: statusOut, grade: asset.grade, asset: asset });
    });

    out.seq = seq;
    return out;
  }

  function templateCSV() {
    return toCSV(TEMPLATE_COLS, TEMPLATE_ROWS);
  }

  const api = {
    ALIASES,
    TEMPLATE_COLS,
    REQUIRED_COLS,
    TEST_PARAM_KEYS,
    SPEC_FIELD_NAMES,
    parseCSV,
    toCSV,
    col,
    isBareNoSerial,
    isNoSerialValue,
    nextNoSerial,
    serialTaken,
    preview,
    templateCSV,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.AssetCsv = api;
})(typeof window !== "undefined" ? window : globalThis);
