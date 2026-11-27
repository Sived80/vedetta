// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The tiles of the networks (1.0.1): one tile per network, every tile with the same places (icon, name, two boxes, legend and bar or a
// button), only data the page already reads (GET /api/networks, the device list, the gateway's card), the list of the networks read at
// most once a minute, and one tile that fails does not stop the others. Needs jsdom.   from the vedetta/ folder:  node ../tests/ui/check_net_tiles_ui.js [it|en]
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
const gwDev = data.devices.devices[0];
data.summary.external = { public_ip: { on: true }, path: { on: true, target: "1.1.1.1" }, mac_database: { on: false, updated: null } };      // the options of the add-on: two of the three functions on
data.devices.devices[0].ha_share = true; data.devices.devices[1].ha_share = true;      // two of the three devices are shared with Home Assistant
gwDev.latency_ms = 1;                                  // what the card says: whole milliseconds, "1" for a LAN
data.summary.roles = Object.assign({}, data.summary.roles, { by_ip: { [gwDev.ip]: { gateway: "arp" } },
  internet: { public_ip: "203.0.113.7", hops: ["192.0.2.1", "198.51.100.1", "203.0.113.1"], private_hops: ["192.0.2.1"], double_nat: false, cgnat: false, ts: Date.now() / 1000 - 90 } });


const IT = lang === "it";
let netCalls = 0, netBody = null;
const NETS = { main: { id: "main", cidr: "10.80.0.0/22", via: ["direct"], touch: "full", state: "confirmed", cards: 3, fits: true, name: "Casa", vlan: null, on: 2, mute: false, caps: {} },
  networks: [
    { id: "iot", cidr: "10.81.0.0/24", via: ["routed"], touch: "ports", state: "confirmed", cards: 4, fits: true, name: "IoT", vlan: 20, on: 0, mute: true, caps: {} },
    { id: "p7", cidr: "10.87.7.0/24", via: ["routed"], touch: "presence", state: "proposed", cards: 2, fits: true, name: null, vlan: null, on: 2, mute: false, caps: {} },
    { id: "lab", cidr: "10.85.0.0/24", via: ["routed"], touch: "presence", state: "paused", cards: 1, fits: true, name: "Lab", vlan: 50, on: 1, mute: false, caps: {} },
    { id: "bad", state: "confirmed", fits: true },
  ], left_out: [], limits: {} };
let histCalls = 0;
const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
vc.on("error", (e) => errors.push("console.error: " + e));
const calls = [];
const HOSTS = [["192.0.2.201", "B8:27:EB:3A:91:C2"], ["192.0.2.202", "3C:61:05:4F:20:7D"], ["192.0.2.203", "F0:18:98:5A:11:09"]].map(([ip, mac]) => ({ ip, mac, hostname: "h" + ip.split(".")[3] }));
const sources = [];
const streams = [];                                   // the deep searches started: the test says what each one has found, and when it ends
function makeStream(ips, signal) {
  const q = [], waiters = []; let closed = false, aborted = false;
  const enc = new (require("util").TextEncoder)();
  const s = { ips, push(obj) { const v = enc.encode("data: " + JSON.stringify(obj) + "\n"); const w = waiters.shift(); if (w) w.resolve({ done: false, value: v }); else q.push(v); },
    progress(ip) { s.push({ type: "progress", result: { ip, suggested_name: "Dev " + ip, adapter: "generic" } }); }, end() { closed = true; waiters.splice(0).forEach((w) => w.resolve({ done: true })); }, aborted: () => aborted };
  if (signal) signal.addEventListener("abort", () => { aborted = true; waiters.splice(0).forEach((w) => w.reject(new Error("aborted"))); });
  s.reader = { read() { if (aborted) return Promise.reject(new Error("aborted")); if (q.length) return Promise.resolve({ done: false, value: q.shift() }); if (closed) return Promise.resolve({ done: true }); return new Promise((resolve, reject) => waiters.push({ resolve, reject })); } };
  return s;
}
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
  beforeParse(win) {
    win.addEventListener("unhandledrejection", (ev) => errors.push("rejection: " + (ev.reason && ev.reason.stack || ev.reason)));
    win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
    win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
    win.HTMLElement.prototype.scrollIntoView = function () {};
    win.TextDecoder = require("util").TextDecoder;
    win.fetch = (url, opts) => {
      const method = (opts && opts.method) || "GET", body = opts && opts.body ? JSON.parse(opts.body) : null;
      calls.push({ url, method, body });
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      if (url.startsWith("/api/networks") && method === "GET" && !url.includes("/purge")) { netCalls++; return ok(netBody || NETS); }
      if (url === "/api/scan/quick") return ok(HOSTS);
      if (url === "/api/scan/deep") { const s = makeStream(body.ips, opts.signal); streams.push(s); return Promise.resolve({ ok: true, status: 200, body: { getReader: () => s.reader } }); }
      if (url === "/api/devices/add") return ok({ ok: true });
      if (url.startsWith("/api/new-devices")) return ok([]);
      if (url === "/api/scan/cancel") return ok({ ok: true });
      let b = {};
      if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
      else if (url.startsWith("/api/ha/summary")) b = data.summary;
      else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
      else if (url.startsWith("/api/ha/history?")) b = data.history_all;
      else if (url.startsWith("/api/ha/history/") && url.includes("hours=1") && !url.includes("hours=168")) { histCalls++; b = { device_id: gwDev.id, latency: { from: 0, to: 1, points: [[1, 0.4], [2, 0.6], [3, 0.5]], avg: 0.5, max: 0.6 } }; }
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
const label = (c) => (c.getAttribute("aria-label") || c.textContent).trim();
const cells = (i) => Array.from(rows()[i].querySelectorAll(".nd-actions > *")).map((c) => label(c));
const bar = () => Array.from(qa("#card-new .nd-bar-actions > *")).map((c) => label(c) + (c.disabled ? "(spento)" : ""));
const title = () => q("#card-new .ch-title").textContent.trim();
const rowState = (i) => Array.from(rows()[i].classList).filter((c) => /^nd-(idle|run|save|done)$/.test(c))[0];




(async () => {
  await wait(1500);
  const tiles = {};
  for (let i = 0; i < 12; i++) {
    const card = q("#rot .t-card");
    const name = card && card.querySelector(".t-name") ? card.querySelector(".t-name").textContent.trim() : (q("#rot .t-l") || { textContent: "?" }).textContent.trim();
    if (card && !tiles[name]) tiles[name] = { text: card.textContent.replace(/\s+/g, " ").trim(), card: card.cloneNode(true) };
    q("#rot").click();
    await wait(350);
  }
  const names = Object.keys(tiles);
  check(["Casa", "IoT", "10.87.7.0/24", "Lab"].every((n) => names.includes(n)), "una tile per ogni rete (principale, VLAN, proposta, in pausa): " + names.join(", "));
  check(!names.some((n) => /^(Latenza|Latency|Gateway)$/.test(n)), "niente piu' tile separate di latenza e gateway: stanno nella tile della rete principale");
  const same = names.every((n) => { const c = tiles[n].card; return c.querySelectorAll(".t-head .t-ic").length === 1 && c.querySelectorAll(".t-name").length === 1 && c.querySelectorAll(".t-mid .stat-box").length === 2 && c.querySelectorAll(".t-foot").length === 1; });
  check(same, "ogni tile ha gli stessi posti: icona, nome, due riquadri, piede");
  const main = tiles["Casa"] ? tiles["Casa"].text : "";
  check(/2 \/ 3/.test(main), "rete principale: accese su schede dai dati di /api/networks (2 / 3): " + main);
  check(/Gateway/.test(main) && /1\.0\s*ms/.test(main), "rete principale: la latenza del gateway, dalla sua scheda: " + main);
  check(main.includes("10.80.0.0/22") && /1 (spenta|off)/.test(main), "legenda: la sottorete vera letta dal server, anche una /22 (Discussion #15), e le spente: " + main);
  const iot = tiles["IoT"] ? tiles["IoT"].text : "";
  check(/Muta|Silent/.test(iot) && /VLAN\s*20/.test(iot), "rete muta: lo dice, con la sua VLAN: " + iot);
  const prop = tiles["10.87.7.0/24"];
  check(!!prop && /Proposta|Proposed/.test(prop.text) && !!prop.card.querySelector(".t-foot [data-open]") && !prop.card.querySelector(".t-foot .pbar"), "rete proposta: niente barra, il tasto per le Reti");
  const lab = tiles["Lab"];
  check(!!lab && /In pausa|Paused/.test(lab.text) && !!lab.card.querySelector(".t-foot [data-open]"), "rete in pausa: il tasto per le Reti");
  check(netCalls >= 1 && netCalls <= 2, "l'elenco delle reti letto al massimo una volta al minuto, non a ogni giro: " + netCalls + " richieste");
  for (let i = 0; i < 12 && !(q("#rot .t-name") && q("#rot .t-name").textContent.trim() === "Lab"); i++) { q("#rot").click(); await wait(350); }
  const before = calls.length;
  const go = q("#rot .t-foot [data-open]");
  if (go) { go.click(); await wait(200); }
  check(!!go && calls.slice(before).some((c) => c.url.startsWith("/api/networks") || c.url.startsWith("/api/ignored")), "il tasto apre il pannello Reti");
  check(errors.length === 0, "una rete con dati mancanti non rompe le altre tile, nessun errore nella pagina" + (errors.length ? ": " + errors[0] : ""));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
