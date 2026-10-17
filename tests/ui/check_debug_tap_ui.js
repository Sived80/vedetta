// The debug mode: three taps within two seconds on the logo or the name in the title of the Network card switch it on (the DEBUG badge appears and the root gets data-debug),
// three more switch it off; two taps only say how many are left; taps on anything else, or too slow, change nothing. The trick was lost when the header got the logo (it listened on
// an element that no longer exists). Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_debug_tap_ui.js [it|en]
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
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve("") });
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
const click = (el) => el.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true, cancelable: true }));
const on = () => doc.documentElement.hasAttribute("data-debug") && !!doc.getElementById("debug-badge");
const off = () => !doc.documentElement.hasAttribute("data-debug") && !doc.getElementById("debug-badge");

(async () => {
  await wait(800);
  const logo = doc.querySelector("#card-network .card-header .net-logo");
  const name = doc.querySelector("#card-network #net-title");
  check(logo && name, "l'intestazione della scheda Rete ha il logo e il nome");
  check(off(), "all'inizio il debug e' spento");

  click(logo); click(logo);
  await wait(50);
  check(off(), "due tocchi sul logo non bastano");
  click(logo);
  await wait(50);
  check(on(), "tre tocchi sul logo accendono il debug (scritta DEBUG e attributo sulla pagina)");
  click(logo); click(logo); click(logo);
  await wait(50);
  check(off(), "altri tre tocchi lo spengono");

  click(name); click(name); click(name);
  await wait(50);
  check(on(), "tre tocchi sul nome funzionano come sul logo");
  click(logo); click(logo); click(logo);
  await wait(50);
  check(off(), "e si spegne di nuovo");

  const elsewhere = doc.querySelector("#card-network .gauge-of");
  click(elsewhere); click(elsewhere); click(elsewhere);
  await wait(50);
  check(off(), "tre tocchi su un altro punto della scheda non fanno nulla");

  click(logo);
  await wait(2100);
  click(logo);
  await wait(2100);
  click(logo);
  await wait(50);
  check(off(), "tre tocchi troppo lenti (oltre due secondi) non contano");
  check(errors.length === 0, "nessun errore nella pagina" + (errors.length ? ": " + errors[0] : ""));
  dom.window.close();
  console.log(failed ? "FALLITI: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
