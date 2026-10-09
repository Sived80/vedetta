// The one-time invitation to star the project: a star on the menu button, its entry first in the menu, gone at once when the link is
// clicked, and it does not come back. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_star_ui.js [it|en]
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

function open(starHint) {
  const errors = [], posts = [], opened = [];
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
      win.open = function () { opened.push(1); return null; };       // the link opens another tab: jsdom has no windows
      win.fetch = (url, opts) => {
        const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
        let b = {};
        if (url.startsWith("/api/ha/star")) { posts.push(opts && opts.method); b = { ok: true }; }
        else if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
        else if (url.startsWith("/api/ha/summary")) b = Object.assign({}, data.summary, { star_hint: starHint, version: "0.4.7" });
        else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
        else if (url.startsWith("/api/ha/history?")) b = data.history_all;
        return ok(b);
      };
      win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
      win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
    },
  });
  return { dom, doc: dom.window.document, errors, posts, opened };
}

(async () => {
  // 1) the server says it may appear
  let a = open(true);
  await wait(800);
  const doc = a.doc, menu = doc.getElementById("menu"), btn = doc.getElementById("btn-menu"), badge = () => doc.querySelector(".star-badge");
  check(badge() && !badge().hidden, "la stellina e' sul tasto del menu");
  check(badge().parentNode === btn.parentNode, "sta nello stesso contenitore del tasto (sopra la pagina, senza spostare nulla)");
  btn.click();
  const entry = () => menu.querySelector(".star-entry");
  check(entry() && menu.firstElementChild === entry(), "aprendo il menu, la prima voce e' l'invito");
  check(entry().getAttribute("href") === "https://github.com/Sived80/vedetta/tree/main#readme" && entry().target === "_blank" && /noopener/.test(entry().rel), "e' un link a GitHub che si apre in un'altra scheda");
  check(a.posts.length === 1 && a.posts[0] === "POST", "il server viene avvisato subito che e' stata mostrata (una sola volta)");
  // a choice inside the menu rebuilds it: the entry stays while this menu is open, and the server is not asked again
  const speed = menu.querySelector("[data-speed]");
  speed.click();
  await wait(50);
  check(entry() && a.posts.length === 1, "scegliendo una velocita' l'invito resta e non c'e' un secondo avviso al server");
  // click on it: gone at once, then the menu closes and the star is gone
  entry().click();
  check(!entry() || entry().style.display === "none", "cliccando 'Accendi una stella' la voce sparisce subito");
  await wait(50);
  check(menu.hidden, "poi il menu si chiude");
  check(badge().hidden, "e la stellina sul tasto sparisce");
  btn.click();
  check(!entry(), "riaprendo il menu l'invito non c'e' piu'");
  check(a.errors.length === 0, "nessun errore nella pagina" + (a.errors.length ? ": " + a.errors.join("; ") : ""));
  a.dom.window.close();

  // 2) seen but not clicked: closing the menu is enough, it does not come back
  a = open(true);
  await wait(800);
  a.doc.getElementById("btn-menu").click();
  check(!!a.doc.querySelector(".star-entry"), "(2) l'invito e' nel menu");
  a.doc.getElementById("btn-menu").click();           // closes
  check(a.doc.querySelector(".star-badge").hidden, "(2) chiuso il menu senza cliccare, la stellina sparisce");
  a.doc.getElementById("btn-menu").click();
  check(!a.doc.querySelector(".star-entry"), "(2) e riaprendo non c'e' piu'");
  a.dom.window.close();

  // 3) the server says no: nothing at all
  a = open(false);
  await wait(800);
  check(a.doc.querySelector(".star-badge").hidden, "(3) senza il via del server la stellina non si vede");
  a.doc.getElementById("btn-menu").click();
  check(!a.doc.querySelector(".star-entry") && a.posts.length === 0, "(3) niente voce nel menu e nessuna chiamata al server");
  a.dom.window.close();

  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
