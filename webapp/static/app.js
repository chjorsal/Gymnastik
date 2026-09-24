"use strict";

const ACTIVE_HAL_KEY = "opvarmning_active_hal_v2";
const SCHEDULE_MODE_KEY = "opvarmning_schedule_mode_v1";
const ACTIVE_WARMUP_HAL_KEY = "opvarmning_active_warmup_hal_v1";

let STATE = { warmupHalls: [], priorityHall: null, showHalls: [], rows: [], schedule: [] };
let activeHal = localStorage.getItem(ACTIVE_HAL_KEY) || null;
let scheduleMode = localStorage.getItem(SCHEDULE_MODE_KEY) || "opvisning";
let activeWarmupHal = localStorage.getItem(ACTIVE_WARMUP_HAL_KEY) || null;

// ---------- Ikoner ----------
// Små håndrullede SVG-ikoner (stroke-baseret, arver farve via currentColor) —
// bruges i stedet for tekst-symboler (⠿ ✕ ★ ⚠) for et mere gennemført look.

const ICONS = {
  drag: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="9" cy="6" r="1.6"/><circle cx="15" cy="6" r="1.6"/><circle cx="9" cy="12" r="1.6"/><circle cx="15" cy="12" r="1.6"/><circle cx="9" cy="18" r="1.6"/><circle cx="15" cy="18" r="1.6"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>',
  starFilled: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
  starOutline: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>',
  warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
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

// Alle kald returnerer den nye state. Ved en fejl vises serverens besked,
// og den nuværende STATE returneres uændret — så et "STATE = await ..."
// aldrig overskriver state med et {error}-svar.
async function readState(res) {
  const data = await res.json().catch(() => ({}));
  if (res.ok) return data;
  alert(data.error || `Noget gik galt (fejl ${res.status}).`);
  return STATE;
}
async function apiGet(url) {
  return readState(await fetch(url));
}
async function apiJSON(url, method, body) {
  return readState(await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }));
}

// ---------- Genbrugte UI-hjælpere ----------
// (drag-og-slip og redigerbare/readonly celler bruges ens flere steder:
// hovedlisten, opvarmnings-tabellen og "ikke placeret"-listen)

function confirmAndRun(message, action) {
  return async () => {
    if (!confirm(message)) return;
    STATE = await action();
    render();
  };
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

// Gør et element til et droppable mål: toggler .drag-over og kalder
// onDrop(draggedId) når noget slippes ovenpå.
function makeDropTarget(el, onDrop) {
  el.addEventListener("dragover", (e) => {
    e.preventDefault();
    el.classList.add("drag-over");
  });
  el.addEventListener("dragleave", () => el.classList.remove("drag-over"));
  el.addEventListener("drop", async (e) => {
    e.preventDefault();
    el.classList.remove("drag-over");
    const draggedId = e.dataTransfer.getData("text/plain");
    if (!draggedId) return;
    await onDrop(draggedId);
  });
}

function readonlyCell(text, extraClass) {
  const td = document.createElement("td");
  td.className = extraClass ? `${extraClass} readonly` : "readonly";
  td.textContent = text;
  return td;
}

// ---------- Init ----------

async function init() {
  STATE = await apiGet("/api/state");
  if (!activeHal || !STATE.showHalls.some((h) => h.name === activeHal)) {
    activeHal = STATE.showHalls.length ? STATE.showHalls[0].name : null;
  }
  render();

  document.getElementById("upload-form").addEventListener("submit", onUpload);
  document.getElementById("btn-reset").addEventListener("click", onReset);
  document.getElementById("warmup-hall-form").addEventListener("submit", (e) => onHallCreate(e, "warmup"));
  document.getElementById("show-hall-form").addEventListener("submit", (e) => onHallCreate(e, "show"));

  document.getElementById("hal-start-time").addEventListener("change", onStartTimeChange);
  document.querySelectorAll(".add-special").forEach((btn) => {
    btn.addEventListener("click", () => onAddSpecial(btn.dataset.type));
  });
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", () => setScheduleMode(btn.dataset.mode));
  });
}

async function onUpload(e) {
  e.preventDefault();
  const input = document.getElementById("file-input");
  if (!input.files.length) return;
  const fd = new FormData();
  for (const f of input.files) fd.append("files", f);
  STATE = await readState(await fetch("/api/upload", { method: "POST", body: fd }));
  input.value = "";
  if (!activeHal && STATE.showHalls.length) {
    activeHal = STATE.showHalls[STATE.showHalls.length - 1].name;
  }
  render();
}

async function onReset() {
  if (!confirm("Ryd alle indlæste hold? Hal-opsætningen bevares.")) return;
  STATE = await apiJSON("/api/reset", "POST", {});
  render();
}

async function onHallCreate(e, kind) {
  e.preventDefault();
  const input = e.target.querySelector("input");
  const name = input.value.trim();
  if (!name) return;
  STATE = await apiJSON(`/api/halls/${kind}`, "POST", { name });
  input.value = "";
  if (kind === "show" && !activeHal) {
    activeHal = name;
    saveActiveHal();
  }
  render();
}

async function onStartTimeChange(e) {
  if (!activeHal) return;
  STATE = await apiJSON("/api/halls/show/starttime", "POST", { name: activeHal, startTime: e.target.value.trim() });
  render();
}

async function onAddSpecial(type) {
  if (!activeHal) return;
  STATE = await apiJSON("/api/rows/special", "POST", { hal: activeHal, type });
  render();
}

function saveActiveHal() {
  try { localStorage.setItem(ACTIVE_HAL_KEY, activeHal || ""); } catch (e) {}
}

function setActiveHal(name) {
  activeHal = name;
  saveActiveHal();
  render();
}

function setScheduleMode(mode) {
  scheduleMode = mode;
  try { localStorage.setItem(SCHEDULE_MODE_KEY, mode); } catch (e) {}
  render();
}

function setActiveWarmupHal(name) {
  activeWarmupHal = name;
  try { localStorage.setItem(ACTIVE_WARMUP_HAL_KEY, name || ""); } catch (e) {}
  render();
}

// Hop til det opvisningshold der hører til et opvarmningspunkt, så man kan
// rette det med det samme (varighed/opvarmningstid) i hovedlisten.
function jumpToRow(opvisningHal) {
  if (!opvisningHal) return;
  scheduleMode = "opvisning";
  try { localStorage.setItem(SCHEDULE_MODE_KEY, "opvisning"); } catch (e) {}
  activeHal = opvisningHal;
  saveActiveHal();
  render();
}

// ---------- Render ----------

function render() {
  renderHalls();
  renderSchedule();

  const opvisningView = document.getElementById("opvisning-view");
  const opvarmningView = document.getElementById("opvarmning-view");
  if (scheduleMode === "opvarmning") {
    opvisningView.classList.add("hidden");
    opvarmningView.classList.remove("hidden");
    renderUnplacedWarmup();
    renderWarmupTable();
  } else {
    opvarmningView.classList.add("hidden");
    opvisningView.classList.remove("hidden");
    renderHalTabs();
    renderToolbar();
    renderTable();
  }
}

function renderHalls() {
  const warmupList = document.getElementById("warmup-hall-list");
  warmupList.innerHTML = "";
  STATE.warmupHalls.forEach((name) => {
    const li = document.createElement("li");
    li.className = "list-group-item d-flex align-items-center gap-2 px-2 py-2";

    const star = document.createElement("span");
    star.className = "star icon-btn" + (STATE.priorityHall === name ? " active" : "");
    star.title = "Sæt som prioritetshal";
    star.appendChild(icon(STATE.priorityHall === name ? "starFilled" : "starOutline"));
    star.addEventListener("click", async () => {
      STATE = await apiJSON("/api/halls/warmup/priority", "POST", { name });
      render();
    });

    const input = document.createElement("input");
    input.type = "text";
    input.className = "form-control form-control-sm border-0 bg-transparent px-1";
    input.value = name;
    input.addEventListener("change", async () => {
      const newName = input.value.trim();
      if (!newName || newName === name) { input.value = name; return; }
      STATE = await apiJSON("/api/halls/warmup", "PATCH", { oldName: name, newName });
      render();
    });

    const del = document.createElement("span");
    del.className = "del icon-btn icon-btn-danger";
    del.appendChild(icon("close"));
    del.title = "Slet hal";
    del.addEventListener("click", confirmAndRun(
      `Slet opvarmningshal "${name}"?`,
      () => apiJSON("/api/halls/warmup", "DELETE", { name })
    ));

    li.append(star, input, del);
    warmupList.appendChild(li);
  });

  const showList = document.getElementById("show-hall-list");
  showList.innerHTML = "";
  STATE.showHalls.forEach((hal) => {
    const li = document.createElement("li");
    li.className = "list-group-item d-flex align-items-center gap-2 px-2 py-2";

    const input = document.createElement("input");
    input.type = "text";
    input.className = "form-control form-control-sm border-0 bg-transparent px-1";
    input.value = hal.name;
    input.addEventListener("change", async () => {
      const newName = input.value.trim();
      if (!newName || newName === hal.name) { input.value = hal.name; return; }
      const wasActive = activeHal === hal.name;
      STATE = await apiJSON("/api/halls/show", "PATCH", { oldName: hal.name, newName });
      if (wasActive) { activeHal = newName; saveActiveHal(); }
      render();
    });

    const timeInput = document.createElement("input");
    timeInput.type = "text";
    timeInput.className = "form-control form-control-sm hall-time-input";
    timeInput.placeholder = "HH:MM";
    timeInput.value = hal.startTime || "";
    timeInput.title = "Startklokkeslæt";
    timeInput.addEventListener("change", async () => {
      STATE = await apiJSON("/api/halls/show/starttime", "POST", { name: hal.name, startTime: timeInput.value.trim() });
      render();
    });

    const del = document.createElement("span");
    del.className = "del icon-btn icon-btn-danger";
    del.appendChild(icon("close"));
    del.title = "Slet hal (og alle hold i den)";
    del.addEventListener("click", async () => {
      if (!confirm(`Slet opvisningshal "${hal.name}" og alle hold i den?`)) return;
      STATE = await apiJSON("/api/halls/show", "DELETE", { name: hal.name });
      if (activeHal === hal.name) {
        activeHal = STATE.showHalls.length ? STATE.showHalls[0].name : null;
        saveActiveHal();
      }
      render();
    });

    li.append(input, timeInput, del);
    showList.appendChild(li);
  });
}

function renderSchedule() {
  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.mode === scheduleMode);
  });

  const warmupTabs = document.getElementById("warmup-hal-tabs");
  if (scheduleMode === "opvarmning") {
    warmupTabs.classList.remove("hidden");
    renderWarmupHalTabs();
    renderWarmupSchedule();
  } else {
    warmupTabs.classList.add("hidden");
    renderOpvisningSchedule();
  }
}

function renderOpvisningSchedule() {
  const el = document.getElementById("schedule-list");
  el.innerHTML = "";

  if (!activeHal) {
    el.innerHTML = '<div class="schedule-empty">Vælg en opvisningshal for at se dens tidsplan.</div>';
    return;
  }

  const items = STATE.schedule.filter((item) => item.opvisningHal === activeHal);
  if (!items.length) {
    el.innerHTML = '<div class="schedule-empty">Ingen programpunkter i denne hal endnu.</div>';
    return;
  }
  items.forEach((item) => {
    const div = document.createElement("div");
    div.className = "schedule-item" + (!item.needsWarmup ? " schedule-special" : "");
    const tid = document.createElement("span");
    tid.className = "tid";
    tid.textContent = item.tid;
    const hold = document.createElement("span");
    hold.className = "hold";
    hold.textContent = item.hold;
    hold.title = item.hold;
    div.append(tid, hold);
    el.appendChild(div);
  });
}

function renderWarmupHalTabs() {
  const el = document.getElementById("warmup-hal-tabs");
  el.innerHTML = "";
  if (!activeWarmupHal || !STATE.warmupHalls.includes(activeWarmupHal)) {
    activeWarmupHal = STATE.warmupHalls.length ? STATE.warmupHalls[0] : null;
  }
  STATE.warmupHalls.forEach((name) => {
    const hasProblem = STATE.rows.some(
      (r) => r.opvarmningHalOverride === name && r.problemMessage
    );
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "nav-link d-inline-flex align-items-center gap-1"
      + (name === activeWarmupHal ? " active" : "")
      + (hasProblem ? " nav-link-danger" : "");
    if (hasProblem) btn.appendChild(icon("warning"));
    btn.appendChild(document.createTextNode(name));
    if (hasProblem) btn.title = "Et hold der er låst til denne hal kan ikke få plads";
    btn.addEventListener("click", () => setActiveWarmupHal(name));
    makeDropTarget(btn, (draggedId) => patchRow(draggedId, "opvarmningHal", name));
    el.appendChild(btn);
  });
}

function renderWarmupSchedule() {
  const el = document.getElementById("schedule-list");
  el.innerHTML = "";

  const unplaced = STATE.rows.filter((r) => r.needsWarmup && r.problemMessage);
  if (unplaced.length) {
    const heading = document.createElement("div");
    heading.className = "schedule-subheading schedule-subheading-danger";
    heading.textContent = `Ikke placeret (${unplaced.length})`;
    el.appendChild(heading);
    unplaced.forEach((row) => {
      const div = document.createElement("div");
      div.className = "schedule-item schedule-danger";
      div.title = row.problemMessage;
      div.addEventListener("click", () => jumpToRow(row.opvisningHal));
      const tid = document.createElement("span");
      tid.className = "tid";
      tid.appendChild(icon("warning"));
      const hold = document.createElement("span");
      hold.className = "hold";
      hold.textContent = row.hold;
      hold.title = row.hold;
      const hal = document.createElement("span");
      hal.className = "hal";
      hal.textContent = row.opvisningHal;
      div.append(tid, hold, hal);
      el.appendChild(div);
    });
  }

  if (!STATE.warmupHalls.length) {
    const empty = document.createElement("div");
    empty.className = "schedule-empty";
    empty.textContent = "Ingen opvarmningshaller oprettet endnu.";
    el.appendChild(empty);
    return;
  }

  const hint = document.createElement("div");
  hint.className = "schedule-empty";
  hint.textContent = "Vælg en hal ovenfor for at se og rette dens opvarmningstider i listen til højre.";
  el.appendChild(hint);
}

// Den redigerbare visning for én specifik opvarmningshal: viser hvilke hold
// der varmer op der, hvornår de går på og i hvilken opvisningshal — kun
// opvarmningstiden kan rettes herfra.
function buildWarmInput(row) {
  const warmInput = document.createElement("input");
  warmInput.type = "number";
  warmInput.min = "0";
  warmInput.className = "form-control form-control-sm cell-input";
  warmInput.placeholder = String(row.opvarmningMinDefault);
  warmInput.value = row.opvarmningMinOverride === null || row.opvarmningMinOverride === undefined
    ? "" : row.opvarmningMinOverride;
  warmInput.addEventListener("change", () => patchRow(row.id, "opvarmningMin", warmInput.value));
  return warmInput;
}

function buildMoveHalSelect(row) {
  const moveSelect = document.createElement("select");
  moveSelect.className = "form-select form-select-sm cell-input";
  const autoOpt = document.createElement("option");
  autoOpt.value = "";
  autoOpt.textContent = "Automatisk";
  if (!row.opvarmningHalOverride) autoOpt.selected = true;
  moveSelect.appendChild(autoOpt);
  STATE.warmupHalls.forEach((name) => {
    const o = document.createElement("option");
    o.value = name;
    o.textContent = name;
    if (row.opvarmningHalOverride === name) o.selected = true;
    moveSelect.appendChild(o);
  });
  moveSelect.addEventListener("change", () => patchRow(row.id, "opvarmningHal", moveSelect.value));
  return moveSelect;
}

function renderUnplacedWarmup() {
  const section = document.getElementById("unplaced-warmup-section");
  const tbody = document.getElementById("unplaced-warmup-body");
  tbody.innerHTML = "";

  const unplaced = STATE.rows.filter((r) => r.needsWarmup && r.problemMessage);
  if (!unplaced.length) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");

  unplaced.forEach((row) => {
    const tr = document.createElement("tr");
    tr.className = "table-danger";
    tr.dataset.id = row.id;
    makeDragSource(tr, row.id);

    const tdHold = document.createElement("td");
    tdHold.className = "hold-col";
    const holdText = dragHandleText(row.hold);
    holdText.classList.add("hold-name-readonly");
    const unpinUnplaced = buildUnpinButton(row);
    if (unpinUnplaced) holdText.appendChild(unpinUnplaced);
    tdHold.appendChild(holdText);
    if (row.problemMessage) {
      tdHold.appendChild(warningMessage(row.problemMessage));
    }
    tr.appendChild(tdHold);

    tr.appendChild(readonlyCell(row.opvisningHal));
    tr.appendChild(readonlyCell(row.opvisningTid, "narrow-col"));

    const tdWarm = document.createElement("td");
    tdWarm.className = "narrow-col";
    tdWarm.appendChild(buildWarmInput(row));
    tr.appendChild(tdWarm);

    const tdMoveHal = document.createElement("td");
    tdMoveHal.className = "narrow-col";
    tdMoveHal.appendChild(buildMoveHalSelect(row));
    tr.appendChild(tdMoveHal);

    tbody.appendChild(tr);
  });
}

function renderWarmupTable() {
  const table = document.getElementById("warmup-table");
  const emptyState = document.getElementById("warmup-empty-state");
  const noHalState = document.getElementById("warmup-no-hal-state");
  const title = document.getElementById("warmup-view-title");

  if (!activeWarmupHal || !STATE.warmupHalls.includes(activeWarmupHal)) {
    activeWarmupHal = STATE.warmupHalls.length ? STATE.warmupHalls[0] : null;
  }

  if (!activeWarmupHal) {
    title.textContent = "";
    table.classList.add("hidden");
    emptyState.classList.add("hidden");
    noHalState.classList.remove("hidden");
    return;
  }
  noHalState.classList.add("hidden");
  title.textContent = activeWarmupHal;

  const rows = STATE.rows
    .filter((r) => r.needsWarmup && r.status === "OK" && r.opvarmningHalBeregnet === activeWarmupHal)
    .sort((a, b) => (a.opvarmningStart || "").localeCompare(b.opvarmningStart || ""));

  if (!rows.length) {
    table.classList.add("hidden");
    emptyState.classList.remove("hidden");
    return;
  }
  table.classList.remove("hidden");
  emptyState.classList.add("hidden");

  const tbody = document.getElementById("warmup-table-body");
  tbody.innerHTML = "";

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.dataset.id = row.id;
    tr.title = "Træk til en hal-fane for at flytte holdet, eller træk hen på et tidligere hold i listen for at bytte opvarmningstid med det";
    makeDragSource(tr, row.id);
    makeDropTarget(tr, (draggedId) => {
      if (draggedId === row.id) return;
      return swapWarmupTime(draggedId, row.id);
    });

    const tdTime = readonlyCell(`${row.opvarmningStart}–${row.opvarmningSlut}`, "narrow-col");
    const unpinTime = buildUnpinButton(row);
    if (unpinTime) tdTime.appendChild(unpinTime);
    tr.appendChild(tdTime);
    const tdHold = document.createElement("td");
    tdHold.className = "readonly";
    tdHold.appendChild(dragHandleText(row.hold));
    tr.appendChild(tdHold);
    tr.appendChild(readonlyCell(row.opvisningHal));
    tr.appendChild(readonlyCell(row.opvisningTid, "narrow-col"));

    const tdWarm = document.createElement("td");
    tdWarm.className = "narrow-col";
    tdWarm.appendChild(buildWarmInput(row));
    tr.appendChild(tdWarm);

    const tdMoveHal = document.createElement("td");
    tdMoveHal.className = "narrow-col";
    tdMoveHal.appendChild(buildMoveHalSelect(row));
    tr.appendChild(tdMoveHal);

    tbody.appendChild(tr);
  });
}

function renderHalTabs() {
  const el = document.getElementById("hal-tabs");
  el.innerHTML = "";
  STATE.showHalls.forEach((hal) => {
    const hasProblem = STATE.rows.some((r) => r.opvisningHal === hal.name && r.problemMessage);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "nav-link d-inline-flex align-items-center gap-1"
      + (hal.name === activeHal ? " active" : "")
      + (hasProblem ? " nav-link-danger" : "");
    if (hasProblem) btn.appendChild(icon("warning"));
    btn.appendChild(document.createTextNode(hal.name));
    if (hasProblem) btn.title = "Der er hold i denne hal der ikke kan placeres";
    btn.addEventListener("click", () => setActiveHal(hal.name));
    el.appendChild(btn);
  });
}

function renderToolbar() {
  const toolbar = document.getElementById("hal-toolbar");
  const hal = STATE.showHalls.find((h) => h.name === activeHal);
  if (!hal) {
    toolbar.classList.add("hidden");
    return;
  }
  toolbar.classList.remove("hidden");
  const startInput = document.getElementById("hal-start-time");
  if (document.activeElement !== startInput) {
    startInput.value = hal.startTime || "";
  }
}

function renderTable() {
  const table = document.getElementById("teams-table");
  const emptyState = document.getElementById("empty-state");
  const noHalState = document.getElementById("no-hal-state");

  if (!STATE.showHalls.length) {
    table.classList.add("hidden");
    emptyState.classList.add("hidden");
    noHalState.classList.remove("hidden");
    return;
  }
  noHalState.classList.add("hidden");

  const rows = STATE.rows
    .filter((r) => r.opvisningHal === activeHal)
    .sort((a, b) => a.order - b.order);

  if (!rows.length) {
    table.classList.add("hidden");
    emptyState.classList.remove("hidden");
    return;
  }
  table.classList.remove("hidden");
  emptyState.classList.add("hidden");

  renderTableBody(rows);
}

function renderTableBody(rows) {
  const tbody = document.getElementById("table-body");
  tbody.innerHTML = "";

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.dataset.id = row.id;
    if (!row.needsWarmup) tr.classList.add("row-special");
    if (row.problemMessage) tr.classList.add("table-danger");

    makeDragSource(tr, row.id);
    makeDropTarget(tr, async (draggedId) => {
      if (draggedId === row.id) return;
      const ids = rows.map((r) => r.id);
      const from = ids.indexOf(draggedId);
      const to = ids.indexOf(row.id);
      if (from === -1 || to === -1) return;
      ids.splice(from, 1);
      ids.splice(to, 0, draggedId);
      STATE = await apiJSON("/api/rows/reorder", "POST", { hal: activeHal, orderedIds: ids });
      render();
    });

    const tdDrag = document.createElement("td");
    tdDrag.className = "drag-col";
    tdDrag.appendChild(icon("drag"));
    tr.appendChild(tdDrag);

    const tdHold = document.createElement("td");
    tdHold.className = "hold-col";
    if (row.needsWarmup) {
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
      holdInput.classList.add("special-label");
      holdInput.addEventListener("change", () => patchRow(row.id, "hold", holdInput.value));
      tdHold.appendChild(holdInput);
    }
    if (row.problemMessage) {
      tdHold.appendChild(warningMessage(row.problemMessage));
    }
    tr.appendChild(tdHold);

    const tdVarighed = document.createElement("td");
    tdVarighed.className = "narrow-col";
    const varighedInput = document.createElement("input");
    varighedInput.type = "number";
    varighedInput.min = "0";
    varighedInput.className = "form-control form-control-sm cell-input";
    varighedInput.value = row.varighed;
    varighedInput.addEventListener("change", () => patchRow(row.id, "varighed", varighedInput.value));
    tdVarighed.appendChild(varighedInput);
    tr.appendChild(tdVarighed);

    const tdWarm = document.createElement("td");
    tdWarm.className = "narrow-col";
    if (row.needsWarmup) {
      const warmInput = document.createElement("input");
      warmInput.type = "number";
      warmInput.min = "0";
      warmInput.className = "form-control form-control-sm cell-input";
      warmInput.placeholder = String(row.opvarmningMinDefault);
      warmInput.value = row.opvarmningMinOverride === null || row.opvarmningMinOverride === undefined
        ? "" : row.opvarmningMinOverride;
      warmInput.addEventListener("change", () => patchRow(row.id, "opvarmningMin", warmInput.value));
      tdWarm.appendChild(warmInput);
    } else {
      tdWarm.classList.add("readonly");
      tdWarm.textContent = "—";
    }
    tr.appendChild(tdWarm);

    tr.appendChild(readonlyCell(row.opvisningTid || "—", "narrow-col"));

    const tdMoveHal = document.createElement("td");
    tdMoveHal.className = "narrow-col";
    const halSelect = document.createElement("select");
    halSelect.className = "form-select form-select-sm cell-input";
    STATE.showHalls.forEach((hal) => {
      const o = document.createElement("option");
      o.value = hal.name;
      o.textContent = hal.name;
      if (row.opvisningHal === hal.name) o.selected = true;
      halSelect.appendChild(o);
    });
    halSelect.addEventListener("change", () => patchRow(row.id, "opvisningHal", halSelect.value));
    tdMoveHal.appendChild(halSelect);
    tr.appendChild(tdMoveHal);

    const tdAction = document.createElement("td");
    const del = document.createElement("button");
    del.type = "button";
    del.className = "row-delete icon-btn icon-btn-danger";
    del.appendChild(icon("close"));
    del.title = "Slet punkt";
    del.addEventListener("click", confirmAndRun(
      `Slet "${row.hold}" fra programmet?`,
      () => apiJSON(`/api/rows/${row.id}`, "DELETE")
    ));
    tdAction.appendChild(del);
    tr.appendChild(tdAction);

    tbody.appendChild(tr);
  });
}

async function patchRow(id, field, value) {
  STATE = await apiJSON(`/api/rows/${id}`, "PATCH", { field, value });
  render();
}

async function swapWarmupTime(draggedId, targetId) {
  STATE = await apiJSON("/api/rows/swap-warmup-time", "POST", { draggedId, targetId });
  render();
}

// Lille knap der fjerner et fast opvarmningstidspunkt (sat ved træk-og-slip),
// så holdet igen placeres automatisk. null hvis holdet ikke har et.
function buildUnpinButton(row) {
  if (!row.opvarmningStartOverride) return null;
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "icon-btn";
  btn.title = `Fast tidspunkt ${row.opvarmningStartOverride} — klik for at gøre det automatisk igen`;
  btn.appendChild(icon("close"));
  btn.addEventListener("click", () => patchRow(row.id, "opvarmningStart", ""));
  return btn;
}

init();
