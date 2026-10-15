// The flag of the report: on the icon of the tile, as it always was (a small flag, hidden until the device is flagged), and in the open card the button with the flag is blue/azzurro (primary theme color), plain icon only without words, steady (no flashing), and it goes back to plain when the flag is removed. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_flag_ui.js [it|en]
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
const WORD = lang === "it" ? "Segnalato" : "Flagged";

const errors = [], posts = [];
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
      if (url.includes("/override")) { posts.push(JSON.parse(opts.body)); b = { ok: true }; }
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
const win = dom.window, doc = win.document;
const q = (s) => doc.querySelector(s);
const flagBtn = () => q("#more .mi-flag");
const ev = (type, target) => target.dispatchEvent(new win.Event(type, { bubbles: true, cancelable: true }));

(async () => {
  await wait(800);
  // --- not flagged: no flag on the icon, a plain button in the card
  const iconFlag = (id) => q('.tile[data-id="' + id + '"] .tile-flag');
  check(!!iconFlag("d2") && iconFlag("d2").hidden, "scheda non segnalata: la bandierina sull'icona c'e' ma e' nascosta");
  q('.tile[data-id="d2"]').click();
  await wait(400);
  check(!!flagBtn() && !flagBtn().classList.contains("on") && !flagBtn().querySelector(".mi-flag-txt") && flagBtn().getAttribute("aria-pressed") === "false", "scheda non segnalata: tasto normale, senza parola");

  // --- flag it: the form, the save, then the steady orange button with the word
  flagBtn().click();
  await wait(100);
  const form = q("#focus-form");
  check(!!form, "il tasto apre il modulo della segnalazione");
  ev("submit", form);
  await wait(400);
  check(posts.length === 1 && posts[0].focus === true, "il server riceve la segnalazione");
  check(flagBtn().classList.contains("on") && flagBtn().getAttribute("aria-pressed") === "true", "segnalata: il tasto e' acceso");
  check(!flagBtn().querySelector(".mi-flag-txt") && flagBtn().textContent.trim() === "" && !!flagBtn().querySelector("svg"), "segnalata: il tasto resta solo icona, senza parola (mai '" + WORD + "')");
  check(!iconFlag("d2").hidden && q('.tile[data-id="d2"]').classList.contains("flagged") && !!iconFlag("d2").title, "segnalata: la bandierina sull'icona si vede, com'era, con il suo titolo");

  q('.tile[data-id="d2"]').click();
  await wait(100);
  doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  q('.tile[data-id="d2"]').click();
  await wait(300);

  // --- remove the flag: back to plain
  flagBtn().click();
  await wait(100);
  const off = q('[data-act="focus-off"]');
  check(!!off, "con la segnalazione attiva il modulo offre 'togli la segnalazione'");
  off.click();
  await wait(400);
  check(posts.length === 2 && posts[1].focus === false, "il server riceve la rimozione");
  check(!flagBtn().classList.contains("on") && !flagBtn().querySelector(".mi-flag-txt"), "tolta: tasto di nuovo normale, senza parola");
  check(iconFlag("d2").hidden && !q('.tile[data-id="d2"]').classList.contains("flagged"), "tolta: la bandierina sull'icona sparisce");
  check(!flagBtn().classList.contains("flash") && !q("#more .flash"), "nessun lampo: ne' quando si segnala ne' quando si toglie");

  // --- the style: blue/azzurro (theme primary), not orange, no word
  const cssDir = path.join(__dirname, "..", "..", "vedetta", "app", "frontend", "ha", "css");   // the page links its styles: they are read from the files
  const css = fs.readdirSync(cssDir).filter((f) => f.endsWith(".css")).map((f) => fs.readFileSync(path.join(cssDir, f), "utf8")).join("\n");
  const on = /\.mi-flag\.on\s*\{([^}]*)\}/.exec(css);
  check(!!on && /--primary-color/.test(on[1]) && !/--warning-color/.test(on[1]), "il tasto acceso usa il blu/azzurro della pagina (--primary-color), non l'arancione");
  check(/\.tile\.flagged\s+\.tile-mark\.br\s*\{[^}]*left:/.test(css), "segnalata e in assestamento insieme: l'orologio passa in basso a sinistra, la bandierina resta dov'era");
  check(errors.length === 0, "nessun errore nella pagina" + (errors.length ? ": " + errors.join("; ") : ""));
  win.close();
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
