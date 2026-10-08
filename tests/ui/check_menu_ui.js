// The speed buttons of the menu: the time is written inside them, a choice stays lit at once and the menu stays open (so the line under it can be
// read), a tap between the buttons changes nothing. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_menu_ui.js [it|en]
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
  doc.getElementById("btn-menu").click();
  await wait(100);
  const menu = doc.getElementById("menu");
  const pills = () => Array.from(menu.querySelectorAll("[data-speed]"));
  check(!menu.hidden && pills().length === 3, "il menu e' aperto e ha i tre tasti di velocita'");
  check(pills().map((p) => p.querySelector(".pill-sub").textContent).join("|") === "10 s|30 s|1 min", "il tempo e' scritto dentro ai tasti: 10 s, 30 s, 1 min (" + pills().map((p) => p.querySelector(".pill-sub").textContent).join("|") + ")");
  check(pills().every((p) => p.querySelector(".pill-main").textContent.length > 0), "e sopra il tempo c'e' il nome");
  const hint = () => menu.querySelector(".menu-hint").textContent;
  pills()[0].click();
  await wait(50);
  check(!menu.hidden, "scelta una velocita' il menu resta aperto");
  check(pills()[0].getAttribute("aria-pressed") === "true" && pills().filter((p) => p.getAttribute("aria-pressed") === "true").length === 1, "e il tasto scelto e' acceso subito, uno solo");
  check(/20 s/.test(hint()), "la riga sotto e' leggibile e dice il nuovo tempo (" + hint() + ")");
  check(posted.length === 1 && posted[0].poll_interval === 10 && posted[0].miss_limit === 2, "la scelta e' inviata al server");
  menu.querySelector(".menu-pills:last-of-type, .menu-pills").dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));   // a tap in the gap between the buttons
  await wait(50);
  check(!menu.hidden && pills().filter((p) => p.getAttribute("aria-pressed") === "true").length === 1, "un tocco tra i tasti non spegne e non chiude niente");
  pills()[2].click();
  await wait(50);
  check(pills()[2].getAttribute("aria-pressed") === "true" && /5 min/.test(hint()), "cambiando velocita' si accende quella nuova e la riga cambia (" + hint() + ")");
  // the status line: its two parts stay whole (the second goes under the first on a narrow screen, never a break in the middle of a phrase)
  const st = doc.getElementById("scan-text");
  const parts = Array.from(st.querySelectorAll(".st-part")).map((p) => p.textContent);
  check(parts.length === 2 && !!st.querySelector(".st-sep"), "la riga di stato ha due parti intere e un separatore (" + parts.join(" | ") + ")");
  check(/prossimo controllo tra \d+ s|next check in \d+ s/.test(parts[1] || ""), "la seconda parte e' il conto alla rovescia, intera");
  check(st.title === st.dataset.text && st.title.includes(" · "), "il testo completo resta nel tooltip");
  check(errors.length === 0, "nessun errore nella pagina");
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
