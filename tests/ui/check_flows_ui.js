// The "Search methods" window: three searches as tabs, the functions of the chosen one in panels by risk (closed at the start),
// counters that follow the switches, and every change saved for the three searches. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_flows_ui.js [it|en]
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
const payload = JSON.parse(fs.readFileSync(path.join(__dirname, "flows_payload_" + lang + ".json"), "utf8"));
delete payload.ui;

const errors = [];
const posts = [];
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
    win.fetch = (url, opts) => {
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      let b = {};
      if (url.startsWith("/api/flows")) {
        if (opts && opts.method === "POST") {
          if (url.startsWith("/api/flows/reset")) b = JSON.parse(JSON.stringify(payload));
          else {
            const sent = JSON.parse(opts.body);
            posts.push(sent); b = JSON.parse(JSON.stringify(payload)); Object.keys(sent.flows).forEach((p) => { b.flows[p].steps = sent.flows[p]; });
          }
        } else b = JSON.parse(JSON.stringify(payload));
      }
      else if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
      else if (url.startsWith("/api/ha/summary")) b = data.summary;
      else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
      else if (url.startsWith("/api/ha/history?")) b = data.history_all;
      return ok(b);
    };
    win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const doc = dom.window.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }
const dlg = () => doc.getElementById("flows");
const q = (s) => dlg().querySelector(s);
const qa = (s) => Array.from(dlg().querySelectorAll(s));
const click = (el) => el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));

(async () => {
  await wait(800);
  doc.getElementById("btn-menu").click();
  const item = doc.querySelector("#menu [data-flows]");
  check(!!item, "la voce di menu dei metodi di ricerca esiste");
  click(item);
  await wait(200);
  check(dlg().hasAttribute("open"), "la finestra si apre");
  check(qa('[role="tab"]').length === 3, "tre schede (le tre ricerche)");
  check(q('[role="tab"][aria-selected="true"]').dataset.flTab === "initial", "parte dalla ricerca iniziale");
  check(qa(".fl-grp-b").every((b) => b.hidden), "i pannelli partono chiusi");
  check(qa(".fl-chips .risk").length === 3, "tre contatori");
  check(!/riscansione|rescan/i.test(dlg().textContent), "nessuna parola vietata nei testi");

  // the locked step of the initial search is on, disabled and marked
  const lockedRow = q(".fl-sw:disabled");
  check(!!lockedRow && lockedRow.checked && !!lockedRow.closest("label").querySelector(".fl-req"), "la funzione obbligatoria e' attiva, bloccata e segnata");

  // open the first panel
  click(q(".fl-grp-h"));
  check(q(".fl-grp-h").getAttribute("aria-expanded") === "true" && !q(".fl-grp-b").hidden, "il pannello si apre");

  // go to the deep search by keyboard-free click, count the chips, toggle one step
  click(q('[data-fl-tab="deep"]'));
  check(q('[role="tab"][aria-selected="true"]').dataset.flTab === "deep", "si passa alla ricerca approfondita");
  const total = payload.flows.deep.steps.length + payload.steps.filter((s) => s.locked_in.includes("deep") && !payload.flows.deep.steps.includes(s.id)).length;
  const chipOn = () => parseInt(q(".fl-chips .risk.r-easy").textContent, 10);
  const before = chipOn();
  check(before === total, "il contatore delle attive e' giusto (" + before + ")");
  click(q('[data-fl-grp="deepeasy"]'));
  const sw = qa('.fl-sw[data-p="deep"]:not(:disabled)').find((i) => i.checked && i.closest(".fl-grp").classList.contains("r-easy"));
  sw.checked = false;
  sw.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  await wait(100);
  check(chipOn() === before - 1, "il contatore scende di uno");
  check(posts.length === 1 && Object.keys(posts[0].flows).sort().join() === "associative,deep,initial", "si salvano tutte e tre le ricerche");
  check(!posts[0].flows.deep.includes(sw.dataset.step), "la funzione spenta non e' piu' nell'elenco salvato");

  // the choice survives a change of tab and back
  click(q('[data-fl-tab="associative"]'));
  click(q('[data-fl-tab="deep"]'));
  check(qa('.fl-sw[data-p="deep"]').find((i) => i.dataset.step === sw.dataset.step).checked === false, "tornando alla scheda la scelta resta");

  // arrow keys move between the tabs
  q('[data-fl-tab="deep"]').dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
  check(q('[role="tab"][aria-selected="true"]').dataset.flTab === "initial", "freccia destra: dall'ultima alla prima");

  // reset
  click(q('[data-fl="reset"]'));
  await wait(100);
  click(q('[data-fl-tab="deep"]'));
  check(qa('.fl-sw[data-p="deep"]').find((i) => i.dataset.step === sw.dataset.step).checked === true, "ripristina predefiniti riaccende la funzione");

  click(q('[data-fl="close"]'));
  check(!dlg().hasAttribute("open"), "la finestra si chiude");
  check(errors.length === 0, "nessun errore nella pagina" + (errors.length ? ": " + errors.join("; ") : ""));
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
