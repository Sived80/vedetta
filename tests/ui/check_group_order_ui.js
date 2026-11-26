// The groups of the page (1.0.4): the smart home kinds have their own groups (a device of type "climate" gets the heading of Climate), and the
// person orders the groups from the menu («Order of groups»): one row per group with up and down, up off on the first row and down off on the
// last, «Reset» back to the default order. The order is the setting group_order of the server (the same on every device): the page draws the
// groups in the order the server says and posts every change.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_group_order_ui.js [it|en]
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
const LOCALE = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "locales", lang, "ha.json"), "utf8"));
const DEFAULT = ["router", "server", "pc", "phone", "media", "audio", "iot", "climate", "appliance", "energy", "security", "cover", "water", "printer", "camera", "generic"];

// one more device, of the new group "climate" (invented values)
const base = data.devices.devices[0];
data.devices.devices.push(Object.assign({}, base, { id: "d9", name: "Caldaia", ip: "192.0.2.9", mac: "02:00:00:00:00:09", type: "climate", icon: "water-boiler", brand: null, vendor: null, logo: null }));
const SERVER = { alerts: true, poll_interval: 30, miss_limit: 3, phone_hold_ha: true, group_order: ["climate", "phone"].concat(DEFAULT.filter((g) => g !== "climate" && g !== "phone")) };

const posted = [];
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
    win.fetch = (url, opts) => {
      const post = opts && opts.method === "POST" && url.startsWith("/api/settings");
      if (post) {
        const body = JSON.parse(opts.body);
        posted.push(body);
        if (Array.isArray(body.group_order)) body.group_order = body.group_order.length ? body.group_order : [];
        Object.assign(SERVER, body);
      }
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      let b = {};
      if (url.startsWith("/api/settings")) b = JSON.parse(JSON.stringify(SERVER));
      else if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
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
const sections = () => [...doc.querySelectorAll("#groups section.group")].filter((s) => s.isConnected).map((s) => s.dataset.type);
const rows = () => [...doc.querySelectorAll("#orderdlg [data-go-row]")];
const order = () => rows().map((r) => r.getAttribute("data-go-row"));

(async () => {
  await wait(900);
  const climate = doc.querySelector('#groups section.group[data-type="climate"]');
  check(!!climate && climate.querySelector(".hd-title").textContent === LOCALE["js.ha.type.climate"], "a device of type climate has its own group, with its name: " + (climate && climate.querySelector(".hd-title").textContent));
  check(sections().join() === "climate,phone,router,iot", "the groups follow the order of the server: " + sections().join());

  doc.getElementById("btn-menu").click();
  await wait(80);
  const entry = doc.querySelector("#menu [data-grouporder]");
  check(!!entry && entry.textContent.indexOf(LOCALE["js.ha.order.menu"]) >= 0, "the menu has the entry «" + LOCALE["js.ha.order.menu"] + "»");
  if (!entry) { console.log("FAILED: " + (failed + 1)); process.exit(1); }
  entry.click();
  await wait(60);
  const dlg = doc.getElementById("orderdlg");
  check(dlg && dlg.hasAttribute("open") && doc.getElementById("menu").hidden, "the entry closes the menu and opens the panel");
  check(order().join() === SERVER.group_order.join() && rows().length === 16, "the panel lists the 16 groups in the saved order");
  check(rows().every((r) => r.textContent.indexOf(LOCALE["js.ha.type." + r.getAttribute("data-go-row")]) >= 0), "each row has the name of its group");
  const up = (r) => r.querySelector("[data-go-up]"), down = (r) => r.querySelector("[data-go-down]");
  check(rows().every((r) => up(r).tagName === "BUTTON" && down(r).tagName === "BUTTON" && up(r).getAttribute("aria-label") && down(r).getAttribute("aria-label")), "up and down are buttons with a name for the screen readers");
  check(up(rows()[0]).disabled && !down(rows()[0]).disabled, "up is off on the first row");
  check(down(rows()[15]).disabled && !up(rows()[15]).disabled, "down is off on the last row");
  check(rows().slice(1, 15).every((r) => !up(r).disabled && !down(r).disabled), "both are on in the rows between");

  down(rows()[0]).click();          // climate goes after phone
  await wait(60);
  check(order().slice(0, 3).join() === "phone,climate,router", "down moves the group one place: " + order().slice(0, 3).join());
  const last = posted[posted.length - 1];
  check(posted.length === 1 && Array.isArray(last.group_order) && last.group_order.join() === order().join() && Object.keys(last).length === 1, "the new order is posted to the server, whole: " + JSON.stringify(last));
  check(doc.activeElement && doc.activeElement.closest("[data-go-row]") && doc.activeElement.closest("[data-go-row]").getAttribute("data-go-row") === "climate", "the focus follows the moved group");
  await wait(60);
  check(sections().join() === "phone,climate,router,iot", "the page draws the groups in the new order at once: " + sections().join());

  up(rows()[2]).click();            // router goes before climate
  await wait(60);
  check(order().slice(0, 3).join() === "phone,router,climate" && posted.length === 2, "up moves the group one place: " + order().slice(0, 3).join());

  const reset = dlg.querySelector("[data-go-reset]");
  check(!!reset && reset.textContent.indexOf(LOCALE["js.ha.order.reset"]) >= 0, "the panel has «" + LOCALE["js.ha.order.reset"] + "»");
  reset.click();
  await wait(60);
  check(order().join() === DEFAULT.join(), "reset goes back to the default order");
  check(posted.length === 3 && Array.isArray(posted[2].group_order) && posted[2].group_order.length === 0, "and posts [] (the default order): " + JSON.stringify(posted[2]));
  await wait(60);
  check(sections().join() === "router,phone,iot,climate", "the page goes back to the default order: " + sections().join());

  dlg.querySelector("[data-go-close]").click();
  await wait(30);
  check(!dlg.hasAttribute("open"), "the panel closes");
  check(errors.length === 0, "no error in the page: " + errors.join(" | "));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
