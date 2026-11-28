// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The switch "MAC on the cards" in the menu (1.1.1, setting "tile_mac", asked by a user): it sits right under the view (cards or list), shows
// the value the server has, a tap posts the new value and the menu stays open; on, every card with a MAC shows it under its address, in the
// same box as the address (so the list view needs no new column); off, no card shows a MAC and the address line is the address alone.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_menu_mac_ui.js [it|en]
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
const DEVS = data.devices.devices;
const SERVER = { alerts: true, poll_interval: 30, miss_limit: 3, phone_hold_ha: true, tile_mac: false };

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
  const tiles = () => Array.from(doc.querySelectorAll(".tile[data-id]"));
  const withMac = DEVS.filter((d) => d.mac);
  const macShown = () => tiles().filter((el) => { const m = el.querySelector(".tile-mac"); return m && !m.hidden && m.textContent; });
  check(tiles().length > 0 && withMac.length > 0, "la pagina ha card e dispositivi con MAC: " + tiles().length + "/" + withMac.length);
  check(macShown().length === 0, "spento (valore del server): nessuna card mostra il MAC");
  const one = tiles().find((el) => withMac.some((d) => d.id === el.dataset.id));
  const dev = one && withMac.find((d) => d.id === one.dataset.id);
  check(!!one && one.querySelector(".tile-ip").textContent === dev.ip, "spento, la riga dell'indirizzo e' l'indirizzo e basta: " + (one && one.querySelector(".tile-ip").textContent));
  doc.getElementById("btn-menu").click();
  await wait(100);
  const menu = doc.getElementById("menu");
  const sw = () => menu.querySelector("[data-tilemac]");
  check(!menu.hidden && !!sw(), "il menu ha l'interruttore del MAC sulle card");
  if (!sw()) { console.log("FAILED: " + (failed + 1)); process.exit(1); }
  check(sw().classList.contains("rv-switch") && sw().getAttribute("role") === "switch", "e' l'interruttore gia' usato nella pagina (rv-switch)");
  const row = sw().closest(".al-row"), view = menu.querySelector("[data-view]");
  check(!!row && !!view && (view.compareDocumentPosition(row) & dom.window.Node.DOCUMENT_POSITION_FOLLOWING) &&
    (row.compareDocumentPosition(menu.querySelector("[data-speed]")) & dom.window.Node.DOCUMENT_POSITION_FOLLOWING), "sta sotto la vista (card o elenco), prima della velocita'");
  check(row.querySelector(".al-lbl").textContent.length > 0 && row.querySelector(".al-hint").textContent.length > 0, "ha un nome e una riga che spiega");
  check(sw().getAttribute("aria-checked") === "false" && !sw().classList.contains("on"), "mostra il valore del server: spento");
  sw().click();
  await wait(100);
  check(!menu.hidden, "toccato l'interruttore il menu resta aperto");
  check(posted.length === 1 && posted[0].tile_mac === true && Object.keys(posted[0]).length === 1, "il nuovo valore e' inviato al server: " + JSON.stringify(posted));
  check(sw().getAttribute("aria-checked") === "true" && sw().classList.contains("on"), "e l'interruttore e' acceso subito");
  const shown = macShown();
  check(shown.length > 0 && shown.every((el) => { const d = DEVS.find((x) => x.id === el.dataset.id); return d && d.mac && el.querySelector(".tile-mac").textContent === d.mac; }),
    "acceso: le card con un MAC lo mostrano (" + shown.length + "), ognuna il suo");
  check(!!one && !!one.querySelector(".tile-ip .tile-mac"), "il MAC sta nella stessa casella dell'indirizzo (anche la vista elenco lo mostra)");
  check(tiles().every((el) => { const d = DEVS.find((x) => x.id === el.dataset.id); const m = el.querySelector(".tile-mac"); return !d || d.mac || !m || m.hidden; }),
    "una card senza MAC non mostra una riga vuota");
  sw().click();
  await wait(100);
  check(posted.length === 2 && posted[1].tile_mac === false && sw().getAttribute("aria-checked") === "false", "un altro tocco lo spegne di nuovo");
  check(macShown().length === 0, "e i MAC spariscono dalle card");
  check(errors.length === 0, "nessun errore nella pagina: " + errors.join(" | "));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
