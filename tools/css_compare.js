#!/usr/bin/env node
// Compares the rendering of the /ha page with two style sheets, A and B: the proof that reorganising the CSS changes nothing.
//
//   node tools/css_compare.js [--a A.css] [--b B.css] [--base REV] [--lang it|en] [--themes light,dark] [--widths 1280,390]
//                             [--only state1,state2] [--json out.json]
//
//   --a     the first style sheet; without it, the parts of vedetta/app/frontend/ha/css/ at the git revision --base (default HEAD)
//   --b     the second one; without it, the parts in the working copy. Parts are joined in name order, as app/assets.py does.
//   --only  some of the states (names in STATES below); an unknown name is an error.
//   exit 0: no difference; 1: differences (the summary is printed, the full list goes to --json); 2: the check could not run,
//   with the reason (a state not reached, Chrome, the page). A state is never skipped: every theme x width x state is read or
//   the run ends with 2.
//
// How: tests/ui/build_page.py renders the page with invented devices; a tiny local server gives it to Chrome headless (DevTools
// Protocol over Node's own WebSocket, nothing to install). fetch and EventSource are mocked like in the jsdom UI tests. For every
// theme, width and UI state the page is loaded afresh, the tool waits until it is settled (drawn, at the emulated width, still),
// drives it into the state (clicks, each on an element waited for) and waits for the state's own check; a state not reached is
// tried once more from a fresh page and reported, a second miss ends the run. Then the page timers are frozen, the check is
// read again, and the computed style of every element (and of ::before/::after) is read with A, the sheet is swapped for B in
// place and read again.
// Animations and transitions are switched off by a sheet that is the same for A and B, so A against A gives zero differences.
// Chrome: CHROME env variable, or the usual install paths.
"use strict";
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const { spawn, spawnSync, execFileSync } = require("child_process");

const ROOT = path.resolve(__dirname, "..");
const VEDETTA = path.join(ROOT, "vedetta");
const CSS_REL = "vedetta/app/frontend/ha/css";
const STATIC = path.join(VEDETTA, "app", "static");

// ------------------------------------------------------------------ arguments
function parseArgs(argv) {
  const o = { base: "HEAD", lang: "it", themes: "light,dark", widths: "1280,390" };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const m = /^--(a|b|base|lang|json|themes|widths|only)$/.exec(k);
    if (!m || i + 1 >= argv.length) { if (k === "-h" || k === "--help") { usage(0); } console.error("unknown or incomplete option: " + k); usage(2); }
    o[m[1]] = argv[++i];
  }
  if (!/^(it|en)$/.test(o.lang)) { console.error("--lang must be it or en"); usage(2); }
  return o;
}
function usage(code) {
  console.log("usage: node tools/css_compare.js [--a A.css] [--b B.css] [--base REV] [--lang it|en] [--themes light,dark] [--widths 1280,390] [--only states] [--json out.json]");
  process.exit(code);
}

// ------------------------------------------------------------------ the two style sheets
// Python's read_text() turns CRLF into LF: the same here, so a checkout with CRLF joins like the app does.
const lf = (s) => s.replace(/\r\n?/g, "\n");
function cssFromRev(rev) {
  const names = execFileSync("git", ["ls-tree", "--name-only", rev, CSS_REL + "/"], { cwd: ROOT, encoding: "utf8" })
    .split("\n").map((s) => s.trim()).filter((s) => s.endsWith(".css")).sort();
  if (!names.length) throw new Error("no CSS parts at " + rev + ":" + CSS_REL);
  return { text: names.map((n) => lf(execFileSync("git", ["show", rev + ":" + n], { cwd: ROOT, encoding: "utf8", maxBuffer: 64 << 20 }))).join(""),
    label: rev + " (" + names.map((n) => path.posix.basename(n)).join(" + ") + ")" };
}
function cssFromWorkingCopy() {
  const dir = path.join(ROOT, CSS_REL);
  const names = fs.readdirSync(dir).filter((n) => n.endsWith(".css")).sort();
  return { text: names.map((n) => lf(fs.readFileSync(path.join(dir, n), "utf8"))).join(""), label: "working copy (" + names.join(" + ") + ")" };
}
const cssFromFile = (f) => ({ text: lf(fs.readFileSync(f, "utf8")), label: f });

// ------------------------------------------------------------------ what is compared
const PROPS = ["display", "position", "top", "right", "bottom", "left", "inset-inline-start", "inset-inline-end", "float", "clear",
  "width", "height", "min-width", "min-height", "max-width", "max-height", "box-sizing", "aspect-ratio",
  "margin-top", "margin-right", "margin-bottom", "margin-left", "padding-top", "padding-right", "padding-bottom", "padding-left",
  "color", "background-color", "background-image", "background-position", "background-size", "background-repeat", "background-clip",
  "border-top-width", "border-right-width", "border-bottom-width", "border-left-width", "border-top-style", "border-right-style",
  "border-bottom-style", "border-left-style", "border-top-color", "border-right-color", "border-bottom-color", "border-left-color",
  "border-top-left-radius", "border-top-right-radius", "border-bottom-right-radius", "border-bottom-left-radius",
  "outline-style", "outline-width", "outline-color", "outline-offset",
  "font-family", "font-size", "font-weight", "font-style", "font-variant-numeric", "line-height", "letter-spacing", "text-align",
  "text-transform", "text-decoration-line", "text-overflow", "text-indent", "vertical-align", "white-space", "word-break", "overflow-wrap",
  "opacity", "visibility", "transform", "transform-origin", "filter", "backdrop-filter", "clip-path", "mask-image", "-webkit-mask-image",
  "row-gap", "column-gap", "grid-template-columns", "grid-template-rows", "grid-template-areas", "grid-auto-flow", "grid-auto-rows",
  "grid-column-start", "grid-column-end", "grid-row-start", "grid-row-end",
  "flex-direction", "flex-wrap", "flex-grow", "flex-shrink", "flex-basis", "justify-content", "justify-items", "justify-self",
  "align-content", "align-items", "align-self", "place-self", "order", "z-index", "box-shadow", "text-shadow",
  "overflow-x", "overflow-y", "overscroll-behavior-y", "scrollbar-width", "scrollbar-gutter", "cursor", "pointer-events", "user-select",
  "list-style-type", "object-fit", "fill", "stroke", "stroke-width", "content", "contain", "container-type", "color-scheme",
  "accent-color", "caret-color", "appearance", "isolation", "mix-blend-mode", "table-layout", "touch-action"];
const PSEUDO_PROPS = ["content", "display", "position", "top", "left", "right", "bottom", "width", "height", "color", "background-color",
  "background-image", "border-top-width", "border-top-color", "border-top-left-radius", "opacity", "transform", "mask-image",
  "-webkit-mask-image", "box-shadow", "z-index", "inset-inline-start"];

// Same for A and B, first layer of the page so its !important wins over every layered !important of the sheets under test.
const FREEZE_CSS = "@layer __cmp_freeze { *, *::before, *::after, ::backdrop { animation: none !important; transition: none !important; " +
  "caret-color: transparent !important; scroll-behavior: auto !important; } }";

// ------------------------------------------------------------------ the UI states
// Each state: the steps to reach it from a freshly loaded dashboard, and a check that it is really there (it is read again
// after the animations are finished and the page is frozen, so a state that closes by itself is caught, never compared).
// A step is a click on the first element matching a selector (waited for, up to 5 s) or a condition to wait for.
const click = (sel) => ({ click: sel });
const waitFor = (expr) => ({ wait: expr });
const DEEP_MENU_OPEN = "(function () { var m = document.getElementById('deep-menu'), b = document.getElementById('deep-badge'); if (!m || m.hidden) return false;" +
  " var r = m.getBoundingClientRect(); return m.querySelectorAll('.dm-tile').length === 2 && !!b && b.dataset.at === 'slot' && !!m.querySelector('.dm-slot #deep-badge')" +
  " && document.getElementById('btn-deepmenu').getAttribute('aria-expanded') === 'true' && r.width > 0 && r.left >= 0 && r.right <= innerWidth; })()";
const STATES = [
  { name: "dashboard", steps: [], check: "document.querySelectorAll('.tile').length >= 3 && !!document.querySelector('#card-network #btn-scan')" },
  { name: "more-info", steps: [click('.tile[data-id="d1"]')], check: "document.getElementById('more').open && !!document.querySelector('#more #mi-attrs .attr')" },
  { name: "more-attrs", steps: [click('.tile[data-id="d1"]'), click("#attr-more > summary")], check: "document.getElementById('more').open && document.getElementById('attr-more').open" },
  { name: "more-flag", steps: [click('.tile[data-id="d1"]'), click('#more [data-act="focus"]')], check: "document.getElementById('more').open && !!document.getElementById('focus-form')" },
  { name: "more-rename", steps: [click('.tile[data-id="d2"]'), click('#more [data-act="rename"]')], check: "document.getElementById('more').open && !!document.getElementById('rn-name')" },
  { name: "more-ignore", steps: [click('.tile[data-id="d2"]'), click('#more [data-act="ignore"]')], check: "document.getElementById('more').open && !!document.querySelector('#more [data-act=\"ignore-confirm\"]')" },
  { name: "more-type", steps: [click('.tile[data-id="d1"]'), click('#more [data-act="type-menu"]')], check: "document.getElementById('more').open && document.querySelectorAll('#more .type-menu .menu-item').length > 3" },
  { name: "more-evidence", steps: [click('.tile[data-id="d1"]'), waitFor("(document.querySelector('#more [data-ev-pct=\"name\"]') || {}).textContent === '65%'"), click('#more [data-ev-i="name"]')],
    check: "document.getElementById('more').open && !!document.querySelector('#more #ev-pop .ev-pop-h') && document.querySelector('#more [data-ev-i=\"name\"]').getAttribute('aria-expanded') === 'true'" },
  // the badge flies from the arrow into the menu: the check waits for it to land in its slot
  { name: "deep-menu", steps: [click("#btn-deepmenu")], check: DEEP_MENU_OPEN },
  { name: "main-menu", steps: [click("#btn-menu")], check: "!document.getElementById('menu').hidden && document.querySelectorAll('#menu .menu-item').length > 3" },
  { name: "live-menu", steps: [click("#live")], check: "!document.getElementById('pause-menu').hidden && document.querySelectorAll('#pause-menu .menu-item').length > 1" },
  { name: "export", steps: [click("#btn-menu"), click("#menu [data-export]")], check: "document.getElementById('exportdlg').open && !!document.querySelector(\"#exportdlg [data-xp='dest:me']\")" },
  { name: "export-period", steps: [click("#btn-menu"), click("#menu [data-export]"), click("#exportdlg [data-xp='dest:me']")], check: "document.getElementById('exportdlg').open && !!document.querySelector(\"#exportdlg [data-xp^='p:']\")" },
  { name: "ignored", steps: [click("#btn-menu"), click("#menu [data-ignored]")], check: "document.getElementById('ignored').open" },
  { name: "log-open", steps: [click("#log-toggle")], check: "document.getElementById('log-toggle').getAttribute('aria-expanded') === 'true'" },
  { name: "devices-found", steps: [click("#btn-scan")], check: "!document.getElementById('card-new').hidden && document.querySelectorAll('#card-new .nd-row').length === 3" },
  // "Add" on the first row: its analysis never ends (mocked stream), so the row stays in progress next to two idle ones
  { name: "devices-adding", steps: [click("#btn-scan"), click("#card-new [data-add-ip]")],
    check: "!document.getElementById('card-new').hidden && document.querySelectorAll('#card-new .nd-row.nd-run').length === 1 && document.querySelectorAll('#card-new .nd-row.nd-idle').length === 2 && !!document.querySelector('#card-new .nd-run [data-add-cancel]')" },
  { name: "list-view", steps: [click("#btn-menu"), click('#menu [data-view="list"]')], check: "document.getElementById('root').getAttribute('data-view') === 'list' || document.documentElement.getAttribute('data-view') === 'list'" },
];

// ------------------------------------------------------------------ the page side
// Runs before the page's own scripts on every load: mocks of the server, a clean storage, timers that can be frozen.
function initScript(data) {
  return `(function () {
  var DATA = ${JSON.stringify(data)};
  try { localStorage.clear(); sessionStorage.clear(); } catch (e) {}
  // timers: frozen once the state is reached, so nothing changes between the A and the B reading
  var rawST = window.setTimeout.bind(window), rawSI = window.setInterval.bind(window), rawRAF = window.requestAnimationFrame.bind(window);
  window.__cmpFrozen = false;
  window.__cmpRAF = rawRAF;
  // What moved the page, for the waiting and for the error messages. With a phone width the window is born 980 wide (the
  // viewport meta is applied later) and its resize event comes only with the first frame, which can be late: the menus close on
  // resize and on scroll, so the tool clicks only once the page has its width and has been still for a moment.
  var T0 = performance.now();
  window.__cmpEv = ["start " + innerWidth + "x" + innerHeight];
  window.__cmpMoved = T0;
  function note(s, moved) { var now = performance.now(); if (moved) window.__cmpMoved = now; if (window.__cmpEv.length < 40) window.__cmpEv.push(Math.round(now - T0) + "ms " + s); }
  function who(t) { return t === document ? "document" : t.id || String(t.className || t.tagName); }
  window.addEventListener("resize", function () { note("resize " + innerWidth + "x" + innerHeight, true); }, true);
  window.addEventListener("scroll", function (e) { note("scroll " + who(e.target), true); }, true);
  document.addEventListener("click", function (e) { note("click " + who(e.target), false); }, true);
  window.setTimeout = function (f, ms) { var a = [].slice.call(arguments, 2); return rawST(function () { if (!window.__cmpFrozen && typeof f === "function") f.apply(window, a); }, ms); };
  window.setInterval = function (f, ms) { var a = [].slice.call(arguments, 2); return rawSI(function () { if (!window.__cmpFrozen && typeof f === "function") f.apply(window, a); }, ms); };
  window.requestAnimationFrame = function (f) { return rawRAF(function (t) { if (!window.__cmpFrozen) f(t); }); };
  var HOSTS = [["192.168.178.201", "B8:27:EB:3A:91:C2"], ["192.168.178.202", "3C:61:05:4F:20:7D"], ["192.168.178.203", "F0:18:98:5A:11:09"]]
    .map(function (x) { return { ip: x[0], mac: x[1], hostname: "h" + x[0].split(".")[3] }; });
  var INFO = { daily: Array.from({ length: 90 }, function (_, i) { return 200000 + (i % 7) * 50000; }), base: 800000, ratio: 0.3, seal_factor: 1.34, limit: 20 * 1024 * 1024, horizon: 90, flagged: 1 };
  // the evidence of a device sheet (bars, certainty, the pop-up of the (i)), as in tests/ui/check_evidence_ui.js
  var EVIDENCE = {
    name: { value: "Router", certainty: 65, basis: "source", source: "upnp", placeholder: false, rejected: [{ source: "dhcp", value: "esp32-abc", cleaned: null }] },
    brand: { value: "TP-Link", certainty: 45, basis: "found", source: "oui", rejected: [{ kind: "vendor", value: "Espressif", role: "component" }] },
    group: { value: "router", certainty: 83, basis: "scored", reason: null, clues: [{ source: "upnp", points: 10 }], rejected: [{ value: "iot", points: 3, why: "behind" }] }
  };
  function ok(b) { return Promise.resolve(new Response(JSON.stringify(b), { status: 200, headers: { "Content-Type": "application/json" } })); }
  window.fetch = function (input, opts) {
    var url = typeof input === "string" ? input : input.url;
    if (url.indexOf(location.origin) === 0) url = url.slice(location.origin.length);
    if (url === "/api/scan/quick") return ok(HOSTS);
    // the analysis of a device being added: a stream that never ends, so its row keeps turning (nd-run)
    if (url === "/api/scan/deep") return Promise.resolve(new Response(new ReadableStream({ start: function () {} }), { status: 200, headers: { "Content-Type": "text/event-stream" } }));
    if (/^\\/api\\/ha\\/devices\\/[^\\/]+\\/evidence/.test(url)) return ok(EVIDENCE);
    if (url.indexOf("/api/export/info") === 0) return ok(INFO);
    if (url.indexOf("/api/new-devices/ignored") === 0) return ok([]);
    if (url.indexOf("/api/new-devices") === 0) return ok([]);
    if (url.indexOf("/api/ignored") === 0) return ok({ items: [{ id: "i1", ip: "192.168.178.99", mac: null, hostname: "printer" }] });
    var b = {};
    if (url.indexOf("/api/ha/devices") === 0 && url.indexOf("/debug") < 0) b = DATA.devices;
    else if (url.indexOf("/api/ha/summary") === 0) b = DATA.summary;
    else if (url.indexOf("/api/ha/logbook") === 0) b = DATA.logbook;
    else if (url.indexOf("/api/ha/history?") === 0) b = DATA.history_all;
    else if (url.indexOf("/api/ha/history/") === 0) {
      var id = url.split("/")[4].split("?")[0];
      b = Object.assign({ device_id: id }, url.indexOf("hours=168") >= 0 ? DATA.history_7d[id] : DATA.history_all.devices[id]);
    }
    return ok(b);
  };
  window.EventSource = function (url) { var s = this; s.url = url; s.readyState = 1; s.l = {}; rawST(function () { s.onopen && s.onopen({}); }, 5); };
  window.EventSource.prototype.addEventListener = function (n, f) { this.l[n] = f; };
  window.EventSource.prototype.removeEventListener = function () {};
  window.EventSource.prototype.close = function () { this.readyState = 2; };
})();`;
}

// Evaluated in the page: one reading of the computed style of everything under body.
const SNAP_FN = `function (props, pprops) {
  var els = [document.body].concat([].slice.call(document.body.querySelectorAll("*"))).filter(function (e) { return e.tagName !== "SCRIPT" && e.tagName !== "STYLE"; });
  function step(e) {
    if (e.id) return "#" + e.id;
    var s = e.tagName.toLowerCase(), c = typeof e.className === "string" ? e.className.trim().split(/\\s+/).filter(Boolean).slice(0, 2) : [];
    if (c.length) s += "." + c.join(".");
    var p = e.parentElement;
    if (p) { var same = [].filter.call(p.children, function (x) { return x.tagName === e.tagName; }); if (same.length > 1) s += ":" + (same.indexOf(e) + 1); }
    return s;
  }
  function where(e) {
    var parts = [];
    for (var x = e; x && x !== document.documentElement; x = x.parentElement) { parts.unshift(step(x)); if (x.id || parts.length >= 4) break; }
    return parts.join(" > ");
  }
  var r2 = function (n) { return Math.round(n * 100) / 100; };
  var keys = [], rows = [];
  els.forEach(function (e) {
    var cs = getComputedStyle(e), row = {};
    props.forEach(function (p) { row[p] = cs.getPropertyValue(p); });
    var b = e.getBoundingClientRect();
    row["(box)"] = [r2(b.left), r2(b.top), r2(b.width), r2(b.height)].join(" ");
    ["::before", "::after"].forEach(function (ps) {
      var pc = getComputedStyle(e, ps), content = pc.getPropertyValue("content");
      row[ps + " content"] = content;
      if (content !== "none" && content !== "normal") pprops.forEach(function (p) { row[ps + " " + p] = pc.getPropertyValue(p); });
    });
    keys.push(where(e)); rows.push(row);
  });
  // rendered on screen: inside a closed <details> an element still has a box, checkVisibility() knows it is not shown
  var visible = els.filter(function (e) { var b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0 && (!e.checkVisibility || e.checkVisibility({ visibilityProperty: true })); }).length;
  return { keys: keys, rows: rows, visible: visible };
}`;

// ------------------------------------------------------------------ a small DevTools Protocol client
class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.wait = new Map(); this.on = []; }
  static open(url) {
    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url), c = new CDP(ws);
      ws.onopen = () => resolve(c);
      ws.onerror = (e) => reject(new Error("DevTools connection failed: " + (e.message || e.type)));
      ws.onmessage = (m) => {
        const msg = JSON.parse(typeof m.data === "string" ? m.data : Buffer.from(m.data).toString());
        if (msg.id && c.wait.has(msg.id)) { const w = c.wait.get(msg.id); c.wait.delete(msg.id); msg.error ? w.reject(new Error(w.method + ": " + msg.error.message)) : w.resolve(msg.result); }
        else if (msg.method) c.on.forEach((f) => f(msg));
      };
    });
  }
  send(method, params, sessionId) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params: params || {}, sessionId }));
    return new Promise((resolve, reject) => this.wait.set(id, { resolve, reject, method }));
  }
  once(method, sessionId, ms) {
    return new Promise((resolve, reject) => {
      const t = setTimeout(() => { this.on = this.on.filter((f) => f !== h); reject(new Error("timeout waiting for " + method)); }, ms || 15000);
      const h = (msg) => { if (msg.method === method && msg.sessionId === sessionId) { clearTimeout(t); this.on = this.on.filter((f) => f !== h); resolve(msg.params); } };
      this.on.push(h);
    });
  }
  close() { try { this.ws.close(); } catch (e) { /* already closed */ } }
}

function findChrome() {
  const c = [process.env.CHROME, "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe"), "/usr/bin/google-chrome", "/usr/bin/chromium",
    "/usr/bin/chromium-browser", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"].filter(Boolean);
  const hit = c.find((p) => { try { return fs.statSync(p).isFile(); } catch (e) { return false; } });
  if (!hit) throw new Error("Chrome not found: set the CHROME variable");
  return hit;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ main
async function main() {
  const t0 = Date.now();
  const opt = parseArgs(process.argv.slice(2));
  const A = opt.a ? cssFromFile(opt.a) : cssFromRev(opt.base);
  const B = opt.b ? cssFromFile(opt.b) : cssFromWorkingCopy();
  const widths = opt.widths.split(",").map((w) => parseInt(w, 10)).filter((w) => w > 0);
  const themes = opt.themes.split(",").filter((x) => /^(light|dark)$/.test(x));
  const only = opt.only ? opt.only.split(",").map((s) => s.trim()).filter(Boolean) : null;
  const unknown = only ? only.filter((n) => !STATES.some((s) => s.name === n)) : [];
  if (unknown.length) throw new Error("unknown state(s) in --only: " + unknown.join(", ") + " (known: " + STATES.map((s) => s.name).join(", ") + ")");
  const states = only ? STATES.filter((s) => only.includes(s.name)) : STATES;
  if (!widths.length || !themes.length || !states.length) throw new Error("nothing to compare (check --widths, --themes, --only)");
  console.log("A: " + A.label + "  " + A.text.length + " chars" + (A.text === B.text ? "  (identical text to B)" : ""));
  console.log("B: " + B.label + "  " + B.text.length + " chars");

  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "vedetta-csscmp-"));
  let chrome = null, server = null, cdp = null;
  const cleanup = () => {
    if (cdp) cdp.close();
    if (server) server.close();
    if (chrome && chrome.exitCode === null) {
      try { if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(chrome.pid), "/T", "/F"], { stdio: "ignore" }); else chrome.kill("SIGKILL"); } catch (e) { /* gone */ }
    }
    // Chrome may still hold files for a moment after the kill
    for (let i = 0; i < 20; i++) { try { fs.rmSync(tmp, { recursive: true, force: true }); return; } catch (e) { spawnSync(process.execPath, ["-e", "setTimeout(()=>{},150)"]); } }
  };
  process.on("SIGINT", () => { cleanup(); process.exit(2); });
  try {
    // 1. the page, with invented devices
    const out = path.join(tmp, "page");
    const built = spawnSync(process.env.PYTHON || "python", [path.join(ROOT, "tests", "ui", "build_page.py"), out, opt.lang], { cwd: VEDETTA, encoding: "utf8" });
    if (built.status !== 0) throw new Error("build_page.py failed:\n" + built.stdout + built.stderr);
    let html = fs.readFileSync(path.join(out, "page.html"), "utf8");
    const data = JSON.parse(fs.readFileSync(path.join(out, "data.json"), "utf8"));
    // a few variations, for more styles on screen: a flagged device, one never analysed in depth (the badge), one offline
    const D = data.devices.devices;
    if (D[1]) D[1].focus = true;
    if (D[2]) { D[2].scanned_at = null; D[2].deep_empty_at = null; D[2].online = false; }
    // the link to ha.css is replaced by the sheet under test, after the freeze sheet (its layer comes first, see FREEZE_CSS)
    const link = /<link rel="stylesheet" href="[^"]*\/ha\/ha\.css[^"]*">/;
    if (!link.test(html)) throw new Error("the link to ha.css was not found in page.html");
    // A is in the page from the start, so the scripts render (and measure) with it like with the real ha.css
    html = html.replace(link, () => '<style id="__cmp_freeze">' + FREEZE_CSS + '</style><style id="__cmp">' + A.text + "</style>");
    if (/<\/style/i.test(A.text)) throw new Error("sheet A contains </style>: it cannot be put in the page");

    // 2. a local server: the page, and the static files it may ask for
    server = http.createServer((req, res) => {
      const u = new URL(req.url, "http://x");
      if (u.pathname === "/ha") { res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" }); return res.end(html); }
      if (u.pathname.startsWith("/static/")) {
        const f = path.resolve(STATIC, "." + u.pathname.slice(7));
        if (f.startsWith(STATIC) && fs.existsSync(f) && fs.statSync(f).isFile()) { res.writeHead(200); return res.end(fs.readFileSync(f)); }
      }
      res.writeHead(404); res.end();
    });
    await new Promise((r) => server.listen(0, "127.0.0.1", r));
    const pageUrl = "http://127.0.0.1:" + server.address().port + "/ha?lang=" + opt.lang;

    // 3. Chrome headless; port 0 lets Chrome pick a free one and write it in DevToolsActivePort
    const profile = path.join(tmp, "profile");
    fs.mkdirSync(profile);
    chrome = spawn(findChrome(), ["--headless=new", "--remote-debugging-port=0", "--user-data-dir=" + profile, "--window-size=1280,900",
      "--no-first-run", "--no-default-browser-check", "--disable-extensions", "--disable-background-networking", "--disable-sync",
      "--disable-background-timer-throttling", "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows",
      "--force-color-profile=srgb", "--font-render-hinting=none", "about:blank"], { stdio: "ignore" });
    let port = null;
    for (let i = 0; i < 150 && !port; i++) {
      try { port = fs.readFileSync(path.join(profile, "DevToolsActivePort"), "utf8").split("\n")[0].trim(); } catch (e) { await sleep(100); }
    }
    if (!port) throw new Error("Chrome did not start");
    const ver = await (await fetch("http://127.0.0.1:" + port + "/json/version")).json();
    cdp = await CDP.open(ver.webSocketDebuggerUrl);
    const { targetId } = await cdp.send("Target.createTarget", { url: "about:blank" });
    const { sessionId: S } = await cdp.send("Target.attachToTarget", { targetId, flatten: true });
    await cdp.send("Page.enable", {}, S);
    await cdp.send("Runtime.enable", {}, S);
    await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: initScript(data) }, S);
    const pageErrors = [];
    cdp.on.push((m) => { if (m.sessionId === S && m.method === "Runtime.exceptionThrown") pageErrors.push(m.params.exceptionDetails.exception ? m.params.exceptionDetails.exception.description : m.params.exceptionDetails.text); });
    const ev = async (expr, awaitPromise) => {
      const r = await cdp.send("Runtime.evaluate", { expression: expr, awaitPromise: !!awaitPromise, returnByValue: true }, S);
      if (r.exceptionDetails) throw new Error((r.exceptionDetails.exception && r.exceptionDetails.exception.description) || r.exceptionDetails.text);
      return r.result.value;
    };
    const until = async (expr, ms, awaitPromise) => { const end = Date.now() + ms; do { if (await ev(expr, awaitPromise)) return true; await sleep(50); } while (Date.now() < end); return false; };
    const frames = "new Promise(function (r) { window.__cmpRAF(function () { window.__cmpRAF(function () { r(true); }); }); })";
    const snap = () => ev("(" + SNAP_FN + ")(" + JSON.stringify(PROPS) + "," + JSON.stringify(PSEUDO_PROPS) + ")");
    // Settled: two frames have been drawn (so a pending resize has been delivered), the window has the emulated width and
    // nothing has resized or scrolled for 250 ms.
    const settled = (w) => "new Promise(function (r) { window.__cmpRAF(function () { window.__cmpRAF(function () { " +
      "r(innerWidth === " + w + " && performance.now() - window.__cmpMoved >= 250); }); }); })";
    const events = async () => { try { return (await ev("window.__cmpEv")).join(", "); } catch (e) { return "(events not readable)"; } };
    // One attempt at a state, from a fresh page: null when it is there and frozen, otherwise why not.
    const drive = async (st, w) => {
      pageErrors.length = 0;
      const loaded = cdp.once("Page.loadEventFired", S, 20000);
      await cdp.send("Page.navigate", { url: pageUrl }, S);
      await loaded;
      if (!(await until("document.querySelectorAll('.tile').length >= 3 && !!document.getElementById('btn-scan')", 10000))) return "the dashboard did not render (no tiles)";
      if (!(await until(settled(w), 5000, true))) return "the page did not settle at width " + w + " (innerWidth " + (await ev("innerWidth")) + ")";
      for (const s of st.steps) {
        if (s.click) {
          const sel = JSON.stringify(s.click);
          if (!(await until("!!document.querySelector(" + sel + ")", 5000))) return "step: " + s.click + " never appeared";
          await ev("document.querySelector(" + sel + ").click(); " + frames, true);
          await sleep(150);
        } else if (!(await until(s.wait, 5000))) return "step: never true: " + s.wait;
      }
      if (!(await until(st.check, 5000))) return "not reached";
      await sleep(300);
      // the animations made by script are taken to their end, then the page stops moving
      await ev("document.getAnimations().forEach(function (a) { try { a.finish(); } catch (e) { a.cancel(); } }); true");
      await sleep(100);
      await ev("window.__cmpFrozen = true; " + frames, true);
      if (!(await ev(st.check))) return "reached, then lost before the reading";
      return null;
    };
    const retries = [];
    await cdp.send("Page.bringToFront", {}, S);

    // 4. every theme, width and state
    const results = [];
    for (const theme of themes) {
      await cdp.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: theme }, { name: "prefers-reduced-motion", value: "no-preference" }] }, S);
      for (const w of widths) {
        const narrow = w < 700;                       // a phone: touch, so the (pointer: coarse) rules are read as well
        await cdp.send("Emulation.setDeviceMetricsOverride", { width: w, height: narrow ? 844 : 900, deviceScaleFactor: 1, mobile: narrow }, S);
        await cdp.send("Emulation.setTouchEmulationEnabled", { enabled: narrow, maxTouchPoints: narrow ? 5 : 1 }, S);
        for (const st of states) {
          const tag = theme + " " + w + " " + st.name;
          // a second attempt from a fresh page if the first one did not get there; it is reported, and two misses stop the check
          let why = await drive(st, w);
          if (why) {
            retries.push(tag + ": " + why + " [" + (await events()) + "]");
            process.stdout.write("r");
            why = await drive(st, w);
            if (why) throw new Error(tag + ": the state was not reached in two attempts: " + why + "\n  check: " + st.check + "\n  page events: " + (await events()));
          }
          const a = await snap();
          await ev("document.getElementById('__cmp').textContent = " + JSON.stringify(B.text) + "; " + frames, true);
          const b = await snap();
          const diffs = [];
          if (a.keys.length !== b.keys.length || a.keys.some((k, i) => k !== b.keys[i])) diffs.push({ el: "(page)", prop: "elements", a: a.keys.length, b: b.keys.length });
          else a.rows.forEach((ra, i) => {
            const rb = b.rows[i];
            new Set(Object.keys(ra).concat(Object.keys(rb))).forEach((p) => { if (ra[p] !== rb[p]) diffs.push({ el: a.keys[i], prop: p, a: ra[p] === undefined ? "(none)" : ra[p], b: rb[p] === undefined ? "(none)" : rb[p] }); });
          });
          results.push({ theme, width: w, state: st.name, elements: a.keys.length, visible: a.visible, diffs, pageErrors: pageErrors.slice() });
          process.stdout.write(".");
        }
      }
    }
    process.stdout.write("\n");
    // every theme x width x state must have been read: a reading that is missing is a failed check, never a pass
    const expected = themes.length * widths.length * states.length;
    if (results.length !== expected) throw new Error("only " + results.length + " of " + expected + " readings were made");

    // 5. the summary: one row per state (elements read / shown on screen, then ok or the number of differences), then the
    // differences themselves, the same one found in several states, themes or widths written once
    const total = results.reduce((n, r) => n + r.diffs.length, 0);
    const cols = [];
    results.forEach((r) => { const c = r.theme + " " + r.width; if (!cols.includes(c)) cols.push(c); });
    const lines = ["state".padEnd(15) + cols.map((c) => c.padEnd(18)).join("") + "(elements/visible, ok or differences!, E = page error)"];
    for (const st of states) {
      lines.push(st.name.padEnd(15) + cols.map((c) => {
        const r = results.find((x) => x.state === st.name && x.theme + " " + x.width === c);
        return (r.elements + "/" + r.visible + " " + (r.diffs.length ? r.diffs.length + "!" : "ok") + (r.pageErrors.length ? " E" : "")).padEnd(18);
      }).join(""));
    }
    const same = new Map();
    for (const r of results) {
      for (const d of r.diffs) {
        const k = [d.el, d.prop, d.a, d.b].join("\u0000");
        if (!same.has(k)) same.set(k, { d, at: [] });
        same.get(k).at.push(r.state + " " + r.theme + " " + r.width);
      }
    }
    const cut = (v, n) => { v = String(v); return v.length > n ? v.slice(0, n - 3) + "..." : v; };
    let shown = 0;
    for (const { d, at } of same.values()) {
      if (lines.length >= 48) break;
      lines.push("  " + cut(d.el, 60) + "  " + d.prop + ": " + cut(d.a, 40) + " -> " + cut(d.b, 40) + "  [" + at[0] + (at.length > 1 ? " +" + (at.length - 1) + " more" : "") + "]");
      shown++;
    }
    if (shown < same.size) lines.push("  ... " + (same.size - shown) + " more distinct differences" + (opt.json ? ", see " + opt.json : ", --json gives the full list"));
    console.log(lines.join("\n"));
    const errs = results.filter((r) => r.pageErrors.length);
    if (errs.length) console.log("page errors (first): " + errs[0].pageErrors[0].split("\n")[0]);
    if (retries.length) console.log("states reached only at the second attempt (" + retries.length + "):\n" + retries.map((r) => "  " + r).join("\n"));
    console.log((total ? total + " differences" : "no differences") + " in " + results.length + " readings" + (retries.length ? ", " + retries.length + " retried" : "") +
      "; " + ((Date.now() - t0) / 1000).toFixed(1) + " s");
    if (opt.json) fs.writeFileSync(opt.json, JSON.stringify({ a: A.label, b: B.label, lang: opt.lang, differences: total, retries, results }, null, 1));
    return total ? 1 : 0;
  } finally {
    cleanup();
  }
}

// Whatever stops the check (a state not reached, Chrome, the page) is exit 2 with the reason: never a silent pass.
main().then((code) => process.exit(code), (err) => {
  console.error("\ncss_compare: CHECK NOT DONE (exit 2): " + (err && err.message ? err.message : err));
  process.exit(2);
});
