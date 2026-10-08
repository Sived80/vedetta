// The colour of a brand logo on a tile: a logo whose colour would vanish on a theme (white on light, black on dark) is drawn in the
// text colour of the theme; the others keep their own colour. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_logo_tint_ui.js [it|en]
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

// three tiles with a logo of each kind: white (Sony), black (Apple) and coloured (Samsung would be dark: use a bright one, Shelly)
const base = data.devices.devices[0];
const make = (id, name, logo, color) => Object.assign({}, base, { id, name, logo, logo_color: color, ip: "192.168.1." + (100 + data.devices.devices.length) });
data.devices.devices.push(make("t-sony", "TV Sony", "sony", "#FFFFFF"), make("t-apple", "Mac", "apple", "#000000"), make("t-shelly", "Luce", "shelly", "#4495D1"));

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
    win.fetch = (url) => {
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
const tint = (id) => { const t = doc.querySelector('.tile[data-id="' + id + '"] .tile-icon'); return t && t.style.getPropertyValue("--bc"); };

(async () => {
  await wait(800);
  check(tint("t-sony") === "var(--primary-text-color)", "un logo bianco (Sony) e' disegnato col colore del testo: si vede anche nel tema chiaro (" + tint("t-sony") + ")");
  check(tint("t-apple") === "var(--primary-text-color)", "un logo nero (Apple) col colore del testo: si vede anche nel tema scuro");
  check(/^#4495d1$/i.test(tint("t-shelly")), "un logo colorato tiene il suo colore (" + tint("t-shelly") + ")");
  check(errors.length === 0, "nessun errore nella pagina");
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
