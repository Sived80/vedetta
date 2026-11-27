// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The Appropriate Legal Notices (GPL-3.0, sections 0 and 5d) behind ONE entry of the menu, as section 0 allows ("a prominent item in the list"):
// at the foot "About Vedetta" opens a window with the version, the copyright, the license, no warranty, and the links to the license and to
// GitHub (the source code). No line of small print in the menu any more. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_about_ui.js [it|en]
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

const WORDS = {
  it: { entry: "Informazioni su Vedetta", warranty: "senza alcuna garanzia", license: "Leggi la licenza", github: "Apri su GitHub" },
  en: { entry: "About Vedetta", warranty: "without any warranty", license: "Read the license", github: "Open on GitHub" },
}[lang];
const REPO = "https://github.com/Sived80/vedetta";
const newTab = (a) => a && a.getAttribute("target") === "_blank" && /noopener/.test(a.getAttribute("rel") || "");

(async () => {
  await wait(800);
  doc.getElementById("btn-menu").click();
  await wait(100);
  const menu = doc.getElementById("menu");
  check(!menu.querySelector(".menu-legal"), "no line of small print in the menu any more");
  const foot = menu.querySelector(".menu-foot");
  const entry = foot && foot.querySelector("button[data-about]");
  check(menu.lastElementChild === foot && !!entry && foot.firstElementChild === entry, "at the foot of the menu, on the left, one entry");
  check(entry && entry.textContent.trim() === WORDS.entry && entry.querySelector("svg"), "the entry reads \"" + WORDS.entry + "\" with an icon (" + (entry && entry.textContent.trim()) + ")");
  check(!foot.querySelector("a"), "the foot has no link to GitHub of its own: it is in the window");
  entry.click();
  await wait(50);
  const dlg = doc.getElementById("aboutdlg");
  check(menu.hidden && dlg && dlg.hasAttribute("open"), "the entry closes the menu and opens the window");
  const text = dlg.textContent.replace(/\s+/g, " ");
  check(dlg.querySelector(".mi-title").textContent.trim() === "Vedetta" && /\d+\.\d+/.test(dlg.querySelector(".mi-sub").textContent), "title Vedetta and the version under it");
  check(text.includes("© 2026 Sived80"), "the copyright notice");
  check(text.includes("GPL-3.0") && text.includes("NOTICE"), "the license, with the additional terms of NOTICE");
  check(text.includes(WORDS.warranty), "no warranty");
  const links = Array.from(dlg.querySelectorAll("a"));
  const lic = links.find((a) => a.textContent.trim() === WORDS.license);
  const gh = links.find((a) => a.textContent.trim() === WORDS.github);
  check(lic && lic.getAttribute("href") === REPO + "/blob/main/LICENSE" && newTab(lic), "the license link opens the LICENSE on GitHub in a new tab");
  check(gh && gh.getAttribute("href") === REPO && newTab(gh) && gh.classList.contains("filled"), "the main button opens the repository (the source code) in a new tab");
  dlg.querySelector('[data-about="close"]').click();
  await wait(50);
  check(!dlg.hasAttribute("open"), "the X closes the window");
  check(errors.length === 0, "no error in the page" + (errors.length ? ": " + errors[0] : ""));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
