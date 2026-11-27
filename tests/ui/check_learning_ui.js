// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The notice of the first hours (people saw brands they do not own in the first hours: the recognition was still gathering clues). While the summary says
// `learning_until` in the future the page shows a small notice that can be closed; closed, it does not come back in this browser; gone by itself at that time.
// Needs jsdom (see check_evidence_ui.js).   node tests/ui/check_learning_ui.js [it|en]
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
const TEXT = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "locales", lang, "ha.json"), "utf8"));
const KEY = "vedetta-ha-learning-closed";

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }

// A page whose summary says `until` (seconds); `stored` is what this browser already remembers.
function open(until, stored) {
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
      if (stored !== undefined) win.localStorage.setItem(KEY, stored);
      win.fetch = (url) => {
        const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve("") });
        let b = {};
        if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
        else if (url.startsWith("/api/ha/summary")) b = Object.assign({}, data.summary, { learning_until: until });
        else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
        else if (url.startsWith("/api/ha/history?")) b = data.history_all;
        return ok(b);
      };
      win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
      win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
    },
  });
  return { dom, win: dom.window, doc: dom.window.document, errors };
}
const shown = (p) => { const el = p.doc.getElementById("learning"); return !!el && !el.hidden; };

(async () => {
  const now = Date.now() / 1000;
  // 1. the first hours: the notice is there, says it, and closes
  let p = open(now + 20 * 3600);
  await wait(900);
  check(shown(p), "in the first hours the notice is shown");
  const el = p.doc.getElementById("learning");
  check(!!el && el.textContent.includes(TEXT["js.ha.learning.text"]), "it says: " + TEXT["js.ha.learning.text"]);
  const x = el && el.querySelector("button[data-learning-close]");
  check(!!x && !!x.getAttribute("aria-label") && x.getAttribute("aria-label") === x.title, "it has a close button with its label");
  check(el && el.getAttribute("role") === "status", "a status, not an alert");
  if (x) x.click();
  await wait(50);
  check(!shown(p), "closed, it goes away");
  check(p.win.localStorage.getItem(KEY) === String(now + 20 * 3600), "and this browser remembers it");
  check(p.errors.length === 0, "no error in the page" + (p.errors.length ? ": " + p.errors[0] : ""));
  p.dom.window.close();

  // 2. already closed in this browser: not shown again
  p = open(now + 20 * 3600, String(now + 20 * 3600));
  await wait(900);
  check(!shown(p), "closed before: not shown again");
  p.dom.window.close();

  // 3. after the 48 hours the server says nothing: no notice
  p = open(null);
  await wait(900);
  check(!shown(p), "after the first 48 hours: no notice");
  p.dom.window.close();

  // 4. the time runs out while the page is open: it goes away by itself
  p = open(Date.now() / 1000 + 1.5);
  await wait(700);
  check(shown(p), "still in time: shown");
  await wait(1500);
  check(!shown(p), "the time is over: gone by itself");
  p.dom.window.close();

  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
