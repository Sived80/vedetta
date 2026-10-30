// The panel "Networks seen by Home Assistant": opens from the menu, the switch, the first reading, the list by network, the ticks, "Adopt", the closing, and the card of an adopted device.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_ha_networks_ui.js [it|en]
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
const calls = [];
const sources = [];
// what the server says: two clients on one network, one on another, one without an address
const CLIENTS = [
  { mac: "02:00:5e:10:00:21", ip: "198.51.100.21", host: "cam-front", name: "Front camera", online: true, net: "198.51.100.0/24", same_net: false, type: "iot", id: "ha-02005e100021" },
  { mac: "02:00:5e:10:00:31", ip: "198.51.100.31", host: "plug-a", name: null, online: false, net: "198.51.100.0/24", same_net: false, type: "iot", id: "ha-02005e100031" },
  { mac: "02:00:5e:20:00:09", ip: "192.168.40.9", host: "sensor-b", name: null, online: true, net: "192.168.40.0/24", same_net: false, type: "iot", id: "ha-02005e200009" },
  { mac: "02:00:5e:10:00:71", ip: null, host: "thermostat", name: null, online: null, net: null, same_net: false, type: "generic", id: "ha-02005e100071" },
];
const server = { enabled: false, available: true, read_at: null, error: null, adopted: 0, candidates: [] };
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
  beforeParse(win) {
    win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
    win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
    win.HTMLElement.prototype.scrollIntoView = function () {};
    win.fetch = (url, opts) => {
      const method = (opts && opts.method) || "GET", body = opts && opts.body ? JSON.parse(opts.body) : null;
      const full = url;
      url = url.startsWith("/api/ha/networks") ? url.split("?")[0] : url;      // the page adds ?lang= to its requests
      calls.push({ url, method, body });
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      if (url === "/api/ha/networks/enabled") { server.enabled = body.enabled; return ok(server); }
      if (url === "/api/ha/networks/read") { server.read_at = 1700000000; server.candidates = CLIENTS.slice(); return ok(server); }
      if (url === "/api/ha/networks/adopt") {
        server.candidates = server.candidates.filter((c) => !body.macs.includes(c.mac)); server.adopted += body.macs.length;
        return ok(Object.assign({ done: body.macs.length }, server));
      }
      if (url === "/api/ha/networks") return ok(server);
      if (url.startsWith("/api/new-devices")) return ok([]);
      let b = {};
      if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
      else if (url.startsWith("/api/ha/summary")) b = data.summary;
      else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
      else if (url.startsWith("/api/ha/history?")) b = data.history_all;
      else if (url.startsWith("/api/ha/history/")) { const id = url.split("/")[4].split("?")[0]; b = Object.assign({ device_id: id }, data.history_all.devices[id] || {}); }
      return ok(b);
    };
    win.EventSource = class {
      constructor() { this.l = {}; sources.push(this); setTimeout(() => this.onopen && this.onopen(), 5); }
      addEventListener(n, f) { this.l[n] = f; } close() {}
      emit(n, obj) { if (this.l[n]) this.l[n]({ data: JSON.stringify(obj) }); }
    };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const win = dom.window, doc = win.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const q = (s) => doc.querySelector(s), qa = (s) => Array.from(doc.querySelectorAll(s));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }
const click = async (sel) => { const el = typeof sel === "string" ? q(sel) : sel; if (!el) throw new Error("manca " + sel); el.click(); await wait(40); };

(async () => {
  await wait(800);
  check(!!q("#card-nets") && q("#card-nets").hidden, "the panel exists and is closed at the start");
  check(q("#card-nets").parentElement === q("#card-network .card-content"), "it sits inside the Network card");
  await click("#btn-menu");
  const entry = q("[data-nets]");
  check(!!entry && !entry.querySelector(".menu-count"), "the menu has the entry, with no number while the function is off");
  await click(entry);
  await wait(60);
  check(!q("#card-nets").hidden && !!q("#nets-switch") && q("#nets-switch").getAttribute("aria-checked") === "false", "the entry opens the panel with the switch off");
  check(qa("#card-nets .rv-note li").length === 4 && !q("#nets-read"), "the four rules of privacy are written, there is no reading button while it is off");
  await click("#nets-switch");
  await wait(120);
  check(calls.some((c) => c.url === "/api/ha/networks/enabled" && c.body.enabled === true) && calls.some((c) => c.url === "/api/ha/networks/read"), "turning it on asks the server, and reads for the first time");
  const nets = qa("#card-nets .rv-net b").map((b) => b.textContent);
  check(nets.length === 3 && nets[0] === "198.51.100.0/24" && nets[1] === "192.168.40.0/24", "three groups: the networks in the order of the server, the clients without an address last");
  check(qa("#card-nets .rv-row").length === 4 && qa("#card-nets .rv-row")[0].textContent.includes("Front camera"), "four rows, the first with the name Home Assistant shows");
  check(q("#nets-adopt").disabled, "'Adopt' is off until something is ticked");
  await click("[data-nets-all='198.51.100.0/24']");
  check(qa("#card-nets input:checked").length === 2 && !q("#nets-adopt").disabled, "'Select all' of a network ticks its clients and turns 'Adopt' on");
  await click(q("#card-nets input[data-nets-m='02:00:5e:20:00:09']"));
  check(qa("#card-nets input:checked").length === 3, "a single client can be ticked too");
  await click("#nets-adopt");
  await wait(150);
  const adopt = calls.filter((c) => c.url === "/api/ha/networks/adopt")[0];
  check(adopt && adopt.body.macs.length === 3, "'Adopt' sends the three MACs");
  await wait(1700);
  check(q("#card-nets").hidden, "the panel closes by itself after the adoption");
  await click("#btn-menu");
  const count = q("[data-nets] .menu-count");
  check(!!count && count.textContent.trim() === "1", "the menu says how many clients are still to adopt");
  await click("[data-nets]");
  await wait(60);
  check(!q("#card-nets").hidden && qa("#card-nets .rv-row").length === 1, "the panel opens again from the menu, with what is left");
  sources[sources.length - 1].emit("passive", { type: "passive" });
  await wait(400);
  check(calls.filter((c) => c.url.startsWith("/api/ha/devices")).length >= 2, "a passive event makes the page read the devices again");
  check(errors.length === 0, "no error in the page" + (errors.length ? ": " + errors[0] : ""));
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.log("FALLITO: " + (e && e.stack || e)); process.exit(1); });
