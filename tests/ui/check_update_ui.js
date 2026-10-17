// The update dot, the red arrow at the foot of the menu and the window that explains: with a newer version the dot is on the menu button and goes away when the menu
// is opened (it does not come back); the arrow sits at the right of the repository link, in a box like the rows above, with a tip that says what it does; it opens a
// window in the style of the others (the X first on the left, the explanation, Cancel and the main button); the main button asks Home Assistant to open its Updates page
// (a message to the host) and the X does not; without an update, or outside Home Assistant, there is no arrow. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_update_ui.js [it|en]
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

// A page with the given answer of the server about the update; `inHA` puts a host window above it (the page is in an iframe of Home Assistant).
function open(update, inHA) {
  const sent = [], errors = [];
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
      if (inHA) {
        const host = { postMessage: (m) => sent.push(m) };
        try { Object.defineProperty(win, "parent", { configurable: true, value: host }); } catch (e) { win.parent = host; }
      }
      win.fetch = (url) => {
        const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve("") });
        let b = {};
        if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
        else if (url.startsWith("/api/ha/summary")) b = Object.assign({}, data.summary, { update: update });
        else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
        else if (url.startsWith("/api/ha/history?")) b = data.history_all;
        return ok(b);
      };
      win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
      win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
    },
  });
  return { dom, doc: dom.window.document, sent, errors };
}

(async () => {
  // 1. a newer version, the page inside Home Assistant
  let p = open({ available: true, installed: "0.7.1", latest: "0.7.2" }, true);
  await wait(800);
  let doc = p.doc;
  const dot = () => doc.querySelector(".upd-dot");
  check(dot() && !dot().hidden, "con una versione nuova c'e' il pallino rosso sul tasto del menu");
  check(dot().parentNode === doc.getElementById("btn-menu").parentNode, "e sta accanto al tasto (come la stella)");
  doc.getElementById("btn-menu").click();
  await wait(100);
  const menu = doc.getElementById("menu");
  check(!menu.hidden && dot().hidden, "aperto il menu il pallino sparisce");
  const foot = menu.querySelector(".menu-foot");
  const repo = foot && foot.querySelector("a.menu-repo");
  const up = foot && foot.querySelector("button[data-update]");
  check(foot && menu.lastElementChild === foot, "in fondo al menu c'e' la riga del piede");
  check(repo && repo.href === "https://github.com/Sived80/vedetta" && repo.target === "_blank" && /noopener/.test(repo.rel), "a sinistra il link della repository, in una nuova scheda e senza referente");
  check(up && foot.lastElementChild === up && repo.nextElementSibling === up, "a destra del link c'e' la freccia dell'aggiornamento");
  check(up && /0\.7\.2/.test(up.title) && up.title === up.getAttribute("aria-label"), "sopra la freccia il testo dice cosa fa e quale versione (" + (up && up.title) + ")");
  check(up && up.querySelector("svg"), "la freccia e' un'icona");
  check(!foot.querySelector(".menu-version") && !/0\.7\.1\s*$/.test(foot.textContent.trim()), "la versione non e' piu' in fondo al menu");
  doc.getElementById("btn-menu").click();           // close
  await wait(50);
  doc.getElementById("btn-menu").click();           // open again
  await wait(50);
  check(dot().hidden, "il pallino non torna alla riapertura (stessa versione)");
  const dlg = doc.getElementById("updatedlg");
  menu.querySelector("button[data-update]").click();
  await wait(50);
  check(menu.hidden && dlg.hasAttribute("open"), "la freccia chiude il menu e apre la finestra");
  const head = dlg.querySelector(".mi-header");
  check(head && head.firstElementChild.matches('button[data-upd="close"]') && head.querySelector("svg"), "in alto a sinistra c'e' la X (prima del titolo)");
  check(dlg.querySelector(".mi-title").textContent.length > 0 && /0\.7\.1/.test(dlg.querySelector(".mi-sub").textContent) && /0\.7\.2/.test(dlg.querySelector(".mi-sub").textContent), "titolo e versioni (da -> a)");
  check(dlg.querySelectorAll(".upd-steps li").length === 4, "la finestra spiega cosa succede in quattro passi");
  const acts = dlg.querySelector(".mi-actions");
  check(acts && acts.children.length === 2 && acts.children[0].matches('.btn.text[data-upd="close"]') && acts.children[1].matches('.btn.filled[data-upd="go"]'), "in fondo i tasti: Annulla e quello principale, come le altre finestre");
  const nav = () => p.sent.filter((m) => m.type === "home-assistant/navigate");      // the page also subscribes to the properties of the host (narrow): not a navigation
  check(nav().length === 0, "finora non e' partito nessun messaggio di navigazione verso Home Assistant");
  dlg.querySelector('[data-upd="go"]').click();
  await wait(50);
  check(!dlg.hasAttribute("open") && nav().length === 1 && nav()[0].path === "/config/updates", "il tasto principale chiude la finestra e chiede a Home Assistant di aprire la pagina Aggiornamenti");
  menu.hidden || doc.getElementById("btn-menu").click();
  doc.getElementById("btn-menu").click();
  await wait(50);
  menu.querySelector("button[data-update]").click();
  await wait(50);
  dlg.querySelector('[data-upd="close"]').click();
  await wait(50);
  check(!dlg.hasAttribute("open") && nav().length === 1, "la X chiude senza mandare nulla");
  check(p.errors.length === 0, "nessun errore nella pagina" + (p.errors.length ? ": " + p.errors[0] : ""));
  p.dom.window.close();

  // 2. no update: no dot, no arrow
  p = open({ available: false, installed: "0.7.1", latest: "0.7.1" }, true);
  await wait(800);
  doc = p.doc;
  check(doc.querySelector(".upd-dot").hidden, "senza aggiornamento non c'e' il pallino");
  doc.getElementById("btn-menu").click();
  await wait(100);
  check(!doc.querySelector("button[data-update]") && doc.querySelector(".menu-foot a.menu-repo"), "e in fondo al menu c'e' solo il link della repository");
  p.dom.window.close();

  // 3. a newer version but the page is not inside Home Assistant: the dot yes, the arrow no (there is no Updates page to open)
  p = open({ available: true, installed: "0.7.1", latest: "0.7.2" }, false);
  await wait(800);
  doc = p.doc;
  check(!doc.querySelector(".upd-dot").hidden, "fuori da Home Assistant il pallino c'e'");
  doc.getElementById("btn-menu").click();
  await wait(100);
  check(!doc.querySelector("button[data-update]"), "ma la freccia no: non c'e' una pagina Aggiornamenti da aprire");
  p.dom.window.close();

  console.log(failed ? "FALLITI: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
