// The badge of the deep search: how many devices were never analysed in depth, on the corner of the arrow of the scan button;
// it flies into the "to analyse" tile when the menu opens and comes back when it closes. Needs jsdom (see check_evidence_ui.js).
//   from the vedetta/ folder:  node ../tests/ui/check_deep_badge_ui.js [it|en]
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
let releaseRescan = null;                 // the deep search request stays open until the test lets it finish
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
      calls.push({ url, method: opts && opts.method });
      if (url.startsWith("/api/devices/rescan")) return new Promise((res) => { releaseRescan = () => res({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve({}) }); });
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
const setDevice = async (i, patch) => { sources[sources.length - 1].emit("device", { type: "device", rev: 10 + i + Math.random(), device: Object.assign({}, D[i], patch) }); Object.assign(D[i], patch); await wait(60); };

(async () => {
  await wait(800);

  // --- first start: nothing was ever analysed in depth, so the badge says all of them
  check(qa("#deep-badge").length === 1, "un solo badge nella pagina");
  check(!badge().hidden && badge().textContent === "3", "prima volta: il badge mostra tutti i dispositivi (3)");
  check(badge().parentElement === q(".gauge-side .split") && badge().dataset.at === "corner", "sta sull'angolo della freccia, dentro il pulsante diviso");
  check(badge().getAttribute("aria-label").includes("3") && arrow().getAttribute("aria-label").includes("3"), "lo leggono anche i lettori di schermo");

  // --- it follows the numbers
  await setDevice(0, { scanned_at: Date.now() / 1000 });
  check(badge().textContent === "2", "un dispositivo analizzato: scende a 2");
  await setDevice(1, { deep_empty_at: Date.now() / 1000 });
  check(badge().textContent === "1", "una ricerca andata a vuoto conta come tentata: scende a 1");
  await setDevice(2, { scanned_at: Date.now() / 1000 });
  check(badge().hidden, "tutti analizzati: il badge sparisce");
  await setDevice(0, { scanned_at: null });
  await setDevice(1, { deep_empty_at: null });
  check(!badge().hidden && badge().textContent === "2", "un dispositivo nuovo o da rifare: ricompare (2)");

  // --- the menu: two tiles, one note, and the number only in the badge
  arrow().click();
  await wait(30);
  const menu = q("#deep-menu");
  check(!menu.hidden && qa("#deep-menu .dm-tile").length === 2, "il menu ha due tessere");
  check(!/\d/.test(qa("#deep-menu .dm-tile").map((t) => t.textContent).join(" ")), "il numero non è riscritto nelle tessere (lo porta il badge)");
  const note = q("#deep-menu .dm-foot").textContent;
  check(note.includes("03:00") && (note.match(/03:00/g) || []).length === 1, "la spiegazione con l'ora c'è una volta sola");
  check(!menu.textContent.includes(IT ? "Ricerca approfondita…" : "Deep search…"), "niente più titoli ripetuti");
  check(badge().parentElement === doc.body && badge().dataset.at === "fly", "in volo il badge sta fuori da tutto (nel body), così nulla lo nasconde");
  check(flights.length === 1 && flights[0].el === badge(), "una sola animazione, sul badge stesso (non su una copia)");
  check(qa("#deep-badge").length === 1, "durante il volo c'è ancora un solo badge");
  flights[0].finish();
  check(badge().parentElement.classList.contains("dm-slot") && badge().dataset.at === "slot" && !badge().style.left, "atterra nella tessera 'da analizzare' e torna ai suoi stili");
  check(qa("#deep-badge").length === 1, "un solo badge anche dentro il menu");

  // --- closing: it goes back to the arrow, also when the user is quick
  arrow().click();
  await wait(30);
  check(q("#deep-menu").hidden && badge().dataset.at === "fly", "chiudendo, il badge parte verso la freccia");
  flights[flights.length - 1].finish();
  check(badge().parentElement === q(".gauge-side .split") && badge().dataset.at === "corner", "torna sull'angolo della freccia");
  const before = flights.length;
  arrow().click();                                  // open ...
  await wait(10);
  arrow().click();                                  // ... and close at once, before the first flight ends
  await wait(30);
  flights.forEach((f) => f.finish());               // the old flights end late: they must not drag it back
  await wait(30);
  check(flights.length >= before + 2 && badge().parentElement === q(".gauge-side .split") && badge().dataset.at === "corner" && qa("#deep-badge").length === 1,
    "aprire e chiudere di colpo: finisce sull'angolo, un solo badge, i voli vecchi non lo spostano");

  // --- the badge opens the menu too
  badge().click();
  await wait(30);
  check(!q("#deep-menu").hidden, "premere il badge apre il menu");
  flights.forEach((f) => f.finish());
  // pressing outside closes it and the badge returns
  doc.body.click();
  await wait(30);
  flights.forEach((f) => f.finish());
  check(q("#deep-menu").hidden && badge().dataset.at === "corner", "premere fuori chiude e il badge torna");

  // --- everything analysed: the tile is off and the badge is gone
  await setDevice(0, { scanned_at: Date.now() / 1000 });
  await setDevice(1, { scanned_at: Date.now() / 1000 });
  arrow().click();
  await wait(30);
  const pending = q('#deep-menu [data-deep="pending"]');
  check(badge().hidden && pending.disabled && pending.textContent.includes(IT ? "tutti analizzati" : "all analysed"), "a zero: niente badge e la tessera è spenta");
  check(qa("#deep-badge").length === 1, "anche a zero un solo elemento badge");
  arrow().click();
  await wait(30);
  flights.forEach((f) => f.finish());

  // --- no animations available (or reduced motion): it simply changes place
  win.HTMLElement.prototype.animate = undefined;
  await setDevice(0, { scanned_at: null });
  arrow().click();
  await wait(30);
  check(badge().parentElement.classList.contains("dm-slot") && badge().dataset.at === "slot", "senza animazioni si sposta e basta, nella tessera");
  arrow().click();
  await wait(30);
  check(badge().parentElement === q(".gauge-side .split"), "e torna sull'angolo");

  // --- a choice in the menu starts the search at once (no confirmation) and, while it runs, no other can start
  win.HTMLElement.prototype.animate = function () { return { finish() {}, cancel() {}, set onfinish(f) { setTimeout(f, 0); }, set oncancel(f) {} }; };
  await setDevice(0, { scanned_at: null });
  arrow().click();
  await wait(30);
  q('#deep-menu [data-deep="all"]').click();
  await wait(30);
  check(!doc.querySelector("dialog[open]"), "dopo la scelta nel menu non compare nessun pop-up di conferma");
  check(calls.filter((c) => c.url.startsWith("/api/devices/rescan")).length === 1, "la ricerca parte subito");
  check(arrow().disabled && arrow().title.length > 0, "mentre la ricerca va, la freccia e' spenta e dice perche'");
  arrow().click();
  await wait(30);
  check(q("#deep-menu").hidden, "con la ricerca in corso il menu non si apre");
  badge().click();
  await wait(30);
  check(q("#deep-menu").hidden, "ne' dal badge");
  check(!q("#btn-scan").disabled, "Scansiona la rete e' indipendente: resta disponibile");
  sources[sources.length - 1].emit("activity", { type: "activity", rescanning: [D[0].id], search: false });
  releaseRescan && releaseRescan();
  await wait(60);
  check(arrow().disabled, "lo dice anche il server (rescanning): resta spenta anche dopo che la richiesta e' finita");
  sources[sources.length - 1].emit("activity", { type: "activity", rescanning: [], search: false });
  await wait(60);
  check(!arrow().disabled, "a ricerca finita la freccia torna attiva");
  arrow().click();
  await wait(30);
  check(!q("#deep-menu").hidden, "e il menu si apre di nuovo");
  arrow().click();
  await wait(30);

  if (errors.length) console.log(errors.join(String.fromCharCode(10)));
  check(errors.length === 0, "nessun errore nella pagina");
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
