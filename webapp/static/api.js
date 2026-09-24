"use strict";

// Ét sted hvor frontenden kalder handlinger. "server" bruger HTTP mod
// app.py; "browser" (Task 6) kører Python-motoren i browseren via Pyodide.

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const Api = (() => {
  const config = window.PLANNER_CONFIG || { mode: "server" };

  async function readJson(res) {
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new ApiError(data.error || `Noget gik galt (fejl ${res.status}).`, res.status);
    return data;
  }

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
  };

  const transport = server;

  return {
    mode: config.mode,
    start: (onStatus) => transport.start(onStatus),
    request: (method, url, body) => transport.request(method, url, body),
    upload: (files, hal) => transport.upload(files, hal),
    exportPlan: () => transport.exportPlan(),
  };
})();
