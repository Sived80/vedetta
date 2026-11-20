// The rule of the windows (17/10, written again 17/11): every page and pop-up of the app has the same head, the X first on the left
// (an icon button with its name for screen readers), then the title. Opens every window from the menu and from a card and looks at
// its head: the card of a device, Alerts, Export (and its network guide when it is there), the inventory, the Node-RED flows,
// Networks and the side panel of one network. A new window with the X on the right, or without the X, fails here.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_windows_rule_ui.js [it|en]
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
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }

const on = (source, by) => ({ state: "on", source, by });
const NETS = { left_out: [], limits: {}, networks: [], main: { id: "main", cidr: "192.168.50.0/24", via: ["direct"], touch: "full", state: "confirmed", cards: 4, fits: true, name: "Home", vlan: null, on: 3, mute: false,
  caps: { pres: on("ved", "arp"), name: on("ved", "mdns_netbios"), mac: on("ved", "arp"), port: on("ved", "port_probe"), deep: on("ved", "upnp_mdns"), quiet: on("ved", "arp"), stray: { state: "soon" } } } };
const FLOWS = JSON.parse(fs.readFileSync(path.join(__dirname, "flows_payload_" + lang + ".json"), "utf8"));
delete FLOWS.ui;
const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
  beforeParse(win) {
    win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    win.HTMLDialogElement.prototype.show = function () { this.setAttribute("open", ""); };
    win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); this.dispatchEvent(new win.Event("close")); };
    win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
    win.HTMLElement.prototype.scrollIntoView = function () {};
    win.fetch = (url) => {
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      let b = {};
      if (url.startsWith("/api/ha/devices") && !url.includes("/debug") && !url.includes("/evidence")) b = data.devices;
      else if (url.startsWith("/api/ha/summary")) b = data.summary;
      else if (url.includes("/evidence")) b = { name: { basis: "unknown", certainty: 0, rejected: [] }, brand: { basis: "none", certainty: 0, rejected: [] }, group: { basis: "none", certainty: 0, rejected: [], clues: [], value: "generic" } };
      else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
      else if (url.startsWith("/api/ha/history?")) b = data.history_all;
      else if (url.startsWith("/api/sentinel/services")) b = { services: [] };
      else if (url.startsWith("/api/sentinel")) b = { ha_events: true, notify_service: "" };
      else if (url.startsWith("/api/networks")) b = NETS;
      else if (url.startsWith("/api/new-devices")) b = [];
      else if (url.startsWith("/api/flows")) b = FLOWS;
      else if (url.startsWith("/api/export/info")) b = { daily: Array(90).fill(1000), base: 1000, ratio: 1, seal_factor: 1, limit: 20 * 1048576, horizon: 90, flagged: 0 };
      return ok(b);
    };
    win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const win = dom.window, doc = win.document;
const q = (s) => doc.querySelector(s);

// The head of a window: its first element is the X (an icon button with a name), the title comes after it.
function headRule(where, head) {
  if (!head) return check(false, where + ": la finestra ha un'intestazione");
  const x = head.firstElementChild, title = head.querySelector("h2, h3");
  check(!!x && x.tagName === "BUTTON" && !!x.querySelector("svg") && x.textContent.trim() === "" && !!x.getAttribute("aria-label"), where + ": la prima cosa in alto a sinistra e' la X (icona con il suo nome)");
  check(!!title && !!(x.compareDocumentPosition(title) & win.Node.DOCUMENT_POSITION_FOLLOWING), where + ": il titolo viene dopo la X");
  const right = head.lastElementChild;
  check(head.querySelectorAll("button svg").length === 0 || !(right !== x && right.tagName === "BUTTON" && /close|chiudi|zavř|schließ/i.test(right.getAttribute("aria-label") || "")), where + ": nessuna seconda X a destra");
}
async function fromMenu(sel) { q("#btn-menu").click(); await wait(80); q("#menu " + sel).click(); await wait(250); }
function shut(dlg) { if (dlg.hasAttribute("open")) dlg.close(); }

(async () => {
  await wait(800);
  q(".tile").click();
  await wait(400);
  headRule("scheda del dispositivo", q("#more .mi-header"));
  shut(q("#more"));

  await fromMenu("[data-alerts]");
  headRule("Avvisi", q("#alertsdlg .al-top"));
  shut(q("#alertsdlg"));

  await fromMenu("[data-export]");
  headRule("Esporta", q("#exportdlg .mi-header"));
  const xx = q('#exportdlg [data-xp="close"]');
  if (xx) { xx.click(); await wait(80); }
  check(!!xx && !q("#exportdlg").hasAttribute("open"), "Esporta: la X chiude la finestra");
  shut(q("#exportdlg"));

  await fromMenu("[data-inventory]");
  headRule("Inventario", q("#invdlg .mi-header"));
  shut(q("#invdlg"));

  await fromMenu("[data-flows]");
  headRule("Flussi Node-RED", q("#flows .mi-header"));
  shut(q("#flows"));

  await fromMenu("[data-netpanel]");
  headRule("Reti", q("#netview .np-top"));
  q('[data-np-open="main"]').click();
  await wait(120);
  headRule("Reti, pannello di una rete", q("#netview .np-ptop"));
  const px = q("#netview .np-ptop").firstElementChild;
  px.click();
  await wait(80);
  check(px.matches('[data-np-close="1"]') && !q("#netview .np-panel"), "Reti: la X a sinistra chiude il pannello della rete");

  // the guide of the network option of the export is drawn by its own function: its head is checked on the markup
  const vlan = fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "frontend", "ha", "js", "export-vlan.js"), "utf8");
  check(/class="xv-gt"><button[^>]*data-xp="vlanclose"[\s\S]*?icon\("close"\)[\s\S]*?<h3/.test(vlan), "Esporta, guida delle reti: la X a sinistra, poi il titolo");

  check(errors.length === 0, "nessun errore nella pagina" + (errors.length ? ": " + errors.join("; ") : ""));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
