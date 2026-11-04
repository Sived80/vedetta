// Text that comes from the network is shown, never run: a device that announces itself as "<img src=x onerror=...>" (in its name,
// brand, model, the log, the clues of its sheet) must appear as those characters on the page, and no element or script of its own is
// created. Needs jsdom (npm install in this folder); without it the check is skipped.
//   from the vedetta/ folder:  node ../tests/ui/check_untrusted_text_ui.js [it|en]
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

// What a hostile device could announce over DHCP, mDNS or UPnP: each one sets a flag if it ever runs.
const BAD = ['<img src=x onerror="window.__ran=1">', '"><svg onload="window.__ran=2">', "<script>window.__ran=3</script>", "' onmouseover='window.__ran=4"];
data.devices.devices.forEach((d, i) => {
  d.name = BAD[i % BAD.length] + " " + i;
  d.brand = BAD[(i + 1) % BAD.length];
  d.model = BAD[(i + 2) % BAD.length];
  d.latency_ms = 12;
});
data.logbook.events = data.devices.devices.slice(0, 3).map((d, i) => ({ ts: Date.now() / 1000 - 60 * i, kind: "online", device_id: d.id, name: BAD[i % BAD.length], ip: d.ip, type: "iot" }));      // the log names the devices too
const EV = {
  name: { value: BAD[0], certainty: 65, basis: "source", source: "dhcp", placeholder: false, rejected: [{ source: "mdns", value: BAD[1], cleaned: null }] },
  brand: { value: BAD[2], certainty: 45, basis: "found", source: "oui", rejected: [{ kind: "vendor", value: BAD[3], role: "component" }] },
  group: { value: "iot", certainty: 50, basis: "scored", reason: null, clues: [{ source: BAD[0], points: 4 }], rejected: [] },
};

const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
vc.on("error", (e) => errors.push("console.error: " + e));
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
  beforeParse(win) {
    win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); this.dispatchEvent(new win.Event("close")); };
    win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
    win.fetch = (url) => {
      let body = {};
      if (url.includes("/evidence")) body = EV;
      else if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) body = data.devices;
      else if (url.startsWith("/api/ha/summary")) body = data.summary;
      else if (url.startsWith("/api/ha/logbook")) body = data.logbook;
      else if (url.startsWith("/api/ha/history?")) body = data.history_all;
      else if (url.startsWith("/api/ha/history/")) { const id = url.split("/")[4].split("?")[0]; body = Object.assign({ device_id: id }, url.includes("hours=168") ? data.history_7d[id] : data.history_all.devices[id]); }
      return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(body) });
    };
    win.EventSource = class {
      constructor(url) { this.url = url; this.l = {}; setTimeout(() => this.onopen && this.onopen(), 5); }
      addEventListener(n, f) { this.l[n] = f; } close() {}
    };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const win = dom.window, doc = win.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const q = (s) => doc.querySelector(s), qa = (s) => Array.from(doc.querySelectorAll(s));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }
// An element made by the text: any img with src "x", any svg or element with an on... attribute that holds "__ran".
const injected = () => qa("img[src='x'], [onerror], [onload], [onmouseover]").filter((el) => /__ran/.test(el.outerHTML)).length + qa("script").filter((s) => /__ran/.test(s.textContent)).length;

(async () => {
  await wait(1200);
  const first = data.devices.devices[0];
  check(doc.body.textContent.includes(first.name), "the name of a device is shown as the characters it holds");
  check(injected() === 0, "the list builds no element from the text of the devices");
  const tile = q('.tile[data-id="' + first.id + '"]');
  if (tile) { tile.click(); await wait(600); }
  check(!!tile, "the sheet of the device opens");
  qa(".ev-i, [data-ev]").slice(0, 3).forEach((b) => b.click());      // the (i) of name, brand and type: the clues and what was set aside
  await wait(300);
  check(injected() === 0, "the sheet and its clues build no element from the text of the device");
  for (const el of qa("*")) { el.dispatchEvent(new win.Event("mouseover", { bubbles: true })); }
  await wait(50);
  check(win.__ran === undefined, "nothing the devices announced has run (" + win.__ran + ")");
  check(errors.length === 0, "no error on the page" + (errors.length ? ": " + errors[0] : ""));
  console.log(failed ? "FALLITI: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
