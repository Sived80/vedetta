// The export window: who it is for -> which days (the columns, the presets, panning back) -> the steps -> what to decide -> the file.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_export_ui.js [it|en]
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
const calls = [];                                    // what the window asked of the server
// the server of the test: the estimate, and a job whose answers the test decides
const INFO = { daily: Array.from({ length: 90 }, (_, i) => 200000 + (i % 7) * 50000), base: 800000, ratio: 0.3, seal_factor: 1.34, limit: 20 * 1024 * 1024, horizon: 90, flagged: 0 };
let job = null;                                      // the snapshot the server answers while polling
let allSizeBig = false;
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
  beforeParse(win) {
    win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); this.dispatchEvent(new win.Event("close")); };
    win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
    win.URL.createObjectURL = () => "blob:test"; win.URL.revokeObjectURL = () => {};
    win.HTMLAnchorElement.prototype.click = function () { calls.push({ url: "download:" + this.download }); };
    win.HTMLElement.prototype.animate = function () { return { finish() {}, cancel() {}, set onfinish(f) { setTimeout(f, 0); }, set oncancel(f) {} }; };
    win.fetch = (url, opts) => {
      const method = (opts && opts.method) || "GET", body = opts && opts.body ? JSON.parse(opts.body) : null;
      calls.push({ url, method, body });
      const ok = (b, headers) => Promise.resolve({ ok: true, status: 200, headers: { get: (k) => (headers || {})[k] || null }, blob: () => Promise.resolve(new win.Blob(["x"])), json: () => Promise.resolve(b) });
      if (url.startsWith("/api/export/info")) { const i = JSON.parse(JSON.stringify(INFO)); if (allSizeBig) i.daily = i.daily.map((v) => v * 40); return ok(i); }
      if (url === "/api/export/jobs" && method === "POST") return ok(job = Object.assign({ id: "j1", status: "running", steps: ["collect"], items: [], items_total: 0, fixed: 0 }, { dest: body.dest }));
      if (/^\/api\/export\/jobs\/j1\/file/.test(url)) return ok({}, { "Content-Disposition": 'attachment; filename="vedetta-report-ab12cd.txt"' });
      if (/^\/api\/export\/jobs\/j1\/choices/.test(url)) { job = Object.assign({}, job, { status: "running", steps: job.steps.concat(["seal"]) }); return ok(job); }
      if (/^\/api\/export\/jobs\/j1/.test(url) && method === "DELETE") return ok({ ok: true });
      if (/^\/api\/export\/jobs\/j1/.test(url)) return ok(job);
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
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }
const click = async (sel) => { const el = typeof sel === "string" ? q(sel) : sel; if (!el) throw new Error("manca " + sel); el.click(); await wait(20); };
const dlg = () => q("#exportdlg");
const text = () => dlg().textContent;
const openWindow = async () => { await click("#btn-menu"); await click("[data-export]"); await wait(60); };
const reqs = (p) => calls.filter((c) => c.url.startsWith(p));

(async () => {
  await wait(800);
  // --- 1. who it is for
  await openWindow();
  check(dlg().hasAttribute("open"), "la finestra si apre");
  check(qa(".xp-dcard").length === 2, "prima si sceglie per chi: due carte");
  check(qa("[data-xp='dest:dev'], [data-xp='dest:me']").length === 2 && !q(".xp-days"), "e il periodo non e' ancora mostrato");
  check(reqs("/api/export/info").length === 1, "la stima delle dimensioni si chiede una volta, in apertura");

  // --- 2. for the developer: the days
  await click("[data-xp='dest:dev']");
  check(qa(".xp-col").length === 20 && !!q(".xp-days.intro") && !!q(".xp-finger"), "venti colonne e il dito che mostra come toccarle");
  check(qa(".xp-col.in").length === 7, "di partenza: gli ultimi 7 giorni");
  check(!!q(".xp-meter") && /20/.test(q(".xp-meter + .xp-sub").textContent), "per lo sviluppatore c'e' il limite di 20 MB");
  check(qa(".xp-segm button").length === 4 && q("[data-xp='p:7']").getAttribute("aria-pressed") === "true", "tasti 2 / 7 / 20 giorni e Tutto, con il 7 premuto");
  await click("[data-xp='p:20']");
  check(!q(".xp-finger") && !q(".xp-days.intro"), "il dito si vede una volta sola: dal disegno successivo non c'e' piu'");
  check(qa(".xp-col.in").length === 20 && /20/.test(q(".xp-read span").textContent), "20 giorni: tutte le colonne e il riepilogo lo dice");
  const col = (n) => qa(".xp-col")[n];                 // the columns are drawn again after every tap
  await click(col(10));
  check(!!q(".xp-col.pend"), "il primo tocco: la colonna lampeggia finche' non tocchi la seconda");
  await click(col(14));
  check(qa(".xp-col.in").length === 5 && !q(".xp-col.pend"), "due tocchi: cinque giorni selezionati");
  await click(col(0));
  await click(col(19));
  check(qa(".xp-col.in").length === 20 && /20/.test(text()), "oltre 20 giorni la selezione si ferma a 20");
  check(q("[data-xp='newer']").disabled && !q("[data-xp='older']").disabled, "il grafico parte da oggi: 'Dopo' e' spento, 'Prima' no");
  const cap = q(".xp-cap").textContent;
  await click("[data-xp='older']");
  check(q(".xp-cap").textContent !== cap && !q("[data-xp='newer']").disabled, "'Prima' sposta il grafico indietro");
  for (let i = 0; i < 6; i++) await click("[data-xp='older']");
  check(q("[data-xp='older']").disabled && qa(".xp-col.nod").length >= 0, "il grafico non va oltre i 90 giorni");
  await click("[data-xp='p:7']");
  check(q("[data-xp='newer']").disabled, "un tasto dei periodi riporta il grafico a oggi");
  await click("[data-xp='all']");
  check(q("[data-xp='all']").getAttribute("aria-pressed") === "true" && /Tutto|whole/.test(q(".xp-read b").textContent) && !q(".xp-popup, .ovl"), "Tutto: si seleziona e basta, nessun pop-up; poi si preme Esporta");
  await click("[data-xp='p:2']");

  // --- 3. Annulla goes back one step, "for me" has no limit
  await click("[data-xp='cancel']");
  check(qa(".xp-dcard").length === 2 && dlg().hasAttribute("open"), "Annulla nel periodo torna alla scelta per chi, non chiude");
  await click("[data-xp='dest:me']");
  check(!q(".xp-meter") && /chiaro|plain/i.test(q(".xp-chosen").textContent), "per me: in chiaro, nessun limite di dimensione");
  await click("[data-xp='cancel']");
  allSizeBig = true;
  await click("[data-xp='cancel']");                   // closes: the first screen
  check(!dlg().hasAttribute("open"), "Annulla nella prima schermata chiude");
  await openWindow();
  await click("[data-xp='dest:dev']");
  check(q("[data-xp='all']").disabled, "per lo sviluppatore, se tutto lo storico supera il limite 'Tutto' e' spento");
  await click("[data-xp='cancel']");
  await click("[data-xp='dest:me']");
  check(!q("[data-xp='all']").disabled, "per me 'Tutto' e' sempre disponibile");
  allSizeBig = false;

  // --- 4. for me: three steps, the file
  await click("[data-xp='p:7']");
  await click("[data-xp='go']");
  const start = reqs("/api/export/jobs").find((c) => c.method === "POST");
  check(start && start.body.dest === "me" && start.body.from_day === 6 && start.body.to_day === 0, "parte il lavoro con destinazione e giorni (6..0 = ultimi 7)");
  await wait(700);
  check(!!q(".xp-step.run") || !!q(".xp-step.done"), "durante il lavoro si vedono i passi");
  job = Object.assign({}, job, { status: "done", steps: ["collect", "prepare", "ready"], size: 2300000, filename: "vedetta-analisi-x.zip" });
  await wait(700);
  check(qa(".xp-step.done").length === 3 && /non mascherati|not masked/.test(q(".xp-res").textContent), "per me: tre passi fatti, in chiaro e non mascherato");
  await click("[data-xp='save']");
  await wait(60);
  check(reqs("/api/export/jobs/j1/file").length === 1 && calls.some((c) => c.url === "download:vedetta-report-ab12cd.txt"), "'Salva il file' scarica il file una volta");
  check(q("[data-xp='save']").disabled, "dopo il salvataggio il tasto e' spento");
  await click("[data-xp='finish']");
  check(!dlg().hasAttribute("open"), "Chiudi chiude la finestra");

  // --- 5. for the developer: what could not be fixed is decided one by one
  await openWindow();
  await click("[data-xp='dest:dev']");
  await click("[data-xp='go']");
  const items = Array.from({ length: 12 }, (_, i) => ({ id: i, kind: "email address", value: "u" + i + "@example.com", file: "data/settings.json", where: "/mail" }));
  job = Object.assign({}, job, { status: "choose", steps: ["collect", "mask", "check", "fix"], items: items.slice(0, 10), items_total: 12, fixed: 3, dest: "dev" });
  await wait(900);
  check(qa(".xp-fl li").length === 10 && /altri 2|2 more/.test(q(".xp-more").textContent), "al massimo 10 valori, poi 'e altri 2'");
  check(!!q(".xp-tone.bad"), "oltre 10 valori il tono cambia (riquadro rosso)");
  check(!doc.querySelector("[data-xp='bypass']") && !/comunque|anyway/i.test(dlg().textContent), "non c'e' nessun 'Esporta comunque'");
  check(q("[data-xp='apply']").disabled, "'Continua' e' spento finche' non si sceglie");
  await click("[data-xp='rm:0']");
  await click("[data-xp='keep:1']");
  check(q("[data-xp='apply']").disabled, "con due scelte su dieci e' ancora spento");
  await click("[data-xp='rmall']");
  check(!q("[data-xp='apply']").disabled, "'Rimuovi tutti' li decide tutti: 'Continua' si accende");
  await click("[data-xp='keep:2']");
  await click("[data-xp='apply']");
  const dec = reqs("/api/export/jobs/j1/choices")[0];
  check(dec && Object.keys(dec.body.choices).length === 12 && dec.body.choices[2] === "keep" && dec.body.choices[0] === "rm" && dec.body.choices[11] === "rm", "le scelte arrivano al server, anche per i valori non elencati (rimossi)");
  job = Object.assign({}, job, { status: "done", steps: ["collect", "mask", "check", "fix", "seal", "ready"], size: 1500000, filename: "vedetta-report-ab12cd.txt" });
  await wait(900);
  check(/Rimossi 11|Removed 11/.test(text()) && /tenuti|kept/.test(text()), "il risultato dice quanti valori sono stati rimossi e quanti tenuti");
  await click("[data-xp='finish']");

  // --- 6. an error: back to the days
  await openWindow();
  await click("[data-xp='dest:dev']");
  await click("[data-xp='go']");
  job = Object.assign({}, job, { status: "error", steps: ["collect", "mask", "check", "seal"], error: "too_big", items: [], items_total: 0 });
  await wait(900);
  check(!!q(".xp-tone.bad") && /20/.test(text()), "se il file e' troppo grande lo dice, col limite");
  await click("[data-xp='back']");
  check(!!q(".xp-days"), "e si torna a scegliere il periodo");
  await click("[data-xp='cancel']");
  await click("[data-xp='cancel']");
  check(reqs("/api/export/jobs/j1").some((c) => c.method === "DELETE"), "chiudendo la finestra un lavoro non finito viene dimenticato");

  if (errors.length) console.log(errors.join(String.fromCharCode(10)));
  check(errors.length === 0, "nessun errore nella pagina");
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
