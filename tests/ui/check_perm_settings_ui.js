// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The Permissions tile (functions that reach the internet): inside Home Assistant, when the server knows the slug of the app, the foot of the tile is a
// «Settings» button that asks Home Assistant to open the app's Configuration page (where those options are set). Outside Home Assistant, or with no
// slug, the tile keeps its legend. Invented slug.
// Needs jsdom (see check_evidence_ui.js).   node tests/ui/check_perm_settings_ui.js [it|en]
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

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }

// A page whose summary says `slug`; `inHA` puts a host window above it (the page is in an iframe of Home Assistant).
function open(slug, inHA) {
  const sent = [], errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
  vc.on("error", (e) => errors.push("console.error: " + e));
  const external = { public_ip: { on: true }, path: { on: true, target: "1.1.1.1" }, mac_database: { on: false, updated: null }, app_slug: slug };
  const dom = new JSDOM(html, {
    runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
    beforeParse(win) {
      win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
      win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
      win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
      win.HTMLElement.prototype.scrollIntoView = function () {};
      if (inHA) {
        const host = { postMessage: (m) => sent.push(m) };
        try { Object.defineProperty(win, "parent", { configurable: true, value: host }); } catch (e) { win.parent = host; }
      }
      win.fetch = (url) => {
        const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve("") });
        let b = {};
        if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
        else if (url.startsWith("/api/ha/summary")) b = Object.assign({}, data.summary, { external: external });
        else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
        else if (url.startsWith("/api/ha/history?")) b = data.history_all;
        return ok(b);
      };
      win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
      win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
    },
  });
  return { dom, doc: dom.window.document, sent, errors };
}
// Turns the carousel to the Permissions tile; its body, or null.
async function permTile(doc) {
  for (let i = 0; i < 9; i++) {
    const name = doc.querySelector("#rot .t-name");
    if (name && name.textContent.trim() === TEXT["js.ha.tile.external"]) { doc.querySelector("#rot").dispatchEvent(new doc.defaultView.MouseEvent("mouseenter")); return doc.querySelector("#rot .t-body"); }
    doc.querySelector("#rot").click();
    await wait(350);
  }
  return null;
}

(async () => {
  // 1. inside Home Assistant, the slug known: a «Settings» button opens the app's Configuration page
  let p = open("0123abcd_vedetta", true);
  await wait(1500);
  let body = await permTile(p.doc);
  check(!!body, "the carousel has the Permissions tile");
  const go = body && body.querySelector(".t-foot [data-open]");
  check(!!go && go.textContent.trim() === TEXT["js.ha.tile.ext_settings"], "its foot is a «" + TEXT["js.ha.tile.ext_settings"] + "» button");
  const nav = () => p.sent.filter((m) => m.type === "home-assistant/navigate");
  check(nav().length === 0, "nothing asked of Home Assistant before the press");
  if (go) go.click();
  await wait(100);
  check(nav().length === 1 && nav()[0].path === "/hassio/addon/0123abcd_vedetta/config", "the press asks Home Assistant to open the app's Configuration page: " + JSON.stringify(nav()));
  check(p.errors.length === 0, "no error in the page" + (p.errors.length ? ": " + p.errors[0] : ""));
  p.dom.window.close();

  // 2. inside Home Assistant, the slug not known yet: the legend as before, no button
  p = open(null, true);
  await wait(1500);
  body = await permTile(p.doc);
  check(!!body && !body.querySelector("[data-open]") && !!body.querySelector(".bar-leg"), "no slug: the legend, no button");
  p.dom.window.close();

  // 3. outside Home Assistant (the page opened by itself): no Configuration page to open
  p = open("0123abcd_vedetta", false);
  await wait(1500);
  body = await permTile(p.doc);
  check(!!body && !body.querySelector("[data-open]") && !!body.querySelector(".bar-leg"), "outside Home Assistant: the legend, no button");
  p.dom.window.close();

  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
