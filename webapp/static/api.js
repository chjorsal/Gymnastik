"use strict";

// Ét sted hvor frontenden kalder handlinger. "server" bruger HTTP mod
// app.py; "browser" kører Python-motoren i browseren via Pyodide og gemmer
// planen i localStorage. Begge returnerer den samme visning (payload).

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const Api = (() => {
  const config = window.PLANNER_CONFIG || { mode: "server" };
  const PLAN_KEY = "opvarmning_plan_v1";

  async function readJson(res) {
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(data.error || `Noget gik galt (fejl ${res.status}).`, res.status);
    return data;
  }

  function download(blob, filename) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }

  // ---------- server (python app.py) ----------
  const server = {
    async start() {},
    async request(method, url, body) {
      const init = { method };
      if (body !== undefined) {
        init.headers = { "Content-Type": "application/json" };
        init.body = JSON.stringify(body);
      }
      return readJson(await fetch(url, init));
    },
    async upload(files, hal) {
      const fd = new FormData();
      files.forEach((f) => fd.append("files", f));
      if (hal) fd.append("show_hal", hal);
      return readJson(await fetch("/api/upload", { method: "POST", body: fd }));
    },
    async exportPlan() {
      window.location.href = "/api/export.xlsx";
    },
    onExternalChange() {},
    async savePlanFile() { throw new ApiError("Kun i browserudgaven.", 400); },
    async openPlanFile() { throw new ApiError("Kun i browserudgaven.", 400); },
    clearAllData() {},
  };

  // ---------- browser (Pyodide + localStorage) ----------
  // Samme URL'er som serveren, oversat til handlinger i planner.actions.
  const ROUTES = [
    ["GET", /^\/api\/state$/, () => ["payload", {}]],
    ["PATCH", /^\/api\/rows\/([^/]+)$/, (m, b) => ["patch_row", { row_id: decodeURIComponent(m[1]), field: b.field, value: b.value ?? null }]],
    ["DELETE", /^\/api\/rows\/([^/]+)$/, (m) => ["delete_row", { row_id: decodeURIComponent(m[1]) }]],
    ["POST", /^\/api\/rows\/special$/, (m, b) => ["add_special_row", { hal: b.hal, row_type: b.type }]],
    ["POST", /^\/api\/rows\/reorder$/, (m, b) => ["reorder_rows", { hal: b.hal, ordered_ids: b.orderedIds }]],
    ["POST", /^\/api\/rows\/swap-warmup-time$/, (m, b) => ["swap_warmup_time", { dragged_id: b.draggedId, target_id: b.targetId }]],
    ["POST", /^\/api\/reset$/, () => ["reset_rows", {}]],
    ["POST", /^\/api\/halls\/warmup$/, (m, b) => ["create_warmup_hall", { name: b.name }]],
    ["PATCH", /^\/api\/halls\/warmup$/, (m, b) => ["rename_warmup_hall", { old_name: b.oldName, new_name: b.newName }]],
    ["DELETE", /^\/api\/halls\/warmup$/, (m, b) => ["delete_warmup_hall", { name: b.name }]],
    ["POST", /^\/api\/halls\/warmup\/priority$/, (m, b) => ["set_priority_hall", { name: b.name }]],
    ["POST", /^\/api\/halls\/show$/, (m, b) => ["create_show_hall", { name: b.name }]],
    ["PATCH", /^\/api\/halls\/show$/, (m, b) => ["rename_show_hall", { old_name: b.oldName, new_name: b.newName }]],
    ["POST", /^\/api\/halls\/show\/starttime$/, (m, b) => ["set_show_hall_start_time", { name: b.name, start_time: b.startTime }]],
    ["DELETE", /^\/api\/halls\/show$/, (m, b) => ["delete_show_hall", { name: b.name }]],
  ];

  let py = null;
  let bridge = null;
  let planJson = "";
  let storageWarned = false;
  let externalChange = () => {};

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = () => reject(new Error(`kunne ikke hente ${src}`));
      document.head.appendChild(s);
    });
  }

  function readStored() {
    try { return localStorage.getItem(PLAN_KEY) || ""; } catch (e) { return ""; }
  }

  function store(json) {
    planJson = json;
    try {
      localStorage.setItem(PLAN_KEY, json);
    } catch (e) {
      if (!storageWarned) {
        storageWarned = true;
        alert("Planen kan ikke gemmes i denne browser (fx i et privat vindue). "
          + "Brug Gem plan under Haller, før du lukker siden.");
      }
    }
  }

  function loadStoredPlan() {
    const stored = readStored();
    const res = JSON.parse(bridge.load(stored));
    if (res.ok) {
      planJson = JSON.stringify(res.plan);
      return;
    }
    // Ulæselig plan: læg den til side, så den kan reddes, og start forfra.
    try {
      localStorage.setItem(`opvarmning_plan_broken_${Date.now()}`, stored);
      localStorage.removeItem(PLAN_KEY);
    } catch (e) { /* intet at gøre */ }
    planJson = "";
  }

  // save=false for rene læsninger: så skriver et besøg alene aldrig noget
  // i browseren (fx lige efter "Slet alle data").
  function answer(resJson, save = true) {
    const res = JSON.parse(resJson);
    if (!res.ok) throw new ApiError(res.error, res.status);
    if (save) store(JSON.stringify(res.plan));
    return res.payload;
  }

  const browserT = {
    async start(onStatus) {
      try {
        onStatus("Henter Python …");
        await loadScript("pyodide/pyodide.js");
        // Pyodide afbryder ikke selv, hvis hovedfilen ikke kan hentes (den
        // venter for evigt) — tjek den først, så brugeren får en besked.
        const wasmOk = await fetch("pyodide/pyodide.asm.wasm", { method: "HEAD" }).then((r) => r.ok, () => false);
        if (!wasmOk) throw new Error("pyodide.asm.wasm kunne ikke hentes");
        py = await loadPyodide({ indexURL: new URL("pyodide/", document.baseURI).href });
        onStatus("Henter pandas …");
        await py.loadPackage(["pandas"]);
        onStatus("Gør planlæggeren klar …");
        const sitePackages = py.runPython("import sysconfig; sysconfig.get_path('purelib')");
        for (const whl of config.wheels || []) {
          const buf = await (await fetch(`wheels/${whl}`)).arrayBuffer();
          py.unpackArchive(buf, "zip", { extractDir: sitePackages });
        }
        const code = await (await fetch("planner.zip")).arrayBuffer();
        py.unpackArchive(code, "zip", { extractDir: "/home/pyodide/app" });
        py.runPython("import sys; sys.path.insert(0, '/home/pyodide/app')");
        bridge = py.pyimport("planner.browser");
      } catch (e) {
        console.error(e);
        throw new ApiError("Kunne ikke indlæse planlæggeren. Tjek internetforbindelsen og genindlæs siden.", 0);
      }
      loadStoredPlan();
      window.addEventListener("storage", (e) => {
        if (e.key !== PLAN_KEY) return;
        loadStoredPlan();
        externalChange();
      });
    },
    async request(method, url, body) {
      const route = ROUTES.find(([m, re]) => m === method && re.test(url));
      if (!route) throw new ApiError(`Ukendt handling: ${method} ${url}`, 400);
      const [name, args] = route[2](url.match(route[1]), body || {});
      return answer(bridge.call(planJson, name, JSON.stringify(args)), name !== "payload");
    },
    async upload(files, hal) {
      const paths = [];
      for (const [i, f] of files.entries()) {
        const dir = `/tmp/upload_${Date.now()}_${i}`;
        py.FS.mkdirTree(dir);
        const path = `${dir}/${f.name}`;
        py.FS.writeFile(path, new Uint8Array(await f.arrayBuffer()));
        paths.push(path);
      }
      return answer(bridge.upload_files(planJson, JSON.stringify(paths), hal || ""));
    },
    async exportPlan() {
      const out = "/tmp/opvisning_med_opvarmning.xlsx";
      bridge.export_to(planJson, out);
      const bytes = py.FS.readFile(out);
      download(new Blob([bytes], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }),
        "opvisning_med_opvarmning.xlsx");
    },
    onExternalChange(cb) { externalChange = cb; },
    async savePlanFile() {
      download(new Blob([planJson || JSON.stringify(JSON.parse(bridge.load("")).plan)], { type: "application/json" }),
        "opvarmningsplan.json");
    },
    async openPlanFile(text) {
      const res = JSON.parse(bridge.import_plan(text));
      if (!res.ok) throw new ApiError(res.error, res.status);
      store(JSON.stringify(res.plan));
      return answer(bridge.call(planJson, "payload", "{}"));
    },
    clearAllData() {
      try {
        Object.keys(localStorage).filter((k) => k.startsWith("opvarmning_")).forEach((k) => localStorage.removeItem(k));
      } catch (e) { /* intet gemt */ }
    },
  };

  const transport = config.mode === "browser" ? browserT : server;

  return {
    mode: config.mode,
    planKey: PLAN_KEY,
    start: (onStatus) => transport.start(onStatus),
    request: (method, url, body) => transport.request(method, url, body),
    upload: (files, hal) => transport.upload(files, hal),
    exportPlan: () => transport.exportPlan(),
    onExternalChange: (cb) => transport.onExternalChange(cb),
    savePlanFile: () => transport.savePlanFile(),
    openPlanFile: (text) => transport.openPlanFile(text),
    clearAllData: () => transport.clearAllData(),
  };
})();
