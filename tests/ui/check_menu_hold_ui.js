// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The switch of the presence held by Home Assistant in the menu (1.0.3, setting "phone_hold_ha"): it sits right under the speed of the check,
// shows the value the server has (off here, so the default of the page is not what is seen), a tap posts the new value and the menu stays open.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_menu_hold_ui.js [it|en]
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
const SERVER = { alerts: true, poll_interval: 30, miss_limit: 3, phone_hold_ha: false };

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
      const post = opts && opts.method === "POST" && url.startsWith("/api/settings");
      if (post) { posted.push(JSON.parse(opts.body)); Object.assign(SERVER, JSON.parse(opts.body)); }
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      let b = {};
      if (url.startsWith("/api/settings")) b = Object.assign({}, SERVER);
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
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }

(async () => {
  await wait(800);
  doc.getElementById("btn-menu").click();
  await wait(100);
  const menu = doc.getElementById("menu");
  const sw = () => menu.querySelector("[data-hold]");
  check(!menu.hidden && !!sw(), "il menu ha l'interruttore dei telefoni addormentati");
  if (!sw()) { console.log("FAILED: " + (failed + 1)); process.exit(1); }
  check(sw().classList.contains("rv-switch") && sw().getAttribute("role") === "switch", "e' l'interruttore gia' usato nella pagina (rv-switch)");
  const row = sw().closest(".al-row"), hint = menu.querySelector(".menu-hint");
  check(!!row && !!hint && (hint.compareDocumentPosition(row) & dom.window.Node.DOCUMENT_POSITION_FOLLOWING) &&
    (row.compareDocumentPosition(menu.querySelector("[data-flows]")) & dom.window.Node.DOCUMENT_POSITION_FOLLOWING), "sta subito sotto la velocita' del controllo");
  check(row.querySelector(".al-lbl").textContent.length > 0 && row.querySelector(".al-hint").textContent.length > 0, "ha un nome e una riga che spiega");
  check(sw().getAttribute("aria-checked") === "false" && !sw().classList.contains("on"), "mostra il valore del server: spento");
  sw().click();
  await wait(50);
  check(!menu.hidden, "toccato l'interruttore il menu resta aperto");
  check(posted.length === 1 && posted[0].phone_hold_ha === true && Object.keys(posted[0]).length === 1, "il nuovo valore e' inviato al server: " + JSON.stringify(posted));
  check(sw().getAttribute("aria-checked") === "true" && sw().classList.contains("on"), "e l'interruttore e' acceso subito");
  sw().click();
  await wait(50);
  check(posted.length === 2 && posted[1].phone_hold_ha === false && sw().getAttribute("aria-checked") === "false", "un altro tocco lo spegne di nuovo");
  check(errors.length === 0, "nessun errore nella pagina: " + errors.join(" | "));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
