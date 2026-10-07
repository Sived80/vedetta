// The card of the devices found: add one, cancel one, "Add all", cancel the batch, the tick when a device is saved, "Close".
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_new_devices_ui.js [it|en]
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
const calls = [];
const HOSTS = [["192.168.178.201", "B8:27:EB:3A:91:C2"], ["192.168.178.202", "3C:61:05:4F:20:7D"], ["192.168.178.203", "F0:18:98:5A:11:09"]].map(([ip, mac]) => ({ ip, mac, hostname: "h" + ip.split(".")[3] }));
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
const cells = (i) => Array.from(rows()[i].querySelectorAll(".nd-actions > *")).map((c) => c.textContent.trim());
const bar = () => Array.from(qa("#card-new .nd-bar-actions > *")).map((c) => c.textContent.trim() + (c.disabled ? "(spento)" : ""));
const title = () => q("#card-new .ch-title").textContent.trim();
const rowState = (i) => Array.from(rows()[i].classList).filter((c) => /^nd-(idle|run|save|done)$/.test(c))[0];

(async () => {
  await wait(800);
  await click("#btn-scan");
  await wait(120);
  // --- 1. the list
  check(rows().length === 3 && !q("#card-new").hidden, "la scheda mostra i tre dispositivi trovati");
  check(rows().every((_, i) => rowState(i) === "nd-idle" && cells(i).length === 2 && /Aggiungi|Add/.test(cells(i)[0])), "a riposo ogni riga ha due caselle: Aggiungi e Ignora");
  check(bar().length === 2 && /tutti|all/i.test(bar()[0]) && !!q("#card-new [data-ignore-all]"), "la barra ha «Aggiungi tutti» e «Annulla»");
  check(!!q("#card-new .nd-prog.idle"), "la barra di avanzamento c'e' gia', invisibile");

  // --- 2. add one, cancel it
  await click("#card-new [data-add-ip='192.168.178.201']");
  check(rowState(0) === "nd-run" && /Annulla|Cancel/.test(cells(0)[0]) && /In corso|In progress/.test(cells(0)[1]), "«Aggiungi» su una riga: «Annulla» al suo posto e «Ignora» diventa «In corso»");
  check(!!rows()[0].querySelector(".nd-ring .sp"), "nell'icona un anello gira");
  check(bar().length === 2 && bar()[1] === "" && !q("#card-new [data-ignore-all]"), "l'«Annulla» in alto e' sparito");
  check(streams.length === 1 && streams[0].ips.join() === "192.168.178.201", "parte la ricerca di quel solo dispositivo");
  await click("#card-new [data-add-cancel='192.168.178.201']");
  await wait(60);
  check(rowState(0) === "nd-idle" && /Aggiungi|Add/.test(cells(0)[0]), "«Annulla» sulla riga: il dispositivo torna com'era");
  check(streams[0].aborted() && calls.some((c) => c.url === "/api/scan/cancel" && c.body.ips[0] === "192.168.178.201"), "la ricerca e' fermata (anche sul server)");
  check(!calls.some((c) => c.url === "/api/devices/add"), "e non viene aggiunto niente");
  check(!!q("#card-new [data-ignore-all]") && !/Aggiunta|Adding/.test(title()), "la scheda e' tornata a riposo");

  // --- 3. add one, then "Add all": the cancel of the row goes away, the one in the bar is the only one
  await click("#card-new [data-add-ip='192.168.178.201']");
  await click("#card-new [data-add-all]");
  check(streams.length === 3 && streams[2].ips.join() === "192.168.178.202,192.168.178.203", "«Aggiungi tutti» cerca gli altri due");
  check(cells(0)[0] === "" && /In corso|In progress/.test(cells(0)[1]), "l'«Annulla» della riga sparisce");
  check(bar()[0].indexOf("(spento)") > 0 && /Annulla|Cancel/.test(bar()[1]) && !!q("#card-new [data-add-cancel-all]"), "in alto «Aggiungi tutti» e' in corso e accanto c'e' «Annulla»");
  check(!qa("#card-new [data-add-cancel]").length, "nessuna riga ha piu' un suo «Annulla»");
  check(/0 di 3|0 of 3/.test(title()), "il titolo dice quanti sono: 0 di 3");

  // --- 4. the first one is analysed, then the whole batch is cancelled
  streams[1].progress("192.168.178.201");
  await wait(60);
  check(rowState(0) === "nd-save" && !!rows()[0].querySelector(".nd-ring .close"), "analizzato: l'anello si chiude (sta salvando)");
  await click("#card-new [data-add-cancel-all]");
  await wait(120);
  check(rowState(1) === "nd-idle" && rowState(2) === "nd-idle", "«Annulla» in alto: gli altri due tornano in lista");
  check(streams[2].aborted(), "e la loro ricerca e' fermata");
  const adds = calls.filter((c) => c.url === "/api/devices/add");
  check(adds.length === 1 && adds[0].body.devices.length === 1 && adds[0].body.devices[0].ip === "192.168.178.201", "solo quello gia' analizzato viene aggiunto");
  check(rowState(0) === "nd-done" && !!rows()[0].querySelector(".nd-ring .tick") && cells(0).every((c) => c === ""), "e la sua riga diventa verde con la spunta, senza scritte");
  check(/Chiudi|Close/.test(bar()[1]) && /^1 /.test(title()) && /aggiunt|added/.test(title()), "in alto «Annulla» e' diventato «Chiudi» e il titolo dice «1 dispositivo aggiunto»");
  check(!!q("#card-new .nd-prog.ok"), "la barra di avanzamento e' piena e verde");

  // --- 5. Close closes the card (the devices added are in the list; a new scan finds the others again)
  await click("#card-new [data-add-close]");
  check(q("#card-new").hidden, "«Chiudi» chiude la scheda, senza far comparire «Annulla»");

  // --- 6. a new scan, Add all, everything works
  await click("#btn-scan");
  await wait(120);
  check(rows().length === 3, "una nuova ricerca ripropone i dispositivi");
  await click("#card-new [data-add-all]");
  const s = streams[streams.length - 1];
  HOSTS.forEach((h) => s.progress(h.ip)); s.push({ type: "complete", results: HOSTS.map((h) => ({ ip: h.ip, adapter: "generic" })) }); s.end();
  await wait(200);
  check(rows().length === 3 && rows().every((_, i) => rowState(i) === "nd-done"), "tutti aggiunti: tre righe verdi");
  check(/^3 /.test(title()) && /Chiudi|Close/.test(bar()[1]), "titolo «3 dispositivi aggiunti» e «Chiudi» in alto");
  await click("#card-new [data-add-close]");
  check(q("#card-new").hidden, "«Chiudi»: finito tutto la scheda sparisce");

  // --- 7. devices seen on the network by the app (not chosen from a search): "Cancel" closes the card until something new appears
  const seen = (mac, ip) => ({ mac, ip, hostname: "n" + ip.split(".")[3] });
  const emitNew = (list) => sources[sources.length - 1].emit("new_devices", { type: "new_devices", count: list.length, devices: list });
  HOSTS.length = 0;                                  // the next scans find nothing: only what the app saw by itself
  const A = seen("AA:AA:AA:00:00:01", "192.168.178.211"), B = seen("AA:AA:AA:00:00:02", "192.168.178.212");
  await click("#btn-scan");
  await wait(60);
  emitNew([A, B]);
  await wait(60);
  check(!q("#card-new").hidden && rows().length === 2, "due dispositivi visti in rete dall'app: la scheda compare");
  await click("#card-new [data-ignore-all]");
  check(q("#card-new").hidden, "«Annulla» chiude la scheda");
  await click("#btn-scan");                          // (a completed scan is what lets the devices seen on the network show)
  await wait(60);
  emitNew([A, B]);
  await wait(60);
  check(q("#card-new").hidden, "e non ricompare per gli stessi dispositivi, nemmeno dopo una nuova ricerca");
  const C = seen("AA:AA:AA:00:00:03", "192.168.178.213");
  emitNew([A, B, C]);
  await wait(60);
  check(!q("#card-new").hidden && rows().length === 1, "ricompare solo per un dispositivo mai visto prima");

  // --- 8. a device the card itself brought: once saved, the card goes away by itself (after the tick)
  await click("#card-new [data-add-ip='192.168.178.213']");
  const s2 = streams[streams.length - 1];
  s2.progress("192.168.178.213"); s2.push({ type: "complete", results: [{ ip: "192.168.178.213", adapter: "generic" }] }); s2.end();
  await wait(300);
  check(rowState(0) === "nd-done", "salvato: la riga e' verde");
  await wait(2600);
  check(q("#card-new").hidden, "e dopo la spunta la scheda sparisce da sola");

  if (errors.length) console.log(errors.join(String.fromCharCode(10)));
  check(errors.length === 0, "nessun errore nella pagina");
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
