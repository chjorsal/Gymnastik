"use strict";

const ACTIVE_HAL_KEY = "opvarmning_active_hal_v2";
const ACTIVE_WARMUP_HAL_KEY = "opvarmning_active_warmup_hal_v1";
const EXPORT_NAME_KEY = "opvarmning_export_name_v1";

// Små valg der huskes i browseren. localStorage kan være spærret (fx i et
// privat vindue) — så huskes de bare ikke.
function readSetting(key) {
  try { return localStorage.getItem(key) || null; } catch (e) { return null; }
}
function saveSetting(key, value) {
  try { localStorage.setItem(key, value || ""); } catch (e) { /* ikke vigtigt */ }
}

let STATE = { warmupHalls: [], priorityHall: null, showHalls: [], rows: [], schedule: [] };
let activeHal = readSetting(ACTIVE_HAL_KEY);
// Siden åbner altid på oversigten.
let currentView = "oversigt";
// Valgte rækker under Program (flyt/slet flere på én gang). Gælder kun den
// aktive opvisningshal og nulstilles, når man skifter hal.
const selectedIds = new Set();
let lastSelectIndex = null;
let activeWarmupHal = readSetting(ACTIVE_WARMUP_HAL_KEY);
// Hallen, som filerne fra filvælgeren skal i, og hvad der skal ske med dem
// (sættes, lige før den åbnes). Uden handler indlæses de med det samme.
let uploadTarget = null;
let fileHandler = null;
// Kom i gang: filer lagt klar pr. opvisningshal, indlæses samlet med
// "Lav opvarmningsplan". Kun i hukommelsen — forsvinder ved genindlæsning.
const pendingFiles = new Map();

// ---------- Ikoner ----------
// Små håndrullede SVG-ikoner (stroke-baseret, arver farve via currentColor) —
// bruges i stedet for tekst-symboler (⠿ ✕ ★ ⚠) for et mere gennemført look.

const ICONS = {
  drag: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  starFilled: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
  starOutline: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
  warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  pin: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 4h6l-1 6 3 3H7l3-3z"/><line x1="12" y1="16" x2="12" y2="21"/></svg>',
  file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><polyline points="14 3 14 8 19 8"/><line x1="12" y1="18" x2="12" y2="12"/><polyline points="9 15 12 12 15 15"/></svg>',
};

function icon(name, extraClass) {
  const span = document.createElement("span");
  span.className = "icon" + (extraClass ? " " + extraClass : "");
  span.innerHTML = ICONS[name] || "";
  return span;
}

// Tekst med et lille træk-ikon foran (bruges på holdnavne i trækbare rækker).
function dragHandleText(text) {
  const span = document.createElement("span");
  span.className = "with-drag-icon";
  span.appendChild(icon("drag"));
  span.appendChild(document.createTextNode(text));
  return span;
}

// Rød advarselstekst med ikon foran (samme visuelle mønster overalt hvor et
// hold ikke kunne placeres).
function warningMessage(text) {
  const div = document.createElement("div");
  div.className = "problem-message small text-danger fw-semibold d-flex align-items-start gap-1 mt-1";
  div.appendChild(icon("warning"));
  div.appendChild(document.createTextNode(text));
  return div;
}

// ---------- API ----------

// Alle kald returnerer den nye state. Ved en fejl vises beskeden, og den
// nuværende STATE returneres uændret — så et "STATE = await ..." aldrig
// overskriver state med et fejlsvar.
async function handle(promise) {
  try {
    return await promise;
  } catch (e) {
    alert(e instanceof ApiError ? e.message : `Noget gik galt: ${e.message || e}`);
    return STATE;
  }
}
async function apiGet(url) {
  return handle(Api.request("GET", url));
}
async function apiJSON(url, method, body) {
  return handle(Api.request(method, url, body));
}
// Lad browseren gøre fx et Tab færdigt (fokus flyttet til næste felt), før
// siden tegnes forfra — så render() kan sætte fokus det rigtige sted igen.
// Browserudgaven svarer så hurtigt, at det ellers sker før fokus er flyttet.
function settle() {
  return new Promise((resolve) => setTimeout(resolve));
}

// Kør et kald, gem den nye state og tegn siden forfra.
async function update(request) {
  STATE = await request;
  await settle();
  render();
}

// ---------- Genbrugte UI-hjælpere ----------

function confirmAndRun(message, action) {
  return async () => {
    if (!confirm(message)) return;
    await update(action());
  };
}

function iconButton(iconName, label, onClick, extraClass) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "icon-btn" + (extraClass ? ` ${extraClass}` : "");
  btn.title = label;
  btn.setAttribute("aria-label", label);
  btn.appendChild(icon(iconName));
  btn.addEventListener("click", onClick);
  return btn;
}

// Gør et element til en trækbar kilde: sætter dataTransfer til id'et og
// toggler .dragging mens der trækkes.
function makeDragSource(el, id) {
  el.draggable = true;
  el.addEventListener("dragstart", (e) => {
    e.dataTransfer.setData("text/plain", id);
    el.classList.add("dragging");
  });
  el.addEventListener("dragend", () => el.classList.remove("dragging"));
}

// Trækker man filer fra computeren (og ikke et hold på siden)?
function hasFiles(e) {
  return Array.from((e.dataTransfer && e.dataTransfer.types) || []).includes("Files");
}

// Gør et element til et mål for hold, der trækkes rundt på siden: toggler
// .drag-over og kalder onDrop(draggedId, event). Filer ignoreres her.
function makeDropTarget(el, onDrop) {
  el.addEventListener("dragover", (e) => {
    if (hasFiles(e)) return;
    e.preventDefault();
    el.classList.add("drag-over");
  });
  el.addEventListener("dragleave", () => el.classList.remove("drag-over"));
  el.addEventListener("drop", async (e) => {
    if (hasFiles(e)) return;
    e.preventDefault();
    el.classList.remove("drag-over");
    const draggedId = e.dataTransfer.getData("text/plain");
    if (!draggedId) return;
    await onDrop(draggedId, e);
  });
}

// Gør et element til et sted, man kan slippe Excel-filer: alle filerne
// lægges i opvisningshallen hal (onFiles: indlæs nu, eller læg klar).
function makeFileDropTarget(el, hal, onFiles = uploadFiles) {
  el.addEventListener("dragover", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    el.classList.add("file-over");
  });
  el.addEventListener("dragleave", (e) => {
    if (!el.contains(e.relatedTarget)) el.classList.remove("file-over");
  });
  el.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    el.classList.remove("file-over");
    onFiles(e.dataTransfer.files, hal);
  });
}

function readonlyCell(text, extraClass) {
  const td = document.createElement("td");
  td.className = extraClass ? `${extraClass} readonly` : "readonly";
  td.textContent = text;
  return td;
}

function cell(child, className) {
  const td = document.createElement("td");
  if (className) td.className = className;
  td.appendChild(child);
  return td;
}

// ---------- Init ----------

async function init() {
  const boot = document.getElementById("boot");
  const bootText = document.getElementById("boot-text");
  if (Api.mode === "browser") boot.classList.remove("hidden");
  try {
    await Api.start((text) => { bootText.textContent = text; });
  } catch (e) {
    bootText.textContent = e.message;
    boot.classList.add("failed");
    return;
  }
  boot.classList.add("hidden");
  Api.onExternalChange(() => update(apiGet("/api/state")));
  setupExportDialog();
  // En adresse som .../#program åbner direkte på den visning.
  const fromHash = location.hash.slice(1);
  if (VIEWS.includes(fromHash)) currentView = fromHash;
  STATE = await apiGet("/api/state");
  if (!activeHal || !STATE.showHalls.some((h) => h.name === activeHal)) {
    activeHal = STATE.showHalls.length ? STATE.showHalls[0].name : null;
  }
  render();

  const fileInput = document.getElementById("file-input");
  fileInput.addEventListener("change", () => {
    const handler = fileHandler || uploadFiles;
    fileHandler = null;
    handler(fileInput.files, uploadTarget);
  });
  document.getElementById("btn-make-plan").addEventListener("click", onMakePlan);
  document.querySelectorAll("#btn-upload, .js-upload").forEach((btn) => {
    btn.addEventListener("click", () => chooseFiles(defaultUploadHal()));
  });
  // En fil sluppet uden for en hal må ikke få browseren til at åbne den.
  ["dragover", "drop"].forEach((type) => window.addEventListener(type, (e) => {
    if (!hasFiles(e) || e.defaultPrevented) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "none";
  }));
  document.getElementById("onb-warmup-form").addEventListener("submit", (e) => onHallCreate(e, "warmup"));
  document.getElementById("onb-show-form").addEventListener("submit", onShowHallCreate);
  document.querySelectorAll(".rail-link[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => setView(btn.dataset.view));
  });
  document.getElementById("btn-reset").addEventListener("click", onReset);
  document.getElementById("brand-home").addEventListener("click", () => setView("oversigt"));
  document.getElementById("bulk-move").addEventListener("click", onBulkMove);
  // Løsningen vises på oversigten, lige under den røde linje.
  document.getElementById("btn-solve-warmup").addEventListener("click", () => { setView("oversigt"); onSolve(); });
  document.getElementById("bulk-delete").addEventListener("click", onBulkDelete);
  document.getElementById("bulk-clear").addEventListener("click", () => {
    clearSelection();
    renderTable();
  });
  document.getElementById("select-all").addEventListener("change", (e) => {
    const rows = STATE.rows.filter((r) => r.opvisningHal === activeHal);
    clearSelection();
    if (e.target.checked) rows.forEach((r) => selectedIds.add(r.id));
    renderTable();
  });
  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { if (currentView === "oversigt") render(); }, 150);
  });
  document.getElementById("warmup-hall-form").addEventListener("submit", (e) => onHallCreate(e, "warmup"));
  document.getElementById("show-hall-form").addEventListener("submit", (e) => onHallCreate(e, "show"));

  document.getElementById("hal-start-time").addEventListener("change", onStartTimeChange);
  document.getElementById("btn-add-team").addEventListener("click", onAddTeam);
  document.querySelectorAll(".add-special").forEach((btn) => {
    btn.addEventListener("click", () => onAddSpecial(btn.dataset.type));
  });
  if (Api.mode === "browser") {
    document.getElementById("data-section").classList.remove("hidden");
    const planInput = document.getElementById("plan-file-input");
    document.getElementById("btn-save-plan").addEventListener("click", () => handle(Api.savePlanFile()));
    document.getElementById("btn-open-plan").addEventListener("click", () => planInput.click());
    planInput.addEventListener("change", () => onOpenPlan(planInput));
    document.getElementById("btn-clear-data").addEventListener("click", () => {
      if (!confirm("Slet planen og alle haller fra denne browser? Det kan ikke fortrydes.")) return;
      Api.clearAllData();
      location.reload();
    });
  }
}

// Opretter en opvisningshal med starttid i ét trin (fra "Kom i gang").
async function onShowHallCreate(e) {
  e.preventDefault();
  const [nameInput, timeInput] = e.target.querySelectorAll("input");
  const name = nameInput.value.trim();
  if (!name) return;
  STATE = await apiJSON("/api/halls/show", "POST", { name });
  if (timeInput.value.trim()) {
    STATE = await apiJSON("/api/halls/show/starttime", "POST", { name, startTime: timeInput.value.trim() });
  }
  nameInput.value = "";
  timeInput.value = "";
  if (!activeHal) selectHal(name);
  render();
  nameInput.focus();
}

// ---------- Indlæs Excel ----------

function chooseFiles(hal, handler = null) {
  uploadTarget = hal;
  fileHandler = handler;
  document.getElementById("file-input").click();
}

// Kun .xlsx. Andre filer nævnes i en besked og springes over.
function excelOnly(files) {
  const all = Array.from(files || []);
  const xlsx = all.filter((f) => f.name.toLowerCase().endsWith(".xlsx"));
  const skipped = all.filter((f) => !xlsx.includes(f));
  if (skipped.length) {
    alert(`Kun Excel-filer (.xlsx) kan indlæses. Sprunget over: ${skipped.map((f) => f.name).join(", ")}`);
  }
  return xlsx;
}

// Kom i gang: læg filerne klar under hallen (indlæses først ved "Lav opvarmningsplan").
function stageFiles(files, hal) {
  // Læs filerne, før filvælgeren tømmes — dens liste er "levende".
  const xlsx = excelOnly(files);
  document.getElementById("file-input").value = "";
  if (!xlsx.length || !hal) return;
  const list = pendingFiles.get(hal) || [];
  xlsx.forEach((f) => { if (!list.some((g) => g.name === f.name)) list.push(f); });
  pendingFiles.set(hal, list);
  render();
}

function unstageFile(hal, name) {
  const list = (pendingFiles.get(hal) || []).filter((f) => f.name !== name);
  if (list.length) pendingFiles.set(hal, list);
  else pendingFiles.delete(hal);
  render();
}

// Glem klar-lagte filer for haller, der ikke findes længere.
function prunePending() {
  [...pendingFiles.keys()].forEach((hal) => {
    if (!STATE.showHalls.some((h) => h.name === hal)) pendingFiles.delete(hal);
  });
}

async function onMakePlan() {
  // Hallernes rækkefølge, så holdene lander i samme orden som listen.
  const items = STATE.showHalls.flatMap((h) => (pendingFiles.get(h.name) || []).map((file) => ({ file, hal: h.name })));
  if (!items.length) return;
  const btn = document.getElementById("btn-make-plan");
  btn.disabled = true;
  const before = STATE;
  STATE = await handle(Api.uploadToHalls(items));
  if (STATE !== before) {
    pendingFiles.clear();
    selectHal(items[0].hal);
  }
  render();
}

// Knappen "Indlæs Excel": den hal, man står i under Program, ellers den
// første. null = ingen haller endnu; så opretter serveren "Hal 1".
function defaultUploadHal() {
  if (currentView === "program" && STATE.showHalls.some((h) => h.name === activeHal)) return activeHal;
  return STATE.showHalls.length ? STATE.showHalls[0].name : null;
}

// Alle filerne lægges i den samme opvisningshal (hal).
async function uploadFiles(files, hal) {
  // Læs filerne, før filvælgeren tømmes — dens liste er "levende".
  const xlsx = excelOnly(files);
  document.getElementById("file-input").value = "";
  if (!xlsx.length) return;
  const before = STATE;
  STATE = await handle(Api.upload(xlsx, hal));
  const landed = hal || (STATE.showHalls[0] && STATE.showHalls[0].name);
  if (STATE !== before && landed) selectHal(landed);
  render();
}

async function onOpenPlan(input) {
  const file = input.files[0];
  input.value = "";
  if (!file) return;
  if (STATE.rows.length && !confirm("Erstat den nuværende plan med planen fra filen?")) return;
  STATE = await handle(Api.openPlanFile(await file.text()));
  selectHal(STATE.showHalls.length ? STATE.showHalls[0].name : null);
  render();
}

async function onReset() {
  if (!confirm("Ryd alle indlæste hold? Hal-opsætningen bevares.")) return;
  await update(apiJSON("/api/reset", "POST", {}));
}

async function onHallCreate(e, kind) {
  e.preventDefault();
  const input = e.target.querySelector("input");
  const name = input.value.trim();
  if (!name) return;
  STATE = await apiJSON(`/api/halls/${kind}`, "POST", { name });
  input.value = "";
  if (kind === "show" && !activeHal) selectHal(name);
  render();
}

async function onStartTimeChange(e) {
  if (!activeHal) return;
  await update(apiJSON("/api/halls/show/starttime", "POST", { name: activeHal, startTime: e.target.value.trim() }));
}

// Hold tilmeldt på bagkant: 15 min opvisning og 15 min opvarmning, nederst
// i den valgte hal. Tiderne kan rettes bagefter i rækken.
async function onAddTeam() {
  if (!activeHal) return;
  const name = (prompt(`Navn på holdet, der skal tilføjes i ${activeHal}:`) || "").trim();
  if (!name) return;
  await update(apiJSON("/api/rows/team", "POST", { hal: activeHal, name }));
}

async function onAddSpecial(type) {
  if (!activeHal) return;
  await update(apiJSON("/api/rows/special", "POST", { hal: activeHal, type }));
}

// ---------- Hent Excel-plan ----------

// Forslag til filnavn, fx "Opvarmningsplan Arena og Hal2 19-10-2026".
function suggestedExportName() {
  const d = new Date();
  const date = [d.getDate(), d.getMonth() + 1].map((n) => String(n).padStart(2, "0")).concat(d.getFullYear()).join("-");
  const halls = STATE.showHalls.map((h) => h.name);
  return ["Opvarmningsplan", halls.length <= 2 ? halls.join(" og ") : "", date].filter(Boolean).join(" ");
}

function setupExportDialog() {
  const dialog = document.getElementById("export-dialog");
  const input = document.getElementById("export-name");
  const modal = bootstrap.Modal.getOrCreateInstance(dialog);
  document.getElementById("btn-export").addEventListener("click", () => {
    input.value = readSetting(EXPORT_NAME_KEY) || suggestedExportName();
    modal.show();
  });
  dialog.addEventListener("shown.bs.modal", () => { input.focus(); input.select(); });
  document.getElementById("export-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const name = input.value.trim().replace(/\.xlsx$/i, "").trim() || suggestedExportName();
    saveSetting(EXPORT_NAME_KEY, name);
    modal.hide();
    handle(Api.exportPlan(name));
  });
}

// ---------- Visning og valgt hal ----------

function saveActiveHal() {
  saveSetting(ACTIVE_HAL_KEY, activeHal);
}

function clearSelection() {
  selectedIds.clear();
  lastSelectIndex = null;
}

// Skift opvisningshal under Program (uden at tegne forfra).
function selectHal(name) {
  if (name !== activeHal) clearSelection();
  activeHal = name;
  saveActiveHal();
}

function setActiveHal(name) {
  selectHal(name);
  render();
}

// Åbn Program på en bestemt opvisningshal.
function openProgram(name) {
  selectHal(name);
  setView("program");
}

function setView(view) {
  currentView = view;
  render();
  window.scrollTo(0, 0);
}

function setActiveWarmupHal(name) {
  activeWarmupHal = name;
  saveSetting(ACTIVE_WARMUP_HAL_KEY, name);
  render();
}

function ensureActiveWarmupHal() {
  if (!STATE.warmupHalls.includes(activeWarmupHal)) activeWarmupHal = STATE.warmupHalls[0] || null;
}

// ---------- Render ----------

const VIEWS = ["oversigt", "program", "opvarmning"];

function unplacedRows() {
  return STATE.rows.filter((r) => r.needsWarmup && r.problemMessage);
}

function render() {
  // Bevar fokus i et redigerbart felt, når listen tegnes forfra (fx efter at
  // en ændring er gemt), så man kan blive ved med at taste/bruge piletasterne.
  const focusKey = document.activeElement && document.activeElement.dataset
    ? document.activeElement.dataset.focusKey : null;
  renderHalls();
  renderNav();
  renderPageHead();

  VIEWS.forEach((v) => {
    document.getElementById(`${v}-view`).classList.toggle("hidden", v !== currentView);
  });
  if (currentView === "oversigt") {
    renderOverview();
  } else if (currentView === "program") {
    renderHalTabs();
    renderToolbar();
    renderTable();
  } else {
    renderWarmupHalTabs();
    renderUnplacedWarmup();
    renderWarmupTable();
  }
  if (focusKey) {
    const again = document.querySelector(`[data-focus-key="${CSS.escape(focusKey)}"]`);
    if (again) again.focus();
  }
}

function renderNav() {
  document.querySelectorAll(".rail-link[data-view]").forEach((btn) => {
    const active = btn.dataset.view === currentView;
    btn.classList.toggle("active", active);
    if (active) btn.setAttribute("aria-current", "page");
    else btn.removeAttribute("aria-current");
  });
  const count = unplacedRows().length;
  const badge = document.getElementById("problem-count");
  badge.textContent = count;
  badge.title = `${count} hold mangler plads til opvarmning`;
  badge.classList.toggle("hidden", count === 0);
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function renderPageHead() {
  const title = document.getElementById("page-title");
  const sub = document.getElementById("page-sub");
  const teams = STATE.rows.filter((r) => r.needsWarmup).length;
  // Der er ingen plan at hente, før der er indlæst hold.
  document.getElementById("btn-export").classList.toggle("hidden", !teams);

  if (currentView === "oversigt") {
    if (!teams) {
      title.textContent = "Kom i gang";
      sub.textContent = "Tre trin, så er opvarmningsplanen klar.";
    } else {
      title.textContent = "Oversigt";
      sub.textContent = `${plural(teams, "hold", "hold")} i ${plural(STATE.showHalls.length, "opvisningshal", "opvisningshaller")}, `
        + `fordelt på ${plural(STATE.warmupHalls.length, "opvarmningshal", "opvarmningshaller")}.`;
    }
  } else if (currentView === "program") {
    title.textContent = "Program";
    sub.textContent = "";
  } else {
    title.textContent = "Opvarmning";
    sub.textContent = "";
  }
}

// ---------- Haller: fælles rækker til "Kom i gang" og sidepanelet ----------

// Tekstfelt der gemmer, når man forlader det. Et tomt felt fortryder.
function inlineInput(value, label, className, focusKey, onSave) {
  const input = document.createElement("input");
  input.type = "text";
  input.className = `form-control form-control-sm ${className}`;
  input.value = value;
  input.setAttribute("aria-label", label);
  input.dataset.focusKey = focusKey;
  input.addEventListener("change", async () => {
    const next = input.value.trim();
    if (!next || next === value) { input.value = value; return; }
    await onSave(next);
  });
  return input;
}

// where: "onb" (Kom i gang) eller "panel" (sidepanelet Haller) — så fokus
// kan findes igen i den rigtige liste, når siden tegnes forfra.
function warmupHallItem(name, index, where) {
  const isPrio = name === STATE.priorityHall;
  const li = document.createElement("li");
  li.className = "hall-item";
  const star = iconButton(isPrio ? "starFilled" : "starOutline",
    isPrio ? "Efterskolerne varmer op her først" : `Lad efterskolerne varme op i ${name} først`,
    () => update(apiJSON("/api/halls/warmup/priority", "POST", { name })), "star" + (isPrio ? " active" : ""));
  star.setAttribute("aria-pressed", String(isPrio));
  li.append(star, inlineInput(name, "Navn på opvarmningshal", "hall-name-input", `${where}-warmup:${index}`,
    (newName) => update(apiJSON("/api/halls/warmup", "PATCH", { oldName: name, newName }))));
  if (isPrio) {
    const prio = document.createElement("span");
    prio.className = "prio";
    prio.textContent = "Efterskoler først";
    li.appendChild(prio);
  }
  li.appendChild(iconButton("close", `Slet ${name}`, confirmAndRun(
    `Slet opvarmningshal "${name}"?`, () => apiJSON("/api/halls/warmup", "DELETE", { name })), "icon-btn-danger"));
  return li;
}

function showHallItem(hal, index, where) {
  const li = document.createElement("li");
  li.className = "hall-item";
  const row = document.createElement("div");
  row.className = "hall-item-row";
  const time = inlineInput(hal.startTime || "", `Starttid for ${hal.name}`, "hall-time-input", `${where}-show-time:${index}`,
    (startTime) => update(apiJSON("/api/halls/show/starttime", "POST", { name: hal.name, startTime })));
  time.placeholder = "09:00";
  row.append(
    inlineInput(hal.name, "Navn på opvisningshal", "hall-name-input", `${where}-show:${index}`, async (newName) => {
      const wasActive = activeHal === hal.name;
      STATE = await apiJSON("/api/halls/show", "PATCH", { oldName: hal.name, newName });
      const renamed = STATE.showHalls.some((h) => h.name === newName);
      if (wasActive && renamed) selectHal(newName);
      if (renamed && pendingFiles.has(hal.name)) {
        pendingFiles.set(newName, pendingFiles.get(hal.name));
        pendingFiles.delete(hal.name);
      }
      await settle();
      render();
    }),
    time,
    iconButton("close", `Slet ${hal.name}`, async () => {
      if (!confirm(`Slet opvisningshal "${hal.name}" og alle hold i den?`)) return;
      STATE = await apiJSON("/api/halls/show", "DELETE", { name: hal.name });
      if (activeHal === hal.name) selectHal(STATE.showHalls.length ? STATE.showHalls[0].name : null);
      render();
    }, "icon-btn-danger"),
  );
  li.appendChild(row);
  if (where === "onb") {
    // Kom i gang: filerne lægges klar her og indlæses først ved "Lav
    // opvarmningsplan", så man kan nå at lægge filer i alle hallerne.
    const staged = pendingFiles.get(hal.name) || [];
    staged.forEach((f) => li.appendChild(stagedFileChip(hal.name, f)));
    const drop = document.createElement("button");
    drop.type = "button";
    drop.className = "hall-drop" + (staged.length ? " has-files" : "");
    const choose = document.createElement("strong");
    choose.textContent = "vælg fil";
    drop.append(icon("file"),
      document.createTextNode(staged.length ? "Læg en fil mere hertil eller " : "Træk Excel-filen hertil eller "), choose);
    drop.addEventListener("click", () => chooseFiles(hal.name, stageFiles));
    li.appendChild(drop);
    makeFileDropTarget(li, hal.name, stageFiles);
  } else {
    // I sidepanelet kan man stadig slippe en fil på rækken (indlæses med det samme).
    makeFileDropTarget(li, hal.name);
  }
  return li;
}

// En fil, der ligger klar under en hal på Kom i gang, med et ✕ til at fjerne den.
function stagedFileChip(hal, file) {
  const chip = document.createElement("div");
  chip.className = "staged-file";
  const name = document.createElement("span");
  name.className = "staged-file-name";
  name.textContent = file.name;
  chip.append(icon("file"), name,
    iconButton("close", `Fjern ${file.name}`, () => unstageFile(hal, file.name), "icon-btn-danger"));
  return chip;
}

function renderHalls() {
  document.getElementById("warmup-hall-list")
    .replaceChildren(...STATE.warmupHalls.map((name, i) => warmupHallItem(name, i, "panel")));
  document.getElementById("show-hall-list")
    .replaceChildren(...STATE.showHalls.map((hal, i) => showHallItem(hal, i, "panel")));
}

// ---------- Oversigt ----------

function fmtMinutes(min) {
  const h = Math.floor(min / 60) % 24;
  return `${String(h).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
}

function halColor(name) {
  const i = STATE.showHalls.findIndex((h) => h.name === name);
  return `var(--hal-${(i < 0 ? 0 : i) % 5})`;
}

function renderOverview() {
  const teams = STATE.rows.filter((r) => r.needsWarmup);
  const onboarding = document.getElementById("onboarding");
  const data = document.getElementById("overview-data");
  onboarding.classList.toggle("hidden", teams.length > 0);
  data.classList.toggle("hidden", teams.length === 0);

  if (!teams.length) {
    renderOnboarding();
    return;
  }

  renderProblemBanner();
  renderOvernightBanner();
  renderSolveResult();
  renderTimeline(teams);
  renderShowHallSummary();
}

function renderOnboarding() {
  prunePending();
  const staged = [...pendingFiles.values()].reduce((n, list) => n + list.length, 0);
  const steps = [
    ["step-warmup", STATE.warmupHalls.length > 0],
    ["step-show", staged > 0],
    ["step-check", false],
  ];
  const make = document.getElementById("btn-make-plan");
  make.disabled = staged === 0;
  make.title = staged ? "" : "Læg mindst én Excel-fil klar under en opvisningshal først";
  const current = steps.find(([, done]) => !done);
  steps.forEach(([id, done]) => {
    const el = document.getElementById(id);
    el.classList.toggle("done", done);
    el.classList.toggle("current", current && current[0] === id);
  });
  document.getElementById("onb-warmup-list")
    .replaceChildren(...STATE.warmupHalls.map((name, i) => warmupHallItem(name, i, "onb")));
  document.getElementById("onb-show-list")
    .replaceChildren(...STATE.showHalls.map((hal, i) => showHallItem(hal, i, "onb")));
}

const DAY_END = 24 * 60;

// Hvornår en opvisningshals program slutter, i minutter fra dagens start
// (over 1440 = efter midnat). null hvis hallen er tom.
function hallEndMinutes(halName) {
  const rows = STATE.rows.filter((r) => r.opvisningHal === halName && r.opvisningMin !== null);
  if (!rows.length) return null;
  return Math.max(...rows.map((r) => r.opvisningMin + r.varighed));
}

// Rød linje øverst på oversigten med en tekst og en handling.
function setBanner(id, text, actionText, onClick) {
  const banner = document.getElementById(id);
  banner.classList.toggle("hidden", !text);
  if (!text) return;
  const action = document.createElement("span");
  action.className = "banner-action";
  action.textContent = actionText;
  banner.replaceChildren(icon("warning"), document.createTextNode(text), action);
  banner.onclick = onClick;
}

function renderProblemBanner() {
  const count = unplacedRows().length;
  setBanner("problem-banner", count ? `${plural(count, "hold mangler", "hold mangler")} plads til opvarmning.` : "",
    "Find løsning", onSolve);
  document.getElementById("problem-banner").title =
    "Forkort holdet og holdene omkring det (ned til 10 min, aldrig efterskoler eller DGI-hold)";
}

function renderOvernightBanner() {
  const late = STATE.showHalls
    .map((h) => ({ name: h.name, end: hallEndMinutes(h.name) }))
    .filter((h) => h.end !== null && h.end > DAY_END);
  const text = late.map((h) => `${h.name} slutter først kl. ${fmtMinutes(h.end)} om natten`).join(", og ");
  setBanner("overnight-banner",
    late.length ? `Programmet i ${text}. Fordel holdene på flere opvisningshaller under Program.` : "",
    "Åbn program", () => openProgram(late[0].name));
}

// "Find løsning" er den ene vej til at give hold uden plads en opvarmning.
// Resultatet gælder kun den plan, det blev beregnet for.
let solveResult = null;
let solveFor = null;
let solving = false;

async function onSolve() {
  if (solving) return;
  const box = document.getElementById("solve-result");
  solving = true;
  box.classList.remove("hidden");
  box.textContent = "Søger efter en løsning … (det kan tage op til et halvt minut)";
  await new Promise((r) => setTimeout(r, 30));   // lad teksten blive vist først
  const forState = STATE;
  try {
    solveResult = await Api.request("GET", "/api/solve");
    solveFor = forState;
  } catch (e) {
    solveResult = null;
    alert(e.message || "Kunne ikke finde en løsning.");
  }
  solving = false;
  renderSolveResult();
}

function smallButton(text, className, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = `btn btn-sm ${className}`;
  btn.textContent = text;
  btn.addEventListener("click", onClick);
  return btn;
}

function closeSolveResult() {
  solveResult = null;
  renderSolveResult();
}

function renderSolveResult() {
  const box = document.getElementById("solve-result");
  if (solving) return;   // søgning i gang
  if (!solveResult || solveFor !== STATE) {
    // planen er ændret siden — et gammelt resultat må ikke bruges
    solveResult = null;
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  box.replaceChildren();
  const { changes, moves, placed, remaining, hints } = solveResult;
  const line = (text) => {
    const p = document.createElement("p");
    p.textContent = text;
    box.appendChild(p);
    return p;
  };

  if (placed.length) {
    const total = placed.length + remaining.length;
    line(`${placed.length} af ${total} hold får plads (${placed.join(", ")}), hvis:`);
    const ul = document.createElement("ul");
    const where = (c) => `${c.hold} (går på ${c.opvisningTid} i ${c.opvisningHal})`;
    moves.forEach((m) => {
      const li = document.createElement("li");
      li.textContent = `${where(m)}: varmer op i ${m.toHal}`;
      ul.appendChild(li);
    });
    changes.forEach((c) => {
      const li = document.createElement("li");
      li.textContent = `${where(c)}: ${c.from} → ${c.to} min`;
      ul.appendChild(li);
    });
    box.appendChild(ul);
  } else if (!hints.length) {
    line("Ingen løsning fundet: der er ikke plads i nogen hal, heller ikke med 10 min opvarmning til holdene omkring. "
      + "Flyt holdet i programmet, eller træk det ind på tidslinjen.");
  }

  // Hold, du selv har låst til en hal, flyttes aldrig — men du får at vide,
  // hvor der er plads, og kan selv flytte holdet.
  hints.forEach((h) => {
    const p = line(`${h.hold} er låst til ${h.lockedHal}. Der er plads i ${h.freeHal}, hvis du flytter holdet. `);
    p.className = "solve-hint";
    p.appendChild(smallButton(`Flyt til ${h.freeHal}`, "btn-outline-secondary", () => {
      solveResult = null;
      return patchRow(h.id, "opvarmningHal", h.freeHal);
    }));
  });
  const hinted = new Set(hints.map((h) => h.hold));
  const stuck = remaining.filter((name) => !hinted.has(name));
  if (placed.length && stuck.length) {
    line(`Stadig uden plads: ${stuck.join(", ")}. Flyt holdet i programmet, eller træk det ind på tidslinjen.`);
  }

  const actionsEl = document.createElement("div");
  actionsEl.className = "solve-actions";
  if (placed.length) {
    actionsEl.append(
      smallButton("Brug løsningen", "btn-primary", () => {
        const payload = [
          ...changes.map((c) => ({ id: c.id, minutes: c.to })),
          ...moves.map((m) => ({ id: m.id, hal: m.toHal })),
        ];
        solveResult = null;
        return update(apiJSON("/api/solution", "POST", { changes: payload }));
      }),
      smallButton("Annullér", "btn-outline-secondary", closeSolveResult),
    );
  } else {
    actionsEl.append(smallButton("Luk", "btn-outline-secondary", closeSolveResult));
  }
  box.appendChild(actionsEl);
}

const TL_LABEL_W = 110;   // bredde på hal-navnene til venstre (px)

function renderTimeline(teams) {
  const el = document.getElementById("timeline");
  const legend = document.getElementById("timeline-legend");
  el.replaceChildren();
  legend.replaceChildren();

  // En dag løber fremad fra starttiden og slutter ved midnat. Det, der ligger
  // efter midnat, vises ikke her — oversigten advarer om det i stedet.
  const placed = teams.filter((r) => r.status === "OK" && r.opvarmningStart && r.opvarmningStartMin < DAY_END);
  // Hold uden plads vises i en rød række, hvor opvarmningen skulle have ligget:
  // lige op til holdets opvisning.
  const missing = teams
    .filter((r) => r.problemMessage && r.opvisningMin !== null && r.opvisningMin <= DAY_END)
    .map((r) => {
      const warm = r.opvarmningMinOverride ?? r.opvarmningMinDefault;
      const end = r.opvisningMin;
      return { row: r, start: end - warm, end };
    });

  if (!STATE.warmupHalls.length || (!placed.length && !missing.length)) {
    el.innerHTML = '<p class="text-body-secondary mb-0">Ingen hold har fået opvarmning endnu.</p>';
    return;
  }

  // Tidsaksen går fra hel time før første opvarmning til hel time efter sidste.
  const starts = placed.map((r) => r.opvarmningStartMin).concat(missing.map((m) => m.start));
  const ends = placed.map((r) => Math.min(r.opvarmningSlutMin, DAY_END)).concat(missing.map((m) => m.end));
  const from = Math.floor(Math.min(...starts) / 60) * 60;
  const to = Math.min(Math.ceil(Math.max(...ends) / 60) * 60, DAY_END);
  const span = Math.max(to - from, 60);

  // Hele pixels i stedet for procenter, så kanter og linjer står skarpt.
  const trackW = Math.max(el.clientWidth - TL_LABEL_W, 600);
  const px = (min) => Math.round(((min - from) / span) * trackW);
  // til træk-og-slip (og testen): pixel -> minut
  el.dataset.from = from;
  el.dataset.span = span;
  el.dataset.trackW = trackW;
  const minuteAt = (x) => Math.round((from + (x / trackW) * span) / 5) * 5;

  const gridLines = () => {
    const frag = document.createDocumentFragment();
    for (let t = from; t <= to; t += 60) {
      const line = document.createElement("span");
      line.className = "tl-hour";
      line.style.left = `${px(t)}px`;
      frag.appendChild(line);
    }
    return frag;
  };

  const axis = document.createElement("div");
  axis.className = "tl-axis";
  const axisTrack = document.createElement("div");
  axisTrack.className = "tl-track";
  for (let t = from; t <= to; t += 60) {
    const tick = document.createElement("span");
    tick.className = "tl-tick";
    tick.style.left = `${px(t)}px`;
    tick.textContent = fmtMinutes(t);
    axisTrack.appendChild(tick);
  }
  axis.append(document.createElement("span"), axisTrack);
  el.appendChild(axis);

  const addBlock = (track, { start, end, color, extraClass, title, onClick, dragId }) => {
    const left = px(start);
    const block = document.createElement("button");
    block.type = "button";
    block.className = "tl-block" + (extraClass ? ` ${extraClass}` : "");
    block.style.left = `${left}px`;
    block.style.width = `${Math.max(px(end) - left - 1, 3)}px`;  // 1px luft mellem blokke
    if (color) block.style.setProperty("--c", color);
    block.title = title;
    block.setAttribute("aria-label", title.replaceAll("\n", ", "));
    block.addEventListener("click", onClick);
    if (dragId) makeDragSource(block, dragId);
    track.appendChild(block);
  };

  const lane = (label, onLabelClick, extraClass) => {
    const row = document.createElement("div");
    row.className = "tl-lane" + (extraClass ? ` ${extraClass}` : "");
    const name = document.createElement("button");
    name.type = "button";
    name.className = "tl-lane-name";
    name.textContent = label;
    name.addEventListener("click", onLabelClick);
    const track = document.createElement("div");
    track.className = "tl-track";
    track.appendChild(gridLines());
    row.append(name, track);
    el.appendChild(row);
    return track;
  };

  STATE.warmupHalls.forEach((hal) => {
    const open = () => { activeWarmupHal = hal; setView("opvarmning"); };
    const track = lane(hal, open);
    // Slip et hold uden plads her: opvarmningen starter hvor det slippes
    // (rundet til 5 min). Serveren afviser, hvis der ikke er plads.
    makeDropTarget(track, (id, e) => {
      const start = fmtMinutes(minuteAt(e.clientX - track.getBoundingClientRect().left));
      return update(apiJSON(`/api/rows/${encodeURIComponent(id)}/place`, "POST", { hal, start }));
    });
    placed.filter((r) => r.opvarmningHalBeregnet === hal).forEach((r) => {
      addBlock(track, {
        start: r.opvarmningStartMin,
        end: Math.min(r.opvarmningSlutMin, DAY_END),
        color: halColor(r.opvisningHal),
        extraClass: r.opvarmningStartOverride ? "pinned" : "",
        title: `${r.hold}\nOpvarmning ${r.opvarmningStart}–${r.opvarmningSlut}\nGår på ${r.opvisningTid} i ${r.opvisningHal}`,
        onClick: open,
      });
    });
  });

  if (missing.length) {
    const open = () => setView("opvarmning");
    const track = lane("Mangler plads", open, "tl-lane-problem");
    missing.forEach(({ row: r, start, end }) => {
      addBlock(track, {
        start, end,
        extraClass: "problem",
        title: `${r.hold}\nMangler plads til opvarmning\nGår på ${r.opvisningTid} i ${r.opvisningHal}`
          + "\nTræk holdet op i en hal for at give det en opvarmningstid",
        onClick: open,
        dragId: r.id,
      });
    });
  }

  STATE.showHalls.forEach((h) => {
    const item = document.createElement("span");
    item.className = "legend-item";
    const sw = document.createElement("span");
    sw.className = "legend-swatch";
    sw.style.setProperty("--c", halColor(h.name));
    item.append(sw, document.createTextNode(h.name));
    legend.appendChild(item);
  });
}

function renderShowHallSummary() {
  const list = document.getElementById("show-hall-summary");
  list.replaceChildren();
  STATE.showHalls.forEach((hal) => {
    const teams = STATE.rows.filter((r) => r.opvisningHal === hal.name && r.needsWarmup);
    const problems = teams.filter((r) => r.problemMessage).length;
    const endMin = hallEndMinutes(hal.name);

    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "hall-row";
    btn.addEventListener("click", () => openProgram(hal.name));
    makeFileDropTarget(btn, hal.name);

    const dot = document.createElement("span");
    dot.className = "hall-row-dot";
    dot.style.setProperty("--c", halColor(hal.name));
    const name = document.createElement("span");
    name.className = "hall-row-name";
    name.textContent = hal.name;
    const time = document.createElement("span");
    time.className = endMin !== null && endMin > DAY_END ? "hall-row-problem" : "hall-row-time";
    time.textContent = endMin === null ? hal.startTime : `${hal.startTime}–${fmtMinutes(endMin)}`;
    const count = document.createElement("span");
    count.className = problems ? "hall-row-problem" : "hall-row-count";
    if (problems) count.textContent = `${problems} af ${plural(teams.length, "hold", "hold")} mangler opvarmning`;
    else count.textContent = teams.length ? plural(teams.length, "hold", "hold") : "Træk Excel-filen hertil";
    const open = document.createElement("span");
    open.className = "hall-row-open";
    open.textContent = "Åbn program";

    btn.append(dot, name, time, count, open);
    li.appendChild(btn);
    list.appendChild(li);
  });
}

// ---------- Faner ----------

// En fane med navn og antal hold (fx "Arena 38").
function tabButton(name, count, active, problemTitle, onClick) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "tab" + (active ? " active" : "") + (problemTitle ? " has-problem" : "");
  if (problemTitle) {
    btn.appendChild(icon("warning"));
    btn.title = problemTitle;
  }
  const badge = document.createElement("span");
  badge.className = "tab-count";
  badge.textContent = count;
  badge.setAttribute("aria-label", plural(count, "hold", "hold"));
  btn.append(document.createTextNode(name), badge);
  btn.addEventListener("click", onClick);
  return btn;
}

function renderHalTabs() {
  document.getElementById("hal-tabs").replaceChildren(...STATE.showHalls.map((hal) => {
    const hasProblem = STATE.rows.some((r) => r.opvisningHal === hal.name && r.problemMessage);
    const count = STATE.rows.filter((r) => r.opvisningHal === hal.name && r.needsWarmup).length;
    const btn = tabButton(hal.name, count, hal.name === activeHal,
      hasProblem ? "Der er hold i denne hal der ikke kan placeres" : "", () => setActiveHal(hal.name));
    makeFileDropTarget(btn, hal.name);
    return btn;
  }));
}

function renderWarmupHalTabs() {
  ensureActiveWarmupHal();
  document.getElementById("warmup-hal-tabs").replaceChildren(...STATE.warmupHalls.map((name) => {
    const hasProblem = STATE.rows.some((r) => r.opvarmningHalOverride === name && r.problemMessage);
    const count = STATE.rows.filter((r) => r.status === "OK" && r.opvarmningHalBeregnet === name).length;
    const btn = tabButton(name, count, name === activeWarmupHal,
      hasProblem ? "Et hold der er låst til denne hal kan ikke få plads" : "", () => setActiveWarmupHal(name));
    makeDropTarget(btn, (draggedId) => patchRow(draggedId, "opvarmningHal", name));
    return btn;
  }));
}

// ---------- Opvarmning ----------

// Opvarmningstid i minutter. Viser altid den tid, holdet faktisk får (fx 15),
// så piletasterne tæller derfra og ikke fra 0.
function buildWarmInput(row, focusPrefix) {
  const warmInput = document.createElement("input");
  warmInput.type = "number";
  warmInput.min = "0";
  warmInput.className = "form-control form-control-sm cell-input";
  warmInput.value = row.opvarmningMinOverride ?? row.opvarmningMinDefault;
  warmInput.dataset.focusKey = `${focusPrefix}:${row.id}`;
  warmInput.addEventListener("change", () => patchRow(row.id, "opvarmningMin", warmInput.value));
  return warmInput;
}

function buildMoveHalSelect(row) {
  const moveSelect = document.createElement("select");
  moveSelect.className = "form-select form-select-sm cell-input";
  [["", "Automatisk"], ...STATE.warmupHalls.map((name) => [name, name])].forEach(([value, label]) => {
    const o = document.createElement("option");
    o.value = value;
    o.textContent = label;
    o.selected = (row.opvarmningHalOverride || "") === value;
    moveSelect.appendChild(o);
  });
  moveSelect.addEventListener("change", () => patchRow(row.id, "opvarmningHal", moveSelect.value));
  return moveSelect;
}

// De sidste tre celler, som begge opvarmningstabeller har.
function appendWarmupCells(tr, row) {
  tr.append(
    readonlyCell(`${row.opvisningHal} ${row.opvisningTid}`, "narrow-col"),
    cell(buildWarmInput(row, "warmup-view"), "narrow-col"),
    cell(buildMoveHalSelect(row), "narrow-col"),
  );
}

function renderUnplacedWarmup() {
  const section = document.getElementById("unplaced-warmup-section");
  const tbody = document.getElementById("unplaced-warmup-body");
  const unplaced = unplacedRows();
  section.classList.toggle("hidden", !unplaced.length);
  document.getElementById("unplaced-title").replaceChildren(icon("warning"),
    document.createTextNode(`${plural(unplaced.length, "hold mangler", "hold mangler")} plads til opvarmning`));
  tbody.replaceChildren(...unplaced.map((row) => {
    const tr = document.createElement("tr");
    tr.className = "row-problem";
    tr.dataset.id = row.id;
    makeDragSource(tr, row.id);

    const holdText = dragHandleText(row.hold);
    holdText.classList.add("hold-name-readonly");
    const tdHold = cell(holdText, "hold-col");
    const pin = buildPinNote(row);
    if (pin) tdHold.appendChild(pin);
    tr.appendChild(tdHold);
    appendWarmupCells(tr, row);
    return tr;
  }));
}

// Viser et af de tre: tabellen, en tom-besked eller "ingen haller endnu".
function showOneOf(shown, ...ids) {
  ids.forEach((id) => document.getElementById(id).classList.toggle("hidden", id !== shown));
}

function renderWarmupTable() {
  ensureActiveWarmupHal();
  const states = ["warmup-table", "warmup-empty-state", "warmup-no-hal-state"];
  if (!activeWarmupHal) {
    showOneOf("warmup-no-hal-state", ...states);
    return;
  }
  const rows = STATE.rows
    .filter((r) => r.needsWarmup && r.status === "OK" && r.opvarmningHalBeregnet === activeWarmupHal)
    .sort((a, b) => (a.opvarmningStart || "").localeCompare(b.opvarmningStart || ""));
  showOneOf(rows.length ? "warmup-table" : "warmup-empty-state", ...states);

  document.getElementById("warmup-table-body").replaceChildren(...rows.map((row) => {
    const tr = document.createElement("tr");
    tr.dataset.id = row.id;
    tr.title = "Træk holdet hen på en anden hal-fane, eller hen på et tidligere hold for at bytte tid";
    makeDragSource(tr, row.id);
    makeDropTarget(tr, (draggedId) => {
      if (draggedId === row.id) return;
      return swapWarmupTime(draggedId, row.id);
    });

    const tdTime = readonlyCell(`${row.opvarmningStart}–${row.opvarmningSlut}`, "narrow-col warmup-time");
    const pin = buildPinNote(row);
    if (pin) tdTime.appendChild(pin);
    const holdText = dragHandleText(row.hold);
    holdText.classList.add("hold-name-readonly");
    tr.append(tdTime, cell(holdText, "hold-col"));
    appendWarmupCells(tr, row);
    return tr;
  }));
}

// ---------- Program ----------

function renderToolbar() {
  const toolbar = document.getElementById("hal-toolbar");
  const hal = STATE.showHalls.find((h) => h.name === activeHal);
  toolbar.classList.toggle("hidden", !hal);
  if (!hal) return;
  const startInput = document.getElementById("hal-start-time");
  if (document.activeElement !== startInput) {
    startInput.value = hal.startTime || "";
  }
}

function renderTable() {
  const states = ["teams-table", "empty-state", "no-hal-state"];
  if (!STATE.showHalls.length) {
    showOneOf("no-hal-state", ...states);
    return;
  }
  const rows = STATE.rows
    .filter((r) => r.opvisningHal === activeHal)
    .sort((a, b) => a.order - b.order);
  showOneOf(rows.length ? "teams-table" : "empty-state", ...states);
  if (!rows.length) return;

  // Fjern valg af rækker, der ikke længere findes i hallen.
  const present = new Set(rows.map((r) => r.id));
  [...selectedIds].forEach((id) => { if (!present.has(id)) selectedIds.delete(id); });
  renderTableBody(rows);
  renderBulkBar(rows);
}

function toggleSelect(rows, index, checked, shift) {
  if (shift && lastSelectIndex !== null) {
    const [a, b] = [Math.min(lastSelectIndex, index), Math.max(lastSelectIndex, index)];
    rows.slice(a, b + 1).forEach((r) => (checked ? selectedIds.add(r.id) : selectedIds.delete(r.id)));
  } else if (checked) {
    selectedIds.add(rows[index].id);
  } else {
    selectedIds.delete(rows[index].id);
  }
  lastSelectIndex = index;
  renderTable();
}

function renderBulkBar(rows) {
  const bar = document.getElementById("bulk-bar");
  const all = document.getElementById("select-all");
  const n = selectedIds.size;
  all.checked = rows.length > 0 && n === rows.length;
  all.indeterminate = n > 0 && n < rows.length;
  bar.classList.toggle("hidden", n === 0);
  if (!n) return;

  document.getElementById("bulk-count").textContent = `${n} valgt`;
  const target = document.getElementById("bulk-target");
  const others = STATE.showHalls.map((h) => h.name).filter((name) => name !== activeHal);
  const keep = others.includes(target.value) ? target.value : others[0];
  target.replaceChildren(...(others.length ? others : ["Ingen anden hal"]).map((name) => {
    const o = document.createElement("option");
    o.value = others.length ? name : "";
    o.textContent = name;
    return o;
  }));
  if (keep) target.value = keep;
  target.disabled = others.length === 0;
  const move = document.getElementById("bulk-move");
  move.disabled = others.length === 0;
  move.title = others.length ? "" : "Opret en opvisningshal mere under Haller for at kunne flytte";
}

async function onBulkMove() {
  const hal = document.getElementById("bulk-target").value;
  if (!hal || !selectedIds.size) return;
  const ids = [...selectedIds];
  clearSelection();
  await update(apiJSON("/api/rows/move", "POST", { ids, hal }));
}

async function onBulkDelete() {
  const n = selectedIds.size;
  if (!n || !confirm(`Slet ${n} valgte fra programmet? Det kan ikke fortrydes.`)) return;
  const ids = [...selectedIds];
  clearSelection();
  await update(apiJSON("/api/rows/delete", "POST", { ids }));
}

function renderTableBody(rows) {
  const tbody = document.getElementById("table-body");
  tbody.replaceChildren(...rows.map((row, index) => {
    const tr = document.createElement("tr");
    tr.dataset.id = row.id;
    if (!row.needsWarmup) tr.classList.add("row-special");
    if (row.problemMessage) tr.classList.add("row-problem");
    if (selectedIds.has(row.id)) tr.classList.add("selected");

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "form-check-input";
    cb.checked = selectedIds.has(row.id);
    cb.setAttribute("aria-label", `Vælg ${row.hold}`);
    cb.title = "Vælg (hold Shift nede for at vælge flere i træk)";
    cb.addEventListener("click", (e) => toggleSelect(rows, index, cb.checked, e.shiftKey));

    makeDragSource(tr, row.id);
    makeDropTarget(tr, (draggedId) => {
      if (draggedId === row.id) return;
      const ids = rows.map((r) => r.id);
      const from = ids.indexOf(draggedId);
      const to = ids.indexOf(row.id);
      if (from === -1 || to === -1) return;
      ids.splice(from, 1);
      ids.splice(to, 0, draggedId);
      return update(apiJSON("/api/rows/reorder", "POST", { hal: activeHal, orderedIds: ids }));
    });

    const tdHold = document.createElement("td");
    tdHold.className = "hold-col";
    if (row.needsWarmup && !row.manual) {
      // Rigtige holds navn kommer fra Excel-importen og kan ikke rettes her.
      const holdText = document.createElement("span");
      holdText.className = "hold-name-readonly";
      holdText.textContent = row.hold;
      tdHold.appendChild(holdText);
    } else {
      const holdInput = document.createElement("input");
      holdInput.type = "text";
      holdInput.className = "form-control form-control-sm cell-input";
      holdInput.value = row.hold;
      // Selv tilføjede hold kan omdøbes; specialpunkter vises i kursiv.
      holdInput.classList.add(row.manual ? "team-name" : "special-label");
      holdInput.addEventListener("change", () => patchRow(row.id, "hold", holdInput.value));
      tdHold.appendChild(holdInput);
    }
    if (row.problemMessage) {
      tdHold.appendChild(warningMessage(row.problemMessage));
    }

    const varighedInput = document.createElement("input");
    varighedInput.type = "number";
    varighedInput.min = "0";
    varighedInput.className = "form-control form-control-sm cell-input";
    varighedInput.value = row.varighed;
    varighedInput.dataset.focusKey = `program-dur:${row.id}`;
    varighedInput.addEventListener("change", () => patchRow(row.id, "varighed", varighedInput.value));

    const tdWarm = row.needsWarmup
      ? cell(buildWarmInput(row, "program-warm"), "narrow-col")
      : readonlyCell("—", "narrow-col");

    const halSelect = document.createElement("select");
    halSelect.className = "form-select form-select-sm cell-input";
    STATE.showHalls.forEach((hal) => {
      const o = document.createElement("option");
      o.value = hal.name;
      o.textContent = hal.name;
      o.selected = row.opvisningHal === hal.name;
      halSelect.appendChild(o);
    });
    halSelect.addEventListener("change", () => patchRow(row.id, "opvisningHal", halSelect.value));

    const del = iconButton("close", "Slet punkt", confirmAndRun(
      `Slet "${row.hold}" fra programmet?`,
      () => apiJSON(`/api/rows/${row.id}`, "DELETE")
    ), "row-delete icon-btn-danger");

    const tdDrag = cell(icon("drag"), "drag-col");
    tdDrag.title = "Træk for at flytte holdet";
    tr.append(
      cell(cb, "select-col"),
      tdDrag,
      tdHold,
      cell(varighedInput, "narrow-col"),
      tdWarm,
      readonlyCell(row.opvisningTid || "—", "narrow-col"),
      warmupCell(row),
      cell(halSelect, "narrow-col"),
      cell(del),
    );
    return tr;
  }));
}

// Hvor og hvornår holdet varmer op — så alt om et hold står i én række.
function warmupCell(row) {
  if (!row.needsWarmup) return readonlyCell("—", "warmup-col");
  if (row.status === "OK") {
    return readonlyCell(`${row.opvarmningHalBeregnet} ${row.opvarmningStart}–${row.opvarmningSlut}`, "warmup-col");
  }
  const td = document.createElement("td");
  td.className = "warmup-col warmup-missing";
  td.textContent = "Mangler plads";
  return td;
}

function patchRow(id, field, value) {
  return update(apiJSON(`/api/rows/${id}`, "PATCH", { field, value }));
}

function swapWarmupTime(draggedId, targetId) {
  return update(apiJSON("/api/rows/swap-warmup-time", "POST", { draggedId, targetId }));
}

// "fast tid · slip" under et hold, der er trukket til et bestemt tidspunkt.
// "slip" gør tiden automatisk igen. null hvis holdet ikke har en fast tid.
function buildPinNote(row) {
  if (!row.opvarmningStartOverride) return null;
  const note = document.createElement("div");
  note.className = "pin-note";
  const release = document.createElement("button");
  release.type = "button";
  release.className = "pin-release";
  release.textContent = "slip";
  release.title = `Holdet er låst til kl. ${row.opvarmningStartOverride}. Klik for at lade det blive placeret af sig selv igen.`;
  release.addEventListener("click", () => patchRow(row.id, "opvarmningStart", ""));
  note.append(icon("pin"), document.createTextNode("fast tid ·"), release);
  return note;
}

init();
