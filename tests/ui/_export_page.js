// Shared by the UI checks of the export window (not a check itself: the runner only starts check_*.js). Builds the page the way check_export_ui.js does and gives a small kit to drive the window;
// the server of the test is in `server`: what the estimate says (info) and what the network check answers (check).
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

exports.openPage = function openPage(lang, debug) {
  let JSDOM, VirtualConsole;
  try {
    ({ JSDOM, VirtualConsole } = require("jsdom"));
  } catch (e) {
    console.log("SKIP: jsdom is not installed (run `npm install` in tests/ui to enable this check)");
    process.exit(0);
  }
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "vedetta-ui-"));
  const built = spawnSync(process.env.PYTHON || "python", [path.join(__dirname, "build_page.py"), out, lang], { cwd: path.join(__dirname, "..", "..", "vedetta"), encoding: "utf8" });
  if (built.status !== 0) { console.log("build_page.py failed:\n" + built.stdout + built.stderr); process.exit(1); }
  const html = fs.readFileSync(path.join(out, "page.html"), "utf8");
  const data = JSON.parse(fs.readFileSync(path.join(out, "data.json"), "utf8"));
  const L = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "locales", lang, "ha.json"), "utf8"));
  const errors = [], calls = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
  vc.on("error", (e) => errors.push("console.error: " + e));
  const server = { info: { daily: Array.from({ length: 90 }, (_, i) => 200000 + (i % 7) * 50000), base: 800000, ratio: 0.3, seal_factor: 1.34, limit: 20 * 1024 * 1024, horizon: 90, flagged: 0, survey: true },
                   check: { state: "ok", clients: 12 }, job: null };
  const dom = new JSDOM(html, {
    runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang + (debug ? "&debug=1" : ""),
    beforeParse(win) {
      win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
      win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); this.dispatchEvent(new win.Event("close")); };
      win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
      win.URL.createObjectURL = () => "blob:test"; win.URL.revokeObjectURL = () => {};
      win.HTMLElement.prototype.animate = function () { return { finish() {}, cancel() {}, set onfinish(f) { setTimeout(f, 0); }, set oncancel(f) {} }; };
      win.fetch = (url, opts) => {
        const method = (opts && opts.method) || "GET", body = opts && opts.body ? JSON.parse(opts.body) : null;
        calls.push({ url, method, body });
        const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob(["x"])), json: () => Promise.resolve(b) });
        if (url.startsWith("/api/export/info")) return ok(JSON.parse(JSON.stringify(server.info)));
        if (url === "/api/export/survey/check" && method === "POST") return server.check === "fail" ? Promise.reject(new Error("HTTP 500")) : ok(server.check);
        if (url === "/api/export/jobs" && method === "POST") return ok(server.job = { id: "j1", status: "running", steps: ["collect"], items: [], items_total: 0, fixed: 0, dest: body.dest });
        if (/^\/api\/export\/jobs\/j1/.test(url) && method === "DELETE") return ok({ ok: true });
        if (/^\/api\/export\/jobs\/j1/.test(url)) return ok(server.job);
        let b = {};
        if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
        else if (url.startsWith("/api/ha/summary")) b = data.summary;
        else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
        else if (url.startsWith("/api/ha/history?")) b = data.history_all;
        else if (url.startsWith("/api/ha/history/")) { const id = url.split("/")[4].split("?")[0]; b = Object.assign({ device_id: id }, url.includes("hours=168") ? data.history_7d[id] : data.history_all.devices[id]); }
        return ok(b);
      };
      win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
      win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
    },
  });
  const win = dom.window, doc = win.document;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const q = (s) => doc.querySelector(s), qa = (s) => Array.from(doc.querySelectorAll(s));
  const kit = { win, doc, L, server, calls, errors, wait, q, qa, failed: 0 };
  kit.check = (cond, msg) => { if (cond) console.log("ok:", msg); else { kit.failed++; console.log("FALLITO:", msg); } };
  kit.click = async (sel) => { const el = typeof sel === "string" ? q(sel) : sel; if (!el) throw new Error("manca " + sel); el.click(); await wait(20); };
  kit.dlg = () => q("#exportdlg");
  kit.openWindow = async () => { await kit.click("#btn-menu"); await kit.click("[data-export]"); await wait(60); };
  kit.reqs = (p) => calls.filter((c) => c.url.startsWith(p));
  kit.text = (key, n) => { const base = "js.ha.export.vlan." + key; const k = n === undefined ? base : base + (n === 1 ? "_one" : "_other"); return (L[k] || "").replace("{n}", n); };
  kit.finish = () => {
    if (errors.length) { console.log("errori della pagina:\n" + errors.join("\n")); kit.failed++; }
    console.log(kit.failed ? kit.failed + " verifiche FALLITE" : "TUTTO OK");
    process.exit(kit.failed ? 1 : 0);
  };
  return kit;
};
