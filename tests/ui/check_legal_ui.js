// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The Appropriate Legal Notices (GPL-3.0, sections 0 and 5d) in the menu: the copyright, no warranty, the license and the source code, the two
// links opening in a new tab like the other links of the page to outside. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_legal_ui.js [it|en]
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

const WORDS = { it: { warranty: "nessuna garanzia", source: "codice sorgente" }, en: { warranty: "no warranty", source: "source code" } }[lang];
const REPO = "https://github.com/Sived80/vedetta";

(async () => {
  await wait(800);
  doc.getElementById("btn-menu").click();
  await wait(100);
  const menu = doc.getElementById("menu");
  const legal = menu.querySelector(".menu-legal");
  check(!menu.hidden && !!legal, "the open menu has the legal line");
  const text = legal ? legal.textContent.replace(/\s+/g, " ").trim() : "";
  check(text === "Vedetta © 2026 Sived80 · GPL-3.0 · " + WORDS.warranty + " · " + WORDS.source, "the line reads copyright, license, no warranty and source code (" + text + ")");
  const links = legal ? Array.from(legal.querySelectorAll("a")) : [];
  const lic = links.find((a) => a.textContent.trim() === "GPL-3.0");
  const src = links.find((a) => a.textContent.trim() === WORDS.source);
  check(!!lic && lic.getAttribute("href") === REPO + "/blob/main/LICENSE", "GPL-3.0 links to the LICENSE on GitHub (" + (lic && lic.getAttribute("href")) + ")");
  check(!!src && src.getAttribute("href") === REPO, "the source code links to the repository (" + (src && src.getAttribute("href")) + ")");
  check(links.length === 2 && links.every((a) => a.getAttribute("target") === "_blank" && /noopener/.test(a.getAttribute("rel") || "")),
    "both links open in a new tab, without access to the page (noopener), like the repository link of the menu");
  check(menu.lastElementChild === legal, "the line is the last thing in the menu, under the repository link");
  check(errors.length === 0, "no error in the page" + (errors.length ? ": " + errors[0] : ""));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
