// The state of analysis on the page: a lens on the top right corner of the icon of a card under analysis, a clock on the bottom right of a card that is settling, a question mark on one that is unresolved, nothing on an
// identified one; the corner follows the event "analysis" of the live stream. The WORDS (analisi in corso, in assestamento, da identificare) are only inside the open card, beside the word online/offline of its head, and
// they do not move when the card goes from online to offline; the tile has the sign and nothing else. The open card tells the state and the reasons too. Every sign has a shape and a text, never colour alone.
// Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_analysis_ui.js [it|en]
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
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }

const TEXT = lang === "it" ? { analysing: /In analisi/, settling: /In assestamento/, state: "Stato", reason: /Poche prove e un gruppo rivale/, shortA: /analisi in corso/, unresolved: /Non identificato/, shortU: /da identificare/, expired: /oltre 7 giorni/, shortS: /in assestamento/, online: "Online", offline: "Offline" }
  : { analysing: /Under analysis/, settling: /Settling/, state: "State", reason: /Little evidence and a rival group/, shortA: /analysing/, shortS: /settling/, unresolved: /Unresolved/, shortU: /to identify/, expired: /over 7 days/, online: "Online", offline: "Offline" };
const ANY_WORDS = /analisi in corso|analysing|assestamento|settling|da identificare|to identify/i;
const ANALYSIS = {
  d1: { state: "analysing", reasons: ["low_certainty", "close"], badges: [{ id: "analysing", corner: "top_right" }] },
  d3: { state: "settling", reasons: ["low_certainty"], badges: [{ id: "settling", corner: "bottom_right" }] },
};

const errors = [], handlers = {};
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
    win.fetch = (url) => {
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      let b = {};
      if (url.startsWith("/api/ha/devices") && !url.includes("/debug") && !url.includes("/evidence")) b = Object.assign({}, data.devices, { analysis: ANALYSIS });
      else if (url.startsWith("/api/ha/summary")) b = data.summary;
      else if (url.includes("/evidence")) b = { name: { basis: "unknown", certainty: 0, rejected: [] }, brand: { basis: "none", certainty: 0, rejected: [] }, group: { basis: "none", certainty: 0, rejected: [], clues: [], value: "generic" } };
      else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
      else if (url.startsWith("/api/ha/history?")) b = data.history_all;
      return ok(b);
    };
    win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener(name, fn) { handlers[name] = fn; } close() {} };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const doc = dom.window.document;
const tile = (id) => doc.querySelector('.tile[data-id="' + id + '"]');
const mark = (id, corner) => tile(id).querySelector(".tile-mark." + corner);
const shown = (el) => !!el && !el.hidden;
const hero = () => doc.querySelector("#mi-hero");
const heroAn = () => hero().querySelector(".hero-an");
const heroLabel = () => Array.from(hero().querySelectorAll(".hero-st > span")).filter((s) => !s.classList.contains("hs-hide")).map((s) => s.textContent).join("");
const close = () => doc.dispatchEvent(new dom.window.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

(async () => {
  await wait(800);
  // --- the signs on the icons: d1 under analysis (lens, top right), d3 settling (clock, bottom right), d2 identified (nothing)
  check(shown(mark("d1", "tr")) && mark("d1", "tr").classList.contains("analysing") && !!mark("d1", "tr").querySelector("svg"), "d1 in analisi: lente in alto a destra");
  check(TEXT.analysing.test(mark("d1", "tr").title) && TEXT.analysing.test(mark("d1", "tr").getAttribute("aria-label") || ""), "d1: il testo c'e' (al passaggio del mouse e per chi usa il lettore di schermo)");
  check(!shown(mark("d1", "br")), "d1: l'altro angolo resta vuoto");
  check(shown(mark("d3", "br")) && mark("d3", "br").classList.contains("settling") && !shown(mark("d3", "tr")), "d3 in assestamento: orologio in basso a destra, niente in alto");
  check(TEXT.settling.test(mark("d3", "br").title), "d3: il testo dell'assestamento");
  check(!shown(mark("d2", "tr")) && !shown(mark("d2", "br")), "d2 identificato: nessun segno");
  check(mark("d1", "tr").querySelector("svg").outerHTML !== mark("d3", "br").querySelector("svg").outerHTML, "le due forme sono diverse (non solo il colore)");
  const lensHtml = mark("d1", "tr").querySelector("svg").outerHTML;       // the lens, kept to compare the other shapes with it

  // --- the tile has the sign and NO words: its state row is what it always was (online / offline), and nothing moves
  const tileState = (id) => tile(id).querySelector(".tile-state");
  check(!doc.querySelector(".tile-an") && !doc.querySelector(".st-main"), "sulle tessere non c'e' piu' nessuna scritta dell'analisi");
  check(["d1", "d2", "d3"].every((id) => !ANY_WORDS.test(tileState(id).textContent)), "lo stato della tessera dice solo online/offline ('" + tileState("d1").textContent + "')");
  check(/analisi in corso|analysing/.test(tile("d1").getAttribute("aria-label")), "chi usa il lettore di schermo la sente comunque (aria-label)");
  const d1 = data.devices.devices.find((x) => x.id === "d1");
  const offline = (id) => handlers.device({ data: JSON.stringify({ type: "device", id: id, rev: 99, device: Object.assign({}, data.devices.devices.find((x) => x.id === id), { online: false, last_seen: Math.floor(Date.now() / 1000) - 3 * 3600, uptime: null }) }) });

  // --- the open card: the words beside online/offline in the head, in an element of their own that does not move when the state changes
  tile("d1").click();
  await wait(400);
  check(!!hero() && !!heroAn() && TEXT.shortA.test(heroAn().textContent) && !heroAn().hidden, "scheda aperta di d1: accanto allo stato c'e' la scritta ('" + heroLabel() + " · " + heroAn().textContent + "')");
  check(heroLabel() === TEXT.online, "d1 e' online: la scritta dello stato e' '" + TEXT.online + "'");
  const labels = hero().querySelectorAll(".hero-st > span");
  check(labels.length === 2 && Array.from(labels).map((s) => s.textContent).sort().join() === [TEXT.offline, TEXT.online].sort().join(), "le due parole (online e offline) stanno nello stesso posto una sull'altra: la larghezza non cambia");
  check(hero().querySelector(".hero-state") === heroAn().parentElement, "la scritta sta nella riga dello stato, in un elemento suo");
  const cssDir = path.join(__dirname, "..", "..", "vedetta", "app", "frontend", "ha", "css");
  const css = fs.readdirSync(cssDir).filter((f) => f.endsWith(".css")).map((f) => fs.readFileSync(path.join(cssDir, f), "utf8")).join("\n");
  check(/\.hero-st\s*\{[^}]*display:\s*grid/.test(css) && /\.hero-st\s*>\s*span\s*\{[^}]*grid-area:\s*1\s*\/\s*1/.test(css) && /\.hs-hide\s*\{[^}]*visibility:\s*hidden/.test(css), "lo stile le sovrappone (griglia) e nasconde quella non vera con visibility: la riga non si muove");
  offline("d1");
  await wait(150);
  check(heroLabel() === TEXT.offline && !!heroAn() && TEXT.shortA.test(heroAn().textContent) && !heroAn().hidden, "d1 e' passata offline: la parola e' '" + heroLabel() + "' e la scritta dell'analisi c'e' ancora");
  check(hero().querySelectorAll(".hero-st > span").length === 2, "e le due parole sono ancora al loro posto");
  close();

  // --- the live event moves the signs and the words
  handlers.analysis({ data: JSON.stringify({ type: "analysis", cards: { d2: ANALYSIS.d1 } }) });
  check(!shown(mark("d1", "tr")) && !shown(mark("d3", "br")) && shown(mark("d2", "tr")), "l'evento 'analysis' sposta i segni: d1 e d3 liberi, d2 in analisi");
  tile("d2").click();
  await wait(400);
  check(TEXT.shortA.test(heroAn().textContent) && !heroAn().hidden, "scheda aperta di d2 (ora in analisi): la scritta c'e'");
  handlers.analysis({ data: JSON.stringify({ type: "analysis", cards: {} }) });
  check(heroAn().hidden && heroAn().textContent === "", "con la scheda aperta l'evento toglie la scritta (senza chiudere la scheda)");
  handlers.analysis({ data: JSON.stringify({ type: "analysis", cards: { d2: ANALYSIS.d3 } }) });
  check(TEXT.shortS.test(heroAn().textContent) && heroAn().dataset.s === "settling", "e la rimette, con lo stato 'in assestamento'");
  close();
  handlers.analysis({ data: JSON.stringify({ type: "analysis", cards: {} }) });
  check(["d1", "d2", "d3"].every((id) => !shown(mark(id, "tr")) && !shown(mark(id, "br"))), "senza schede in analisi non resta nessun segno");
  handlers.analysis({ data: JSON.stringify({ type: "analysis", cards: ANALYSIS }) });
  check(shown(mark("d1", "tr")) && shown(mark("d3", "br")), "tornano al loro posto");

  // --- unresolved (a week under analysis): a question mark, not the lens; its words in the open card; the invitation in the row
  handlers.analysis({ data: JSON.stringify({ type: "analysis", cards: { d2: { state: "unresolved", reasons: ["low_certainty", "expired"], badges: [{ id: "unresolved", corner: "top_right" }] } } }) });
  check(shown(mark("d2", "tr")) && mark("d2", "tr").classList.contains("unresolved") && !mark("d2", "tr").classList.contains("analysing"), "d2 non identificata: segno proprio in alto a destra");
  check(!!mark("d2", "tr").querySelector("svg") && mark("d2", "tr").querySelector("svg").outerHTML !== lensHtml, "con una forma diversa dalla lente");
  check(TEXT.unresolved.test(mark("d2", "tr").title), "con il suo testo");
  tile("d2").click();
  await wait(400);
  check(TEXT.shortU.test(heroAn().textContent) && heroAn().dataset.s === "unresolved", "scheda aperta di d2: la scritta breve accanto allo stato ('" + heroAn().textContent + "')");
  const rowU = Array.from(doc.querySelectorAll("#mi-attrs .attr")).find((r) => r.querySelector("dt") && r.querySelector("dt").textContent === TEXT.state);
  check(!!rowU && TEXT.unresolved.test(rowU.textContent) && TEXT.expired.test(rowU.textContent), "e la riga: lo stato e l'invito a darle un nome (dopo 7 giorni)");
  close();
  handlers.analysis({ data: JSON.stringify({ type: "analysis", cards: ANALYSIS }) });

  // --- the open card: a line with the state and the reasons, only for a card that is not identified
  tile("d1").click();
  await wait(400);
  const rows = Array.from(doc.querySelectorAll("#mi-attrs .attr"));
  const line = rows.find((r) => r.querySelector("dt") && r.querySelector("dt").textContent === TEXT.state);
  check(!!line && TEXT.analysing.test(line.textContent) && TEXT.reason.test(line.textContent), "scheda aperta di d1: riga '" + TEXT.state + "' con lo stato e i motivi");
  // an identified card has no words in its head
  close();
  tile("d3").click();
  handlers.analysis({ data: JSON.stringify({ type: "analysis", cards: { d1: ANALYSIS.d1 } }) });
  await wait(400);
  check(heroAn().hidden && heroAn().textContent === "", "una scheda identificata non ha nessuna scritta accanto allo stato");
  close();
  check(errors.length === 0, "nessun errore nella pagina" + (errors.length ? ": " + errors.join("; ") : ""));
  dom.window.close();
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
