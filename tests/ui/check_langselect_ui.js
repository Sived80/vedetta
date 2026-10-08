// The language list of the menu: a field with the globe, a themed list (not the native one) with a check on the current language, keyboard and
// pointer, a pick posts the language, Escape closes only the list. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_langselect_ui.js [it|en]
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

const posted = [];
const langPosts = [];
const errors = [];
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
      if (opts && opts.method === "POST" && url.startsWith("/api/lang/")) langPosts.push(url);
      if (opts && opts.method === "POST" && url.startsWith("/api/settings")) posted.push(JSON.parse(opts.body));
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      let b = {};
      if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
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
const unused = (id) => { const t = doc.querySelector('.tile[data-id="' + id + '"] .tile-icon'); return t && t.style.getPropertyValue("--bc"); };

(async () => {
  await wait(800);
  const w = dom.window;
  const langs = w.VEDETTA_LANGS || [];
  doc.getElementById("btn-menu").click();
  await wait(100);
  const menu = doc.getElementById("menu");
  const btn = () => doc.getElementById("lang-btn");
  const list = () => doc.querySelector(".sel-list");
  check(!!btn() && !!btn().querySelector("svg, .mdi") && btn().getAttribute("aria-haspopup") === "listbox", "il menu ha un solo campo lingua con il globo");
  check(!menu.querySelector("[data-lang]"), "e non ci sono piu' le pillole delle lingue");
  btn().click();
  await wait(30);
  check(!!list() && list().children.length === langs.length && langs.length >= 3, "si apre l'elenco con tutte le lingue offerte dal server (" + langs.length + ")");
  check(btn().getAttribute("aria-expanded") === "true" && list().getAttribute("role") === "listbox", "il campo e' segnato aperto e l'elenco e' un listbox");
  check(list().querySelectorAll('[aria-selected="true"]').length === 1 && list().querySelector('[aria-selected="true"]').dataset.v === lang, "la spunta e' sulla lingua attiva e solo su quella");
  const key = (k) => list().dispatchEvent(new w.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
  const act = () => Array.from(list().children).findIndex((li) => li.classList.contains("act"));
  const start = act();
  key("ArrowDown");
  check(act() === (start + 1) % langs.length, "freccia giu' sposta l'evidenziazione");
  key("End");
  check(act() === langs.length - 1, "Fine va all'ultima");
  key("Home");
  check(act() === 0, "Inizio va alla prima");
  key("Escape");
  await wait(20);
  check(!list() && !menu.hidden && btn().getAttribute("aria-expanded") === "false", "Esc chiude solo l'elenco, il menu resta aperto");
  btn().click();
  await wait(30);
  doc.body.dispatchEvent(new w.Event("pointerdown", { bubbles: true }));
  await wait(20);
  check(!list(), "un tocco fuori chiude l'elenco");
  btn().click();
  await wait(30);
  btn().click();
  await wait(30);
  check(!list(), "un secondo tocco sul campo lo chiude");
  btn().click();
  await wait(30);
  const other = Array.from(list().children).find((li) => li.dataset.v !== ""+lang+"");
  other.click();
  await wait(80);
  check(langPosts.length === 1 && langPosts[0] === "/api/lang/" + other.dataset.v, "scegliere una lingua la invia al server (" + langPosts.join(",") + ")");
  check(!list(), "e l'elenco si chiude");
  const real = errors.filter((e) => !/Not implemented: navigation/.test(e));   // the pick reloads the page: jsdom cannot navigate
  check(real.length === 0, "nessun errore nella pagina " + real.join(" ; ").slice(0, 400));
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
