// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The memory on the page: in a card, «Last 30 days» (the strip of 30 days, the class, one line on the link, the changes of name and brand
// closed and opened with a tap); in the menu, «Download the list» (CSV or JSON, «Hide MAC and IP» on by default, the file asked with
// those choices); the card «Last 12 hours» only when there is something to say, hidden by its X until something else happens.
// Needs jsdom (see check_evidence_ui.js).  from the vedetta/ folder:  node ../tests/ui/check_memory_ui.js [it|en]
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
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }

const REC = { class: "stable", active_days: 9, history_days: 10, strip: Array.from({ length: 30 }, (_, i) => i >= 21) };
const QUAL = { samples: 500, median_ms: 12.4, level: "high", trend: "rising", changes_24h: 3, longest_outage_s: 7200 };
const IDS = { changes: [{ ts: 1700000000, field: "name", old: "android-7f3a", new: "Pixel", source: "auto" }, { ts: 1699990000, field: "brand", old: null, new: "Google", source: "mdns" }] };
const DIGEST = { first_window: false, new: ["d2"], back: [{ id: "d1", at: 1700000000, away_s: 40 * 86400 }], silent: [], labels: { d1: "NAS", d2: "Pixel" }, cards: 3, online: 2 };

function open(digest, storage) {
  const errors = [], asked = [], saved = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
  vc.on("error", (e) => errors.push("console.error: " + e));
  const dom = new JSDOM(html, {
    runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
    beforeParse(win) {
      win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
      win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
      win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
      win.HTMLElement.prototype.scrollIntoView = function () {};
      win.URL.createObjectURL = () => "blob:x"; win.URL.revokeObjectURL = () => {};
      win.HTMLAnchorElement.prototype.click = function () { saved.push(this.download); };     // jsdom cannot download: the click is recorded
      if (storage) for (const k in storage) win.localStorage.setItem(k, storage[k]);
      win.fetch = (url) => {
        asked.push(url);
        const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: (h) => (/disposition/i.test(h) ? 'attachment; filename="vedetta-inventory-x.csv"' : null) },
          blob: () => Promise.resolve(new win.Blob(["a,b"])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
        let b = {};
        if (url.startsWith("/api/ha/recurrence/")) b = REC;
        else if (url.startsWith("/api/ha/quality/")) b = QUAL;
        else if (url.startsWith("/api/ha/identity/")) b = IDS;
        else if (url.startsWith("/api/ha/digest")) b = digest;
        else if (url.startsWith("/api/ha/inventory")) b = {};
        else if (url.startsWith("/api/ha/devices") && !url.includes("/debug") && !url.includes("/evidence")) b = data.devices;
        else if (url.startsWith("/api/ha/summary")) b = data.summary;
        else if (url.includes("/evidence")) b = { name: { basis: "unknown", certainty: 0, rejected: [] }, brand: { basis: "none", certainty: 0, rejected: [] }, group: { basis: "none", certainty: 0, rejected: [], clues: [], value: "generic" } };
        else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
        else if (url.startsWith("/api/ha/history?")) b = data.history_all;
        return ok(b);
      };
      win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
      win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
    },
  });
  return { dom, doc: dom.window.document, errors, asked, saved };
}

(async () => {
  let p = open(DIGEST);
  await wait(800);
  let doc = p.doc;
  const q = (s) => doc.querySelector(s);

  // --- the summary card
  const night = q("#card-night");
  check(night && !night.hidden, "con qualcosa da dire la card delle ultime 12 ore c'e'");
  check(night.querySelectorAll(".ng-list li").length === 2 && /Pixel/.test(night.textContent) && /NAS/.test(night.textContent) && /40/.test(night.textContent), "dice il nuovo e il ritorno dopo 40 giorni, con i nomi");
  night.querySelector('[data-night="close"]').click();
  await wait(50);
  const seenKey = p.dom.window.localStorage.getItem("vedetta-night-seen");
  check(night.hidden && !!seenKey, "la X la nasconde e ricorda cosa ha detto");

  // --- «Last 30 days» in a card
  q('.tile[data-id="d2"]').click();
  await wait(500);
  const month = q("#mi-month");
  check(month && !month.hidden, "nella scheda c'e' la sezione degli ultimi 30 giorni");
  check(month.querySelectorAll(".mm-strip i").length === 30 && month.querySelectorAll(".mm-strip i.on").length === 9, "la striscia ha 30 giorni, 9 accesi");
  check(!!month.querySelector('.mm-class[data-c="stable"]'), "la classe e' scritta");
  const ql = month.querySelector(".mm-quality");
  check(ql && /12/.test(ql.textContent) && /2 h/.test(ql.textContent), "una riga sul collegamento: tempo tipico e interruzione piu' lunga");
  const more = month.querySelector('[data-mm="changes"]'), list = () => month.querySelector(".mm-changes");
  check(more && list().hidden && /2/.test(more.textContent), "i cambi di nome e marca sono chiusi, col numero");
  more.click();
  await wait(50);
  check(!list().hidden && list().children.length === 2 && /android-7f3a/.test(list().textContent) && /Pixel/.test(list().textContent), "un tocco li apre: prima e dopo");
  check(p.asked.some((u) => u.startsWith("/api/ha/recurrence/d2")) && p.asked.some((u) => u.startsWith("/api/ha/quality/d2")) && p.asked.some((u) => u.startsWith("/api/ha/identity/d2")), "chiede i tre dati della scheda");
  const dlg = q("#more");
  if (dlg.hasAttribute("open")) dlg.removeAttribute("open");

  // --- «Download the list»
  q("#btn-menu").click();
  await wait(100);
  const item = q("#menu [data-inventory]");
  check(!!item, "nel menu c'e' Scarica l'elenco");
  item.click();
  await wait(100);
  const inv = q("#invdlg");
  check(inv.hasAttribute("open"), "apre la sua finestra");
  const sw = () => inv.querySelector('[data-inv="hide"]');
  check(sw().getAttribute("aria-checked") === "true", "«Nascondi MAC e IP» parte acceso");
  inv.querySelector('[data-inv-fmt="json"]').click();
  await wait(20);
  sw().click();
  await wait(20);
  inv.querySelector('[data-inv="go"]').click();
  await wait(200);
  const asked = p.asked.filter((u) => u.startsWith("/api/ha/inventory"));
  check(asked.length === 1 && /format=json/.test(asked[0]) && /hide=0/.test(asked[0]), "il file chiesto ha le scelte fatte (" + asked[0] + ")");
  check(p.saved.length === 1 && p.saved[0] === "vedetta-inventory-x.csv" && !inv.hasAttribute("open"), "il file si salva col nome dato dal server, e la finestra si chiude");
  check(p.errors.length === 0, "nessun errore nella pagina" + (p.errors.length ? ": " + p.errors[0] : ""));
  p.dom.window.close();

  // --- the same summary already hidden: the card stays hidden; nothing to say: hidden
  p = open(DIGEST, { "vedetta-night-seen": seenKey });
  await wait(800);
  check(p.doc.querySelector("#card-night").hidden, "la stessa cosa gia' nascosta non torna");
  p.dom.window.close();
  p = open({ first_window: false, new: [], back: [], silent: [], labels: {}, cards: 3, online: 3 });
  await wait(800);
  check(p.doc.querySelector("#card-night").hidden, "senza niente da dire la card non c'e'");
  p.dom.window.close();
  p = open(Object.assign({}, DIGEST, { first_window: true }));
  await wait(800);
  check(p.doc.querySelector("#card-night").hidden, "la prima finestra di un'installazione non dice niente");
  p.dom.window.close();

  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
