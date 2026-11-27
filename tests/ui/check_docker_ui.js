// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The page in Docker mode (1.1, the server writes "docker": true in the start data): the menu has «Sign out», which posts a form to
// /logout (the session ends on the server); a newer version shows the red arrow also outside Home Assistant, and its window gives the
// two commands of Compose and a link to the release notes (a new tab) instead of asking Home Assistant for its Updates page; every call
// of the page to the server carries X-Vedetta-Request. Under the Supervisor ("docker": false) there is no «Sign out». Needs jsdom.
// from the vedetta/ folder:  node ../tests/ui/check_docker_ui.js [it|en]
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
const page = fs.readFileSync(path.join(out, "page.html"), "utf8");
const data = JSON.parse(fs.readFileSync(path.join(out, "data.json"), "utf8"));
const TEXT = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "locales", lang, "ha.json"), "utf8"));

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }

function open(docker, update, haLink) {
  const errors = [], calls = [], posted = [];
  const html = page.replace(/"docker": (true|false)/, '"docker": ' + docker);
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
  vc.on("error", (e) => errors.push("console.error: " + e));
  const dom = new JSDOM(html, {
    runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://192.0.2.200:8765/ha?lang=" + lang,
    beforeParse(win) {
      win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
      win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
      win.HTMLFormElement.prototype.submit = function () { posted.push({ method: this.method, action: this.getAttribute("action") }); };
      win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
      win.HTMLElement.prototype.scrollIntoView = function () {};
      win.fetch = (url, opts) => {
        calls.push({ url: url, method: (opts && opts.method) || "GET", body: opts && opts.body, headers: (opts && opts.headers) || {} });
        const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve("") });
        let b = {};
        if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
        else if (url.startsWith("/api/ha/summary")) b = Object.assign({}, data.summary, { update: update, ha_link: haLink === undefined ? null : haLink });
        else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
        else if (url.startsWith("/api/ha/history?")) b = data.history_all;
        return ok(b);
      };
      win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
      win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
    },
  });
  return { dom, doc: dom.window.document, errors, calls, posted };
}

// Turns the carousel to the Home Assistant tile; its body, or null.
async function haTile(doc) {
  for (let i = 0; i < 12; i++) {
    const name = doc.querySelector("#rot .t-name");
    if (name && name.textContent.trim() === TEXT["js.ha.tile.ha"]) return doc.querySelector("#rot .t-body");
    doc.querySelector("#rot").click();
    await wait(350);
  }
  return null;
}

(async () => {
  // 1. Docker, a newer version, the page in its own tab (no Home Assistant around it)
  let p = open(true, { available: true, installed: "1.1.0", latest: "1.1.1" });
  await wait(900);
  let doc = p.doc;
  check(p.calls.length > 0 && p.calls.every((c) => c.headers["X-Vedetta-Request"] === "1"), "every call of the page carries X-Vedetta-Request (" + p.calls.length + ")");
  doc.getElementById("btn-menu").click();
  await wait(100);
  const menu = doc.getElementById("menu");
  const out = menu.querySelector("[data-logout]");
  check(!!out && out.textContent.trim() === TEXT["js.ha.menu.logout"] && out.querySelector("svg"), "the menu has «" + TEXT["js.ha.menu.logout"] + "» with an icon");
  const up = menu.querySelector("button[data-update]");
  check(!!up, "the update arrow is there outside Home Assistant too");
  up.click();
  await wait(50);
  const dlg = doc.getElementById("updatedlg");
  const steps = Array.from(dlg.querySelectorAll(".upd-steps li")).map((li) => li.textContent);
  check(dlg.hasAttribute("open") && steps.length === 3 && /docker compose pull/.test(steps[0]) && /docker compose up -d/.test(steps[1]), "the window gives the commands of Compose");
  const notes = dlg.querySelector('a[data-upd="notes"]');
  check(!!notes && notes.getAttribute("href") === "https://github.com/Sived80/vedetta/releases/tag/v1.1.1" && notes.target === "_blank" && /noopener/.test(notes.rel),
    "and a link to the release notes in a new tab");
  check(!dlg.querySelector('[data-upd="go"]'), "no button that asks Home Assistant for its Updates page");
  dlg.querySelector('[data-upd="close"]').click();
  doc.getElementById("btn-menu").click();
  await wait(50);
  doc.getElementById("menu").querySelector("[data-logout]").click();
  check(p.posted.length === 1 && p.posted[0].method === "post" && p.posted[0].action === "/logout", "«Sign out» posts a form to /logout: " + JSON.stringify(p.posted));
  check(p.errors.length === 0, "no error in the page" + (p.errors.length ? ": " + p.errors[0] : ""));
  p.dom.window.close();

  // 3. Docker, Home Assistant not connected: after the login the window that explains how to connect it opens by itself, once; its
  // «Do not show again» is saved on the server; hidden, or with Home Assistant connected, it does not open
  p = open(true, null, { connected: false, problem: "no_token", devices: 0, at: null, help_hidden: false });
  await wait(900);
  doc = p.doc;
  const help = doc.getElementById("hahelpdlg");
  check(help.hasAttribute("open"), "Home Assistant not connected: the window opens by itself after the login");
  check(help.querySelector(".mi-sub").textContent === TEXT["js.ha.hahelp.sub_no_token"] && help.querySelectorAll(".upd-steps li").length === 4,
    "it says what is missing and the four steps");
  const guide = help.querySelector('a[href*="DOCKER.md#home-assistant"]');
  check(!!guide && guide.target === "_blank" && /noopener/.test(guide.rel), "with a link to the full guide in a new tab");
  help.querySelector("[data-hahelp-hide]").checked = true;
  help.querySelector('[data-hahelp="close"]').click();
  await wait(50);
  const saved = p.calls.filter((c) => c.url === "/api/settings" && c.method === "POST");
  check(!help.hasAttribute("open") && saved.length === 1 && saved[0].body === '{"ha_help_hidden":true}', "«Do not show again» is saved on the server: " + JSON.stringify(saved.map((c) => c.body)));
  p.dom.window.close();
  p = open(true, null, { connected: false, problem: "no_token", devices: 0, at: null, help_hidden: true });
  await wait(900);
  check(!p.doc.getElementById("hahelpdlg").hasAttribute("open"), "hidden by the person: it does not open by itself");
  let body = await haTile(p.doc);
  check(!!body && body.textContent.includes(TEXT["js.ha.tile.ha_not_configured"]) && body.querySelector(".t-foot [data-open]"),
    "the carousel has the Home Assistant tile: not connected, with «" + TEXT["js.ha.tile.ha_how"] + "»");
  body.querySelector(".t-foot [data-open]").click();
  await wait(50);
  check(p.doc.getElementById("hahelpdlg").hasAttribute("open"), "which opens the window again");
  p.dom.window.close();
  p = open(true, null, { connected: true, problem: null, devices: 149, at: Date.now() / 1000, help_hidden: false });
  await wait(900);
  check(!p.doc.getElementById("hahelpdlg").hasAttribute("open"), "Home Assistant connected: it does not open");
  body = await haTile(p.doc);
  check(!!body && body.textContent.includes(TEXT["js.ha.tile.ha_connected"]) && body.textContent.includes("149") && !body.querySelector(".t-foot [data-open]"),
    "the tile says connected, with its 149 devices");
  check(p.errors.length === 0, "no error in the page" + (p.errors.length ? ": " + p.errors[0] : ""));
  p.dom.window.close();

  // 2. Under the Supervisor: no «Sign out», and no arrow outside Home Assistant (as before)
  p = open(false, { available: true, installed: "1.1.0", latest: "1.1.1" });
  await wait(900);
  doc = p.doc;
  doc.getElementById("btn-menu").click();
  await wait(100);
  check(!doc.querySelector("#menu [data-logout]"), "under the Supervisor there is no «Sign out»");
  check(!doc.querySelector("#menu button[data-update]"), "and no arrow outside Home Assistant");
  check(!doc.getElementById("hahelpdlg").hasAttribute("open"), "and never the window about connecting Home Assistant");
  p.dom.window.close();

  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
