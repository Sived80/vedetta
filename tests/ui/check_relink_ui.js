// The gesture "this is a new device" (1.0 step P5) in the open card: asked of the service only for an offline card, shown only when the service
// offers it, with its text in the page's language; a tap sends it once and tells the result. An online card never asks. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_relink_ui.js [it|en]
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
const TEXTS = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "locales", lang, "ha.json"), "utf8"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }

data.devices.devices.forEach((d) => { if (d.id === "d2") { d.online = false; d.last_seen = Date.now() / 1000 - 900; } });
const errors = [], asked = [], sent = [];
let offer = true;
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
      if (url.includes("/relink")) {
        if (opts && opts.method === "POST") { sent.push(url); b = { ok: true }; } else { asked.push(url); b = { offer: offer }; }
      }
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
const button = () => q('#more [data-act="relink"]');
const closeCard = () => { const c = q('#more [data-act="close"]'); if (c) c.click(); };

(async () => {
  await wait(800);
  // an online card never asks
  q('.tile[data-id="d1"]').click();
  await wait(300);
  check(asked.length === 0 && !button(), "a card online: nothing asked, no gesture");
  closeCard();
  // an offline card the service offers it for: the button, with the text of the page's language and the explanation as its title
  q('.tile[data-id="d2"]').click();
  await wait(300);
  check(asked.length === 1 && asked[0].startsWith("/api/devices/d2/relink"), "an offline card asks whether the gesture applies");
  check(!!button() && button().textContent.trim() === TEXTS["js.ha.relink.button"] && button().title === TEXTS["js.ha.relink.hint"], "the gesture is shown, in " + lang);
  button().click();
  await wait(300);
  check(sent.length === 1 && sent[0] === "/api/devices/d2/relink", "a tap sends it once");
  const snacks = Array.from(doc.querySelectorAll(".snack .snack-text")).map((n) => n.textContent);
  check(snacks.includes(TEXTS["js.ha.relink.done"]) && !button(), "it says what happens, and the button goes");
  closeCard();
  // not offered: nothing shown
  offer = false;
  q('.tile[data-id="d2"]').click();
  await wait(300);
  check(asked.length === 2 && !button(), "not offered: no gesture");
  check(errors.length === 0, "no page errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  console.log(failed ? "FALLITI: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
