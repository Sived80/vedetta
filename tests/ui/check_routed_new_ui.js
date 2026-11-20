// 1.0 step P11: a new device behind the router in the card of the new devices. It has an address and no MAC (Home Assistant did not say
// it): the row shows the address and no MAC, «Ignore» ignores it by address (/api/ignored/hosts, never the list by MAC), and the notice of a
// second one names the new one (the page tells the devices apart by address when there is no MAC).
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_routed_new_ui.js [it|en]
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

let JSDOM, VirtualConsole;
try {
  ({ JSDOM, VirtualConsole } = require("jsdom"));
} catch (e) {
  console.log("SKIP: jsdom is not installed (run `npm install` in tests/ui to enable this check)");
  process.exit(0);
}

const lang = process.argv[2] || "it";
const out = fs.mkdtempSync(path.join(os.tmpdir(), "vedetta-ui-"));
const built = spawnSync(process.env.PYTHON || "python", [path.join(__dirname, "build_page.py"), out, lang], { cwd: path.join(__dirname, "..", "..", "vedetta"), encoding: "utf8" });
if (built.status !== 0) { console.log("build_page.py failed:\n" + built.stdout + built.stderr); process.exit(1); }
const html = fs.readFileSync(path.join(out, "page.html"), "utf8");
const data = JSON.parse(fs.readFileSync(path.join(out, "data.json"), "utf8"));

const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
vc.on("error", (e) => errors.push("console.error: " + e));
const HOSTS = [];
const sources = [];
const calls = [];
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
  beforeParse(win) {
    win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
    win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
    win.HTMLElement.prototype.scrollIntoView = function () {};
    win.TextDecoder = require("util").TextDecoder;
    win.fetch = (url, opts) => {
      const method = (opts && opts.method) || "GET", body = opts && opts.body ? JSON.parse(opts.body) : null;
      calls.push({ url, method, body });
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      if (url === "/api/scan/quick") return ok(HOSTS);
      if (url === "/api/devices/add") return ok({ ok: true });
      if (url.startsWith("/api/new-devices")) return ok([]);
      if (url === "/api/scan/cancel") return ok({ ok: true });
      let b = {};
      if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
      else if (url.startsWith("/api/ha/summary")) b = data.summary;
      else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
      else if (url.startsWith("/api/ha/history?")) b = data.history_all;
      else if (url.startsWith("/api/ha/history/")) { const id = url.split("/")[4].split("?")[0]; b = Object.assign({ device_id: id }, url.includes("hours=168") ? data.history_7d[id] : data.history_all.devices[id]); }
      return ok(b);
    };
    win.EventSource = class {
      constructor() { this.l = {}; sources.push(this); setTimeout(() => this.onopen && this.onopen(), 5); }
      addEventListener(n, f) { this.l[n] = f; } close() {}
      emit(n, obj) { if (this.l[n]) this.l[n]({ data: JSON.stringify(obj) }); }
    };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const win = dom.window, doc = win.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const q = (s) => doc.querySelector(s), qa = (s) => Array.from(doc.querySelectorAll(s));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }
const click = async (sel) => { const el = typeof sel === "string" ? q(sel) : sel; if (!el) throw new Error("manca " + sel); el.click(); await wait(30); };
const rows = () => qa("#card-new .nd-row");
const emitNew = (list) => sources[sources.length - 1].emit("new_devices", { type: "new_devices", count: list.length, devices: list });
const routed = (ip) => ({ mac: null, ip, hostname: null, vendor: null, brand: null, network: "iot", first_seen: 100, last_seen: Date.now() / 1000 });

(async () => {
  await wait(800);
  await click("#btn-scan");
  await wait(60);
  emitNew([routed("192.168.60.7")]);
  await wait(60);
  check(!q("#card-new").hidden && rows().length === 1, "the device behind the router is in the card");
  const r = rows()[0];
  check(r.querySelector(".nd-name").textContent === "192.168.60.7" && r.querySelector(".nd-sub").textContent === "", "its address, and no MAC under it");
  check(!/null|undefined/.test(r.textContent), "never «null» or «undefined» for the MAC that is not known");
  const ign = r.querySelector("[data-ign-ip]");
  check(!!ign && ign.dataset.ignIp === "192.168.60.7" && !r.querySelector("[data-ignore-mac]"), "«Ignore» by address, not by MAC");
  emitNew([routed("192.168.60.7"), routed("192.168.60.8")]);
  await wait(60);
  const toasts = qa(".snack .snack-text").map((s) => s.textContent);
  check(toasts.some((s) => s.includes("192.168.60.8")), "the notice of the second one names it: " + toasts.join(" | "));
  check(rows().length === 2, "two rows, one per address");
  await click("#card-new [data-ign-ip='192.168.60.7']");
  await wait(60);
  const posted = calls.filter((c) => c.url === "/api/ignored/hosts");
  check(posted.length === 1 && posted[0].body.hosts[0].ip === "192.168.60.7" && posted[0].body.hosts[0].mac === null, "the ignore is sent by address, with no MAC");
  check(!calls.some((c) => c.url === "/api/new-devices/ignore"), "never the ignore by MAC");
  check(rows().length === 1 && rows()[0].dataset.ip === "192.168.60.8", "the ignored one leaves the card");

  if (errors.length) console.log(errors.join(String.fromCharCode(10)));
  check(errors.length === 0, "nessun errore nella pagina");
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
