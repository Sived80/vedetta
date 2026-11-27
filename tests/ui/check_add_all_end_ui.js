// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// R8 (two public reports: "Add all" left a spinner turning, devices "could not be added"): "Add all" always ends, and says how many were added and,
// row by row, which were not and why. The server tells what it left out (POST /api/devices/add -> skipped); a lost deep-search stream or an add that
// fails ends the card too, with "Close", never a ring that turns for ever. Invented addresses (192.0.2.x) and MACs (02:00:00:...).
// Needs jsdom (see check_evidence_ui.js).   node tests/ui/check_add_all_end_ui.js [it|en]
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

const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
vc.on("error", (e) => errors.push("console.error: " + e));
const calls = [];
const HOSTS = [];
const host = (n) => ({ ip: "192.0.2." + n, mac: "02:00:00:00:00:" + String(n).padStart(2, "0"), hostname: "" });
let addReply = null;                                  // (body) -> a reply of POST /api/devices/add: {status, body} or "hang"
let fast = false;                                     // true: the page's long waits (the 25 s of a request, the 90 s of a silent stream) last a moment
const streams = [];
function makeStream(ips, signal) {
  const q = [], waiters = []; let closed = false, aborted = false;
  const enc = new (require("util").TextEncoder)();
  const s = { ips, push(obj) { const v = enc.encode("data: " + JSON.stringify(obj) + "\n"); const w = waiters.shift(); if (w) w.resolve({ done: false, value: v }); else q.push(v); },
    progress(ip) { s.push({ type: "progress", result: { ip, suggested_name: "Dev " + ip, adapter: "generic" } }); },
    finish() { ips.forEach((ip) => s.progress(ip)); s.push({ type: "complete", results: ips.map((ip) => ({ ip, adapter: "generic" })) }); closed = true; waiters.splice(0).forEach((w) => w.resolve({ done: true })); },
    aborted: () => aborted };
  if (signal) signal.addEventListener("abort", () => { aborted = true; waiters.splice(0).forEach((w) => w.reject(new Error("aborted"))); });
  s.reader = { read() { if (aborted) return Promise.reject(new Error("aborted")); if (q.length) return Promise.resolve({ done: false, value: q.shift() }); if (closed) return Promise.resolve({ done: true }); return new Promise((resolve, reject) => waiters.push({ resolve, reject })); } };
  return s;
}
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
  beforeParse(win) {
    win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
    win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
    win.HTMLElement.prototype.scrollIntoView = function () {};
    win.TextDecoder = require("util").TextDecoder;
    const later = win.setTimeout.bind(win);
    win.setTimeout = (f, ms, ...a) => later(f, fast && (ms === 25000 || ms === 90000) ? 150 : ms, ...a);
    win.fetch = (url, opts) => {
      const method = (opts && opts.method) || "GET", body = opts && opts.body ? JSON.parse(opts.body) : null;
      calls.push({ url, method, body });
      const reply = (status, b) => Promise.resolve({ ok: status < 400, status, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      const ok = (b) => reply(200, b);
      if (url === "/api/scan/quick") return ok(HOSTS);
      if (url === "/api/scan/deep") { const s = makeStream(body.ips, opts.signal); streams.push(s); return Promise.resolve({ ok: true, status: 200, body: { getReader: () => s.reader } }); }
      if (url === "/api/devices/add") {
        const r = addReply ? addReply(body) : { status: 200, body: { added: body.devices.map((d) => ({ ip: d.ip })), skipped: [] } };
        if (r === "hang") return new Promise((resolve, reject) => { if (opts.signal) opts.signal.addEventListener("abort", () => reject(new Error("aborted"))); });
        return reply(r.status, r.body);
      }
      if (url.startsWith("/api/new-devices")) return ok([]);
      if (url === "/api/scan/cancel") return ok({ cancelled: body.ips.length });
      let b = {};
      if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
      else if (url.startsWith("/api/ha/summary")) b = data.summary;
      else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
      else if (url.startsWith("/api/ha/history?")) b = data.history_all;
      else if (url.startsWith("/api/ha/history/")) { const id = url.split("/")[4].split("?")[0]; b = Object.assign({ device_id: id }, url.includes("hours=168") ? data.history_7d[id] : data.history_all.devices[id]); }
      return ok(b);
    };
    win.EventSource = class {
      constructor() { this.l = {}; setTimeout(() => this.onopen && this.onopen(), 5); }
      addEventListener(n, f) { this.l[n] = f; } close() {}
    };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const win = dom.window, doc = win.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const q = (s) => doc.querySelector(s), qa = (s) => Array.from(doc.querySelectorAll(s));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }
const click = async (sel) => { const el = typeof sel === "string" ? q(sel) : sel; if (!el) throw new Error("missing " + sel); el.click(); await wait(30); };
const rows = () => qa("#card-new .nd-row");
const rowOf = (n) => q('#card-new .nd-row[data-ip="192.0.2.' + n + '"]');
const stateOf = (n) => rowOf(n) && Array.from(rowOf(n).classList).filter((c) => /^nd-(idle|run|save|done|skip)$/.test(c))[0];
const subOf = (n) => rowOf(n) && rowOf(n).querySelector(".nd-sub").textContent.trim();
const title = () => q("#card-new .ch-title").textContent.trim();
const sub = () => q("#card-new .ch-sub").textContent.trim();
const turning = () => !!q("#card-new .nd-row .sp, #card-new .nd-mini");
const closeBtn = () => q("#card-new [data-add-close]");
// The text of a key as the page shows it (the plural category of the language, then the plain key), {n} filled in.
const text = (key, n) => {
  const form = n === undefined ? key : (TEXT[key + "_" + new Intl.PluralRules(lang).select(n)] !== undefined ? key + "_" + new Intl.PluralRules(lang).select(n) : key);
  return String(TEXT[form]).replace("{n}", n);
};
async function scanWith(...ns) {
  HOSTS.length = 0;
  ns.forEach((n) => HOSTS.push(host(n)));
  await click("#btn-scan");
  await wait(120);
}

(async () => {
  await wait(800);

  // --- 1. the server adds two and leaves two out: two green rows, two rows that say why, the title counts, "Close" ends it
  await scanWith(11, 12, 13, 14);
  check(rows().length === 4, "four devices found");
  addReply = (body) => ({ status: 200, body: { added: [{ ip: "192.0.2.11" }, { ip: "192.0.2.12" }],
    skipped: [{ ip: "192.0.2.13", reason: "exists" }, { ip: "192.0.2.14", reason: "off_limits" }] } });
  await click("#card-new [data-add-all]");
  streams[streams.length - 1].finish();
  await wait(250);
  check(stateOf(11) === "nd-done" && stateOf(12) === "nd-done", "the two the server added are green");
  check(stateOf(13) === "nd-skip" && stateOf(14) === "nd-skip", "the two it left out are not shown as added");
  check(subOf(13) === text("js.ha.new.skip_exists") && subOf(14) === text("js.ha.new.skip_off_limits"), "each row left out says why: " + subOf(13) + " / " + subOf(14));
  check(title() === text("js.ha.new.added_title", 2), "the title counts only the ones added: " + title());
  check(sub() === text("js.ha.new.not_added", 2), "and the line under it says how many were not added: " + sub());
  check(!turning() && !!closeBtn(), "nothing turns, «Close» ends it");
  await click(closeBtn());
  check(q("#card-new").hidden, "«Close» closes the card");

  // --- 2. nothing added at all (every device already a card): the card still ends, saying so
  await scanWith(21, 22);
  addReply = (body) => ({ status: 200, body: { added: [], skipped: body.devices.map((d) => ({ ip: d.ip, reason: "exists" })) } });
  await click("#card-new [data-add-all]");
  streams[streams.length - 1].finish();
  await wait(250);
  check(stateOf(21) === "nd-skip" && stateOf(22) === "nd-skip" && subOf(21) === text("js.ha.new.skip_exists"), "both rows say they are already cards");
  check(title() === text("js.ha.new.none_added") && sub() === text("js.ha.new.not_added", 2), "the title says nothing was added: " + title() + " / " + sub());
  check(!turning() && !!closeBtn(), "and «Close» ends it");
  await click(closeBtn());

  // --- 3. the deep-search stream goes silent (a proxy dropped it): the page stops waiting, stops the searches on the server, adds what it has
  addReply = null;
  fast = true;
  await scanWith(31, 32);
  await click("#card-new [data-add-all]");
  const s3 = streams[streams.length - 1];
  s3.progress("192.0.2.31");
  await wait(700);
  check(s3.aborted(), "the silent stream is given up");
  check(calls.some((c) => c.url === "/api/scan/cancel" && c.body.ips.join() === "192.0.2.32"), "the search still running is stopped on the server");
  const add3 = calls.filter((c) => c.url === "/api/devices/add").pop();
  check(!!add3 && add3.body.devices.map((d) => d.ip).join() === "192.0.2.31,192.0.2.32", "both are added, the second with what is known");
  check(stateOf(31) === "nd-done" && stateOf(32) === "nd-done" && !turning() && !!closeBtn(), "the add ends: two green rows and «Close»");
  await click(closeBtn());

  // --- 4. the add fails (the server answers an error): the rows say it, the card ends
  addReply = () => ({ status: 500, body: { detail: "Salvataggio non riuscito" } });
  await scanWith(41, 42);
  await click("#card-new [data-add-all]");
  streams[streams.length - 1].finish();
  await wait(250);
  check(stateOf(41) === "nd-skip" && stateOf(42) === "nd-skip" && subOf(41) === text("js.ha.new.skip_error"), "a failed add: the rows say it did not answer");
  check(title() === text("js.ha.new.none_added") && !turning() && !!closeBtn(), "and the card ends with «Close»");
  await click(closeBtn());

  // --- 5. the add never answers: after the page's limit the card ends the same way
  addReply = () => "hang";
  await scanWith(51, 52);
  await click("#card-new [data-add-all]");
  streams[streams.length - 1].finish();
  await wait(60);
  const c5 = q('#card-new [data-add-cancel="192.0.2.51"]');
  check(!!c5 && c5.disabled, "while the add is sent the row's «Cancel» is off (the save cannot be undone any more)");
  await wait(600);
  check(stateOf(51) === "nd-skip" && stateOf(52) === "nd-skip" && !turning() && !!closeBtn(), "an add with no answer ends too, with the rows saying it");
  await click(closeBtn());
  fast = false;
  addReply = null;

  if (errors.length) console.log(errors.join(String.fromCharCode(10)));
  check(errors.length === 0, "no error in the page");
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
