// The deep search of single devices from their sheet: pressing it on a SECOND device while the first is still being searched must start the second too (the server queues the nmap runs),
// not be dropped in silence. Found on a real debug app: of 4 devices only the first was searched, and the log showed the other three requests never reached the server.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_deep_one_ui.js [it|en]
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
const IT = lang === "it";
const out = fs.mkdtempSync(path.join(os.tmpdir(), "vedetta-ui-"));
const built = spawnSync(process.env.PYTHON || "python", [path.join(__dirname, "build_page.py"), out, lang], { cwd: path.join(__dirname, "..", "..", "vedetta"), encoding: "utf8" });
if (built.status !== 0) { console.log("build_page.py failed:\n" + built.stdout + built.stderr); process.exit(1); }
const html = fs.readFileSync(path.join(out, "page.html"), "utf8");
const data = JSON.parse(fs.readFileSync(path.join(out, "data.json"), "utf8"));
const D = data.devices.devices;
// first start: no device was ever analysed in depth
D.forEach((d) => { d.scanned_at = null; d.deep_empty_at = null; });

const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
vc.on("error", (e) => errors.push("console.error: " + e));
const sources = [];
const calls = [];                         // the requests the page made
let releaseRescan = null;
const releasers = [];                       // one per request still open                 // the deep search request stays open until the test lets it finish
const flights = [];                       // the animations the page asked for (jsdom has none: they are driven by hand)
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
  beforeParse(win) {
    win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); this.dispatchEvent(new win.Event("close")); };
    win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
    // jsdom has no layout: every element has a size, the badge starts in a different place from where it lands
    win.HTMLElement.prototype.getBoundingClientRect = function () {
      const left = this.id === "deep-badge" && this.dataset.at === "slot" ? 300 : 100, top = this.id === "deep-badge" && this.dataset.at === "slot" ? 200 : 50;
      return { left, top, right: left + 20, bottom: top + 20, width: 20, height: 20, x: left, y: top };
    };
    win.HTMLElement.prototype.animate = function (frames, opts) {
      const a = { frames, opts, el: this, onfinish: null, oncancel: null, done: false,
        finish() { if (!this.done) { this.done = true; this.onfinish && this.onfinish(); } }, cancel() { if (!this.done) { this.done = true; setTimeout(() => this.oncancel && this.oncancel(), 0); } } };
      flights.push(a);
      return a;
    };
    win.fetch = (url, opts) => {
      calls.push({ url, method: opts && opts.method, body: opts && opts.body });
      if (url.startsWith("/api/devices/rescan")) return new Promise((res) => { releasers.push(() => res({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({}) })); releaseRescan = () => res({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({}) }); });
      let body = {};
      if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) body = data.devices;
      else if (url.startsWith("/api/ha/summary")) body = data.summary;
      else if (url.startsWith("/api/ha/logbook")) body = data.logbook;
      else if (url.startsWith("/api/ha/history?")) body = data.history_all;
      else if (url.startsWith("/api/ha/history/")) { const id = url.split("/")[4].split("?")[0]; body = Object.assign({ device_id: id }, url.includes("hours=168") ? data.history_7d[id] : data.history_all.devices[id]); }
      return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(body) });
    };
    win.EventSource = class {
      constructor(url) { this.url = url; this.l = {}; sources.push(this); setTimeout(() => this.onopen && this.onopen(), 5); }
      addEventListener(n, f) { this.l[n] = f; } close() {}
      emit(n, obj) { this.l[n]({ data: JSON.stringify(obj) }); }
    };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const win = dom.window, doc = win.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const q = (s) => doc.querySelector(s), qa = (s) => Array.from(doc.querySelectorAll(s));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }
const badge = () => q("#deep-badge");
const arrow = () => q("#btn-deepmenu");

const rescans = () => calls.filter((c) => c.url.startsWith("/api/devices/rescan"));
const sent = () => rescans().map((c) => JSON.parse(c.body).ids.join(","));
const openSheet = async (id) => { q('.tile[data-id="' + id + '"]').click(); await wait(60); };
const pressDeep = async () => { const b = doc.querySelector('dialog[open] [data-act="deep"]'); if (!b) return false; b.click(); await wait(40); return true; };
const emit = (rescanning) => sources[sources.length - 1].emit("activity", { type: "activity", rescanning, search: false });

(async () => {
  await wait(800);
  win.localStorage.setItem("vedetta-ha-skip-deep", "1");      // no confirmation window: the press starts the search
  const [a, b, c] = D.map((d) => d.id);

  // --- the first device: the request goes out, the card is marked by the server's activity event
  await openSheet(a);
  check(await pressDeep(), "il pulsante della ricerca c'e' nella scheda del primo dispositivo");
  check(sent().length === 1 && sent()[0] === a, "prima ricerca: parte la richiesta del primo dispositivo");
  emit([a]);
  await wait(30);

  // --- a SECOND device while the first is still open: it must go out too (it used to be dropped without a word)
  await openSheet(b);
  check(await pressDeep(), "il pulsante c'e' anche sulla scheda del secondo dispositivo");
  check(sent().length === 2 && sent()[1] === b, "seconda ricerca mentre la prima gira: parte anche la sua richiesta (non scartata)");
  emit([a, b]);
  await wait(30);
  check(q('.tile[data-id="' + a + '"]').classList.contains("scanning") && q('.tile[data-id="' + b + '"]').classList.contains("scanning"), "le due schede girano insieme");

  // --- the same device again while it is being searched: no second request, and the page says why
  await openSheet(a);
  const again = doc.querySelector('dialog[open] [data-act="deep"]');
  check(!again || again.disabled, "su un dispositivo gia' in ricerca il pulsante e' spento");
  if (again && !again.disabled) await pressDeep();
  check(sent().length === 2, "nessuna richiesta doppia per lo stesso dispositivo");
  doc.querySelector("dialog[open] .sheet-close, dialog[open] [data-act=close], dialog[open] .close") ? doc.querySelector("dialog[open] .sheet-close, dialog[open] [data-act=close], dialog[open] .close").click() : doc.querySelector("dialog[open]") && doc.querySelector("dialog[open]").close();

  // --- a third one too, and the top arrow stays free while only single-device searches run (as before)
  await openSheet(c);
  await pressDeep();
  check(sent().length === 3 && sent()[2] === c, "terza ricerca: parte anche questa");
  check(arrow().disabled, "finche' le richieste sono aperte la freccia in alto aspetta (ricerca su tutti = una sola alla volta)");

  // --- the requests end one by one: the page frees each, nothing stays stuck
  releasers.forEach((r) => r());
  emit([]);
  await wait(80);
  check(!q('.tile[data-id="' + a + '"]').classList.contains("scanning"), "a ricerche finite le schede non girano piu'");
  check(!arrow().disabled, "a ricerche finite la freccia in alto torna attiva");
  await openSheet(a);
  await pressDeep();
  check(sent().length === 4 && sent()[3] === a, "a ricerca finita lo stesso dispositivo si puo' cercare di nuovo");

  check(errors.length === 0, "nessun errore nella pagina: " + errors.join(" | ").slice(0, 200));
  console.log(failed ? "FALLITI: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
