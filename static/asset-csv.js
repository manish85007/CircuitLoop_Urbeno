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

  /* Same register fields as ASSET_COLS / Scan & Test. Asterisk = required on import. */
  const TEMPLATE_COLS = [
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
    "Grade Rationale",
    "Tests Recorded",
    "Failed Parameters",
    "Tests",
    "Tested By",
    "Tested On",
    "Verified By",
    "Verified On",
    "Blancco Status",
    "Blancco Report",
    "Erasure Standard",
    "Specifications",
    "Remarks",
    "Rejection Note",
  ];
  const REQUIRED_COLS = ["Serial*", "Project ID*", "Category*"];

  const TEMPLATE_ROWS = [
    [
      "DL5540-NEW01",
      "",
      "",
      "Laptop",
      "Dell",
      "Latitude 5540",
      "PRJ-1001",
      "",
      "",
      "Tested",
      "",
      "B",
      "",
      "",
      "",
      "poweron:Pass;display:Pass;keyboard:Pass;touchpad:Pass;battery:Pass;ports:Pass;webcam:Pass;audio:Pass;wifi:Pass;charger:Pass;biosclear:Pass;sanitize:Pass",
      "",
      "",
      "",
      "",
      "",
      "",
      "",
      "Processor: Intel Core i5-1335U; RAM: 16 GB; Storage: 512 GB NVMe",
      "Imported from Excel",
      "",
    ],
    [
      "NoSerial",
      "",
      "",
      "Monitor",
      "Dell",
      "P2422H",
      "PRJ-1001",
      "",
      "",
      "Tested",
      "",
      "A",
      "",
      "",
      "",
      "poweron:Pass;panel:Pass;backlight:Pass;ports:Pass;buttons:Pass;stand:Pass;cables:Pass",
      "",
      "",
      "",
      "",
      "",
      "",
      "",
      "Screen Size: 24\"; Panel Type: IPS",
      "No factory serial — physical check",
      "",
    ],
  ];

  function csvEscape(v) {
    return '"' + String(v == null ? "" : v).replace(/"/g, '""') + '"';
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
    if (parseNoSerialIndex(serial) != null) {
      return (assets || []).some(
        (a) => a.projectId === projectId && String(a.serial || "").toLowerCase() === s
      );
    }
    return (assets || []).some((a) => String(a.serial || "").toLowerCase() === s);
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
      const raw = row[p.key] || row[p.key + "_result"];
      const val = normTestResult(raw);
      if (val) tests[p.key] = val;
    });
    return { tests, measures };
  }

  function parseSpecs(text) {
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

  function fillTestsIfTested(tests, cat, ctx, status) {
    if (!["Tested", "Verified", "Rejected"].includes(status)) return tests;
    paramsFor(ctx, cat).forEach((p) => {
      if (!tests[p.key]) tests[p.key] = "Pass";
    });
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
    const idx = { A: 0, B: 1, C: 2, D: 3 }[cosmetic] || 1;
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
      const specs = parseSpecs(col(row, "specs"));
      const tester = matchUser(ctx.users, col(row, "tested_by")) || me;
      const verifier = matchUser(ctx.users, col(row, "verified_by"));
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
        status: status,
        tests: tests,
        measures: parsed.measures,
        specs: specs,
        remarks: col(row, "remarks").slice(0, 500),
        rejectNote: col(row, "reject_note") || "",
        testedBy: status === "Registered" ? null : tester.id,
        testedAt: status === "Registered" ? null : col(row, "tested_on") || todayStamp(),
        verifiedBy: status === "Verified" ? (verifier ? verifier.id : me.id) : null,
        verifiedAt: status === "Verified" ? col(row, "verified_on") || todayStamp() : null,
        blancco: null,
        history: [
          {
            ts: clockStamp(),
            by: me.name,
            ev:
              "Imported from CSV as " +
              status +
              (isNoSerialValue(serial) ? " (" + serial + ", no factory serial)" : " (" + serial + ")"),
          },
        ],
      };

      const bStatus = col(row, "blancco_status");
      const bReport = col(row, "blancco_report");
      const bStd = col(row, "blancco_standard");
      if (bStatus || bReport) {
        let bn = seq.blancco || 9001;
        asset.blancco = {
          reportId: bReport || "BL-" + bn++,
          serial: serial,
          status: bStatus || "Erased",
          standard: bStd || "NIST 800-88 Rev.1 Purge",
          software: "CSV import",
          date: asset.testedAt || todayStamp(),
          verified: /erased|pass/i.test(bStatus || "Erased"),
          drives: [],
          operator: me.name,
          source: "CSV import",
          raw: "Imported from Excel/CSV",
        };
        seq.blancco = bn;
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
      out.ready.push({ row: line, serial: serial, usn: usn, projectId: project.id, category: category, status: status, grade: asset.grade, asset: asset });
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
