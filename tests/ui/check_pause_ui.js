// The pause menu (the round LED of the Network card): it opens under the button with the title and, in one row, 15 min / 1 h / 8 h and under them the full-width button that stops
// until the user resumes ("Ferma" / "Stop"); a choice asks the server and closes the menu; Escape and a click outside close it; its width is the one the placement function
// gives (inside the card, between the minimum and the maximum). While paused the menu has the title, one button to resume and the line that says when. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_pause_ui.js [it|en]
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
const STOP = { it: "Ferma", en: "Stop" }[lang] || "Ferma";
const out = fs.mkdtempSync(path.join(os.tmpdir(), "vedetta-ui-"));
const built = spawnSync(process.env.PYTHON || "python", [path.join(__dirname, "build_page.py"), out, lang], { cwd: path.join(__dirname, "..", "..", "vedetta"), encoding: "utf8" });
if (built.status !== 0) { console.log("build_page.py failed:\n" + built.stdout + built.stderr); process.exit(1); }
const html = fs.readFileSync(path.join(out, "page.html"), "utf8");
const data = JSON.parse(fs.readFileSync(path.join(out, "data.json"), "utf8"));

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }

function open(paused) {
  const calls = [], errors = [];
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
        const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve("") });
        if (url.startsWith("/api/pause")) { calls.push({ method: (opts && opts.method) || "GET", body: opts && opts.body ? JSON.parse(opts.body) : null }); return ok({ paused: false }); }
        let b = {};
        if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
        else if (url.startsWith("/api/ha/summary")) {
          b = Object.assign({}, data.summary);
          if (paused) b.poll = { interval_ms: 30000, next_in_ms: 5000, paused: true, paused_in_ms: 600000, paused_total_ms: 900000 };
        }
        else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
        else if (url.startsWith("/api/ha/history?")) b = data.history_all;
        return ok(b);
      };
      win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
      win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
    },
  });
  return { dom, doc: dom.window.document, calls, errors };
}

(async () => {
  // 1. running
  let p = open(false);
  await wait(800);
  let doc = p.doc;
  const live = doc.getElementById("live"), menu = doc.getElementById("pause-menu");
  check(live && menu && menu.hidden, "il pulsante c'e' e il menu e' chiuso");
  live.click();
  await wait(50);
  check(!menu.hidden && live.getAttribute("aria-expanded") === "true", "un clic sul pulsante apre il menu");
  check(menu.querySelectorAll(".menu-label").length === 1 && menu.querySelector(".menu-label").textContent.length > 0, "c'e' il titolo");
  const pills = Array.from(menu.querySelectorAll("[data-pause]"));
  check(pills.map((b) => b.dataset.pause).join(",") === "15,60,480,0", "i tasti sono 15 min, 1 h, 8 h e quello che ferma, in quest'ordine");
  check(pills[3].textContent.trim() === STOP && pills[3].classList.contains("full"), "l'ultimo si chiama «" + STOP + "» ed e' a tutta larghezza (" + pills[3].textContent.trim() + ")");
  check(pills.slice(0, 3).every((b) => !b.classList.contains("full")), "gli altri tre stanno in una riga");
  const w = parseFloat(menu.style.width);
  check(w >= 184 && w <= 232, "la larghezza viene dal calcolo della posizione, tra 184 e 232 px (" + menu.style.width + ")");
  check(/px$/.test(menu.style.left) && /px$/.test(menu.style.top) && /px/.test(menu.style.transformOrigin), "posizione e punto di partenza dell'animazione sono scritti");
  check(menu.querySelector(".menu-hint") && menu.querySelector(".menu-hint").textContent.length > 0, "sotto c'e' la riga che spiega cosa succede");
  doc.documentElement.dispatchEvent(new doc.defaultView.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  doc.dispatchEvent(new doc.defaultView.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await wait(30);
  check(menu.hidden, "Esc chiude il menu");
  live.click();
  await wait(30);
  doc.body.click();
  await wait(30);
  check(menu.hidden, "un clic fuori chiude il menu");
  live.click();
  await wait(30);
  menu.querySelector('[data-pause="15"]').click();
  await wait(60);
  check(menu.hidden && p.calls.length === 1 && p.calls[0].method === "POST" && p.calls[0].body.minutes === 15, "scegliere 15 min chiude il menu e lo chiede al server (POST, 15 minuti)");
  live.click();
  await wait(30);
  menu.querySelector('[data-pause="0"]').click();
  await wait(60);
  check(p.calls.length === 2 && p.calls[1].body.minutes === 0, "«" + STOP + "» chiede una pausa senza fine (0 minuti)");
  check(p.errors.length === 0, "nessun errore nella pagina" + (p.errors.length ? ": " + p.errors[0] : ""));
  p.dom.window.close();

  // 2. already paused
  p = open(true);
  await wait(800);
  doc = p.doc;
  const live2 = doc.getElementById("live"), menu2 = doc.getElementById("pause-menu");
  live2.click();
  await wait(50);
  check(!menu2.hidden && menu2.querySelectorAll("[data-resume]").length === 1 && !menu2.querySelector("[data-pause]"), "in pausa il menu ha solo il tasto per riprendere");
  check(menu2.querySelector(".menu-label").textContent.length > 0 && menu2.querySelector(".menu-hint").textContent.length > 0, "con il titolo e la riga che dice quando riprende");
  menu2.querySelector("[data-resume]").click();
  await wait(60);
  check(menu2.hidden && p.calls.length === 1 && p.calls[0].method === "DELETE", "riprendere chiude il menu e manda la richiesta di fine pausa (DELETE)");
  check(p.errors.length === 0, "nessun errore nella pagina (in pausa)" + (p.errors.length ? ": " + p.errors[0] : ""));
  p.dom.window.close();

  console.log(failed ? "FALLITI: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
