// The rotating tile of the Network card: the latency of the gateway from the history of the last hour (tenths of a millisecond, not the whole-millisecond value of the card) and the Internet tile.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_tiles_ui.js [it|en]
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
data.devices.devices[0].ha_share = true; data.devices.devices[1].ha_share = true;      // two of the three devices are shared with Home Assistant
gwDev.latency_ms = 1;                                  // what the card says: whole milliseconds, "1" for a LAN
data.summary.roles = Object.assign({}, data.summary.roles, { by_ip: { [gwDev.ip]: { gateway: "arp" } },
  internet: { public_ip: "203.0.113.7", hops: ["192.0.2.1", "198.51.100.1", "203.0.113.1"], private_hops: ["192.0.2.1"], double_nat: false, cgnat: false, ts: Date.now() / 1000 - 90 } });

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
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }
const click = async (sel) => { const el = typeof sel === "string" ? q(sel) : sel; if (!el) throw new Error("manca " + sel); el.click(); await wait(30); };
const rows = () => qa("#card-new .nd-row");
const label = (c) => (c.getAttribute("aria-label") || c.textContent).trim();
const cells = (i) => Array.from(rows()[i].querySelectorAll(".nd-actions > *")).map((c) => label(c));
const bar = () => Array.from(qa("#card-new .nd-bar-actions > *")).map((c) => label(c) + (c.disabled ? "(spento)" : ""));
const title = () => q("#card-new .ch-title").textContent.trim();
const rowState = (i) => Array.from(rows()[i].classList).filter((c) => /^nd-(idle|run|save|done)$/.test(c))[0];




(async () => {
  await wait(1500);
  // Each click shows the next tile (the fade of the swap takes ~160 ms): collect what each one says.
  const seen = {};
  for (let i = 0; i < 7; i++) {
    const label = (q("#rot .t-l") || { textContent: "" }).textContent.trim();
    if (label && !seen[label]) seen[label] = q("#rot .t-body").textContent.replace(/\s+/g, " ").trim();
    q("#rot").click();
    await wait(350);
  }
  const labels = Object.keys(seen);
  check(labels.length >= 4, "la tile gira tra almeno quattro schede: " + labels.join(", "));
  const internet = seen.Internet;
  check(!!internet && internet.includes("203.0.113.7") && /Connessione diretta|Direct connection/.test(internet) && /Online/.test(internet) && /Salti: 3|Hops: 3/.test(internet) && /controllato|checked/.test(internet), "tile «Internet»: IP pubblico, tipo di connessione, stato, salti e quando e' stato controllato");
  const lat = seen[labels.find((l) => /Latenza|Latency/i.test(l))];
  check(histCalls >= 1 && !!lat && lat.includes("0.5") && lat.includes("0.4") && lat.includes("0.6") && !lat.includes("1.0"), "tile della latenza: i numeri vengono dalla storia dell'ultima ora (0.4 - 0.6 ms), non piu' sempre «1.0 ms»");
  // The MQTT tile: "exposed" counts the devices shared with Home Assistant, and only while the broker is connected.
  const visit = async (label) => {
    for (let i = 0; i < 7; i++) {
      if ((q("#rot .t-l") || { textContent: "" }).textContent.trim() === label) return q("#rot .t-body");
      q("#rot").click();
      await wait(350);
    }
    return null;
  };
  const link = (active, connected) => sources[sources.length - 1].emit("mqtt", { type: "mqtt", active, connected });
  const mqText = () => q("#rot .t-body").textContent.replace(/\s+/g, " ");
  let mq = await visit("MQTT");
  check(!!mq && /Non configurato|Not set up/.test(mqText()) && /(Esposte|Exposed) MQTT\s*–/.test(mqText()) && /width:\s*0%/.test(mq.innerHTML), "MQTT non configurato: «Non configurato» (non un guasto) e «Esposte MQTT –», barra vuota");
  link(true, false);
  await wait(300);
  check(/Offline/.test(mqText()) && !/Non configurato|Not set up/.test(mqText()) && /(Esposte|Exposed) MQTT\s*–/.test(mqText()), "configurato ma il broker non risponde, avvisato in tempo reale dal server: «Offline»");
  link(true, true);
  await wait(300);
  check(/Online/.test(mqText()) && /(Esposte|Exposed) MQTT\s*2(?!\d)/.test(mqText()) && /width:\s*66\.7%/.test(q("#rot .t-body").innerHTML), "broker connesso: «Online», «Esposte MQTT 2» (i due condivisi su tre) e barra al 66,7%");
  link(true, false);
  await wait(300);
  check(/Offline/.test(mqText()) && /(Esposte|Exposed) MQTT\s*–/.test(mqText()), "il broker cade: la tile segue senza ricaricare la pagina");
  check(errors.length === 0, "nessun errore nella pagina" + (errors.length ? ": " + errors[0] : ""));
  console.log(failed ? "FALLITI: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
