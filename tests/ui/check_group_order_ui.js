// The order of the groups (1.0.4): the person orders the ten groups from the menu («Order of groups»). The window lists only the groups that
// have devices, one row each with «to top», up and down (to top and up off on the first row, down off on the last); the empty groups keep their
// place in the saved order; «Reset» goes back to the default order. The order is the setting group_order of the server (the same on every
// device): the page draws the groups in the order the server says, without the names it does not know (a "climate" saved by the debug build
// with 16 groups), and posts every change, whole.
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
const DEFAULT = ["router", "server", "pc", "phone", "media", "audio", "iot", "printer", "camera", "generic"];

// one more device, a camera (invented values); the order saved by the debug build with 16 groups still names "climate": dropped silently
const base = data.devices.devices[0];
data.devices.devices.push(Object.assign({}, base, { id: "d9", name: "Telecamera", ip: "192.0.2.9", mac: "02:00:00:00:00:09", type: "camera", icon: "cctv", brand: null, vendor: null, logo: null }));
const SERVER = { alerts: true, poll_interval: 30, miss_limit: 3, phone_hold_ha: true, group_order: ["climate", "phone", "server", "camera", "router", "pc", "media", "audio", "iot", "printer", "generic"] };
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
  check(!doc.querySelector('#groups section.group[data-type="climate"]'), "no group climate on the page");
  check(sections().join() === "phone,camera,router,iot", "the groups follow the order of the server, the unknown name left out: " + sections().join());

  doc.getElementById("btn-menu").click();
  await wait(80);
  const entry = doc.querySelector("#menu [data-grouporder]");
  check(!!entry && entry.textContent.indexOf(LOCALE["js.ha.order.menu"]) >= 0, "the menu has the entry «" + LOCALE["js.ha.order.menu"] + "»");
  if (!entry) { console.log("FAILED: " + (failed + 1)); process.exit(1); }
  entry.click();
  await wait(60);
  const dlg = doc.getElementById("orderdlg");
  check(dlg && dlg.hasAttribute("open") && doc.getElementById("menu").hidden, "the entry closes the menu and opens the panel");
  check(order().join() === "phone,camera,router,iot", "the panel lists only the groups with devices, in the saved order: " + order().join());
  check(rows().every((r) => r.textContent.indexOf(LOCALE["js.ha.type." + r.getAttribute("data-go-row")]) >= 0), "each row has the name of its group");
  const up = (r) => r.querySelector("[data-go-up]"), down = (r) => r.querySelector("[data-go-down]"), top = (r) => r.querySelector("[data-go-top]");
  check(rows().every((r) => [up(r), down(r), top(r)].every((b) => b && b.tagName === "BUTTON" && b.getAttribute("aria-label"))), "to top, up and down are buttons with a name for the screen readers");
  check(top(rows()[0]).getAttribute("aria-label") === LOCALE["js.ha.order.top"].replace("{name}", LOCALE["js.ha.type.phone"]), "«to top» says the group: " + top(rows()[0]).getAttribute("aria-label"));
  check(up(rows()[0]).disabled && top(rows()[0]).disabled && !down(rows()[0]).disabled, "to top and up are off on the first row");
  check(down(rows()[3]).disabled && !up(rows()[3]).disabled && !top(rows()[3]).disabled, "down is off on the last row");

  down(rows()[0]).click();          // phone goes after camera
  await wait(60);
  check(order().join() === "camera,phone,router,iot", "down swaps with the next group shown: " + order().join());
  let last = posted[posted.length - 1];
  check(posted.length === 1 && Array.isArray(last.group_order) && Object.keys(last).length === 1 &&
    last.group_order.join() === "camera,server,phone,router,pc,media,audio,iot,printer,generic", "the whole order is posted, the empty groups in their place: " + JSON.stringify(last));
  check(doc.activeElement && doc.activeElement.closest("[data-go-row]") && doc.activeElement.closest("[data-go-row]").getAttribute("data-go-row") === "phone", "the focus follows the moved group");
  await wait(60);
  check(sections().join() === "camera,phone,router,iot", "the page draws the groups in the new order at once: " + sections().join());

  top(rows()[3]).click();           // smart home to the top
  await wait(60);
  check(order().join() === "iot,camera,phone,router" && posted.length === 2, "«to top» puts the group first: " + order().join());
  last = posted[posted.length - 1];
  check(last.group_order.length === 10 && last.group_order[0] === "iot", "and posts the whole order: " + JSON.stringify(last));
  check(doc.activeElement && doc.activeElement.closest("[data-go-row]") && doc.activeElement.closest("[data-go-row]").getAttribute("data-go-row") === "iot", "the focus stays on the group moved to the top");
  await wait(60);
  check(sections().join() === "iot,camera,phone,router", "the page follows: " + sections().join());

  up(rows()[2]).click();            // phone goes before camera
  await wait(60);
  check(order().join() === "iot,phone,camera,router" && posted.length === 3, "up swaps with the group shown before: " + order().join());

  const reset = dlg.querySelector("[data-go-reset]");
  check(!!reset && reset.textContent.indexOf(LOCALE["js.ha.order.reset"]) >= 0, "the panel has «" + LOCALE["js.ha.order.reset"] + "»");
  reset.click();
  await wait(60);
  check(order().join() === DEFAULT.filter((g) => ["phone", "camera", "router", "iot"].indexOf(g) >= 0).join(), "reset goes back to the default order: " + order().join());
  check(posted.length === 4 && Array.isArray(posted[3].group_order) && posted[3].group_order.length === 0, "and posts [] (the default order): " + JSON.stringify(posted[3]));
  await wait(60);
  check(sections().join() === "router,phone,iot,camera", "the page goes back to the default order: " + sections().join());

  dlg.querySelector("[data-go-close]").click();
  await wait(30);
  check(!dlg.hasAttribute("open"), "the panel closes");
  check(errors.length === 0, "no error in the page: " + errors.join(" | "));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
