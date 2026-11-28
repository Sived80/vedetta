// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The ring of the types (net-gauge.js) is built element by element, never from an HTML string (code scanning: "DOM text reinterpreted as
// HTML"): the arcs are SVG circles made with createElementNS, each with its group class, its key, its dash and a <title> made of text only.
// The ring must stay the same: one arc per group with devices (at most seven, the rest in «Others»), the counts in the titles, a hover and
// a click on an arc still work.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_gauge_dom_ui.js [it|en]
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

const errors = [];
const ringHtmlWrites = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
vc.on("error", (e) => errors.push("console.error: " + e));
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
  beforeParse(win) {
    // Every HTML string written into the ring of the types is recorded: there must be none.
    const desc = Object.getOwnPropertyDescriptor(win.Element.prototype, "innerHTML");
    Object.defineProperty(win.Element.prototype, "innerHTML", {
      configurable: true, get: desc.get,
      set(v) { if (this.id === "g-types" && v) ringHtmlWrites.push(String(v).slice(0, 60)); desc.set.call(this, v); },
    });
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
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }

(async () => {
  await wait(800);
  const segs = Array.from(doc.querySelectorAll("#g-types .g-seg"));
  const groups = new Set(DEVS.map((d) => d.type));
  check(segs.length > 0 && segs.length === Math.min(groups.size, 7), "one arc per group with devices, at most seven: " + segs.length + " for " + groups.size);
  check(ringHtmlWrites.length === 0, "the ring is never written as an HTML string: " + JSON.stringify(ringHtmlWrites));
  const SVG = "http://www.w3.org/2000/svg";
  check(segs.every((s) => s.namespaceURI === SVG && s.tagName.toLowerCase() === "circle"), "every arc is an SVG circle");
  check(segs.every((s) => s.dataset.k && s.classList.contains("gc-" + (s.dataset.k === "_other" ? "other" : s.dataset.k))), "every arc has its key and the colour of its group");
  check(segs.every((s) => /^\d+(\.\d+)? \d+(\.\d+)?$/.test(s.getAttribute("stroke-dasharray") || "") && s.getAttribute("r") === "48" && s.getAttribute("transform") === "rotate(-90 60 60)"),
    "every arc keeps its dash, radius and rotation");
  const titles = segs.map((s) => s.querySelector("title"));
  check(titles.every((tt) => tt && tt.namespaceURI === SVG && tt.children.length === 0 && /: \d+$/.test(tt.textContent)), "every arc has a title of text only, with its count");
  const total = segs.reduce((sum, s) => sum + Number(s.querySelector("title").textContent.split(": ").pop()), 0);
  check(total === DEVS.length, "the counts of the arcs add up to the devices: " + total + "/" + DEVS.length);
  const first = segs[0];
  first.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await wait(150);
  check(doc.querySelector("#g-types .g-seg.hl") && doc.querySelector("#g-types .g-seg.hl").dataset.k === first.dataset.k, "a click on an arc still picks its group");
  check(errors.length === 0, "no error in the page: " + errors.join(" | "));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
