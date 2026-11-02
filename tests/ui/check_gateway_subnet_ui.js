// The gateway tile of the Network card on a network wider than a /24 (Discussion #15): the subnet the server read (roles.network) is the label, the number of addresses comes from it and every
// device inside it is counted, the /24 of the gateway too. Without it (an older server) the tile is the /24 of the gateway, as before. Needs jsdom (see check_tiles_ui.js).
//   from the vedetta/ folder:  node ../tests/ui/check_gateway_subnet_ui.js [it|en]
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
const base = fs.readFileSync(path.join(out, "data.json"), "utf8");
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }

// The page with the three devices of build_page.py, the gateway at 192.168.1.1 and the third device moved to another /24 of a /22.
function gatewayText(network) {
  const data = JSON.parse(base);
  const gw = data.devices.devices[0];
  data.devices.devices[2].ip = "192.168.3.7";
  data.summary.roles = Object.assign({}, data.summary.roles, { by_ip: { [gw.ip]: { gateway: "arp" } } }, network === undefined ? {} : { network });
  const errors = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
  const dom = new JSDOM(html, {
    runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
    beforeParse(win) {
      win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
      win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
      win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
      win.HTMLElement.prototype.scrollIntoView = function () {};
      win.fetch = (url) => {
        let b = {};
        if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
        else if (url.startsWith("/api/ha/summary")) b = data.summary;
        else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
        else if (url.startsWith("/api/ha/history?")) b = data.history_all;
        else if (url.startsWith("/api/ha/history/")) { const id = url.split("/")[4].split("?")[0]; b = Object.assign({ device_id: id }, data.history_all.devices[id]); }
        return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      };
      win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
      win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
    },
  });
  const doc = dom.window.document, wait = (ms) => new Promise((r) => setTimeout(r, ms));
  return (async () => {
    await wait(1500);
    for (let i = 0; i < 8; i++) {
      if (/^Gateway$/.test((doc.querySelector("#rot .t-l") || { textContent: "" }).textContent.trim())) break;
      doc.querySelector("#rot").click();
      await wait(350);
    }
    const label = (doc.querySelector("#rot .t-l") || { textContent: "" }).textContent.trim();
    const text = label === "Gateway" ? doc.querySelector("#rot .t-body").textContent.replace(/\s+/g, " ").trim() : "";
    dom.window.close();
    return { text, errors };
  })();
}

(async () => {
  const wide = await gatewayText("192.168.0.0/22");
  check(wide.text.includes("192.168.0.0/22") && !wide.text.includes("/24"), "rete /22: la tile mostra la sottorete vera: " + wide.text);
  check(/\D3 (usati|used|belegt)/.test(wide.text) && /1019 (liberi|free|frei)/.test(wide.text), "rete /22: contati i tre dispositivi (anche quello su 192.168.3.x) e 1019 indirizzi liberi su 1022");
  const old = await gatewayText(undefined);
  check(old.text.includes("192.168.1.0/24") && /\D2 (usati|used|belegt)/.test(old.text) && /252 (liberi|free|frei)/.test(old.text), "senza la sottorete dal server: la /24 del gateway come prima (2 usati, 252 liberi): " + old.text);
  const odd = await gatewayText("10.20.0.0/22");
  check(odd.text.includes("192.168.1.0/24"), "una sottorete che non contiene il gateway non viene usata: " + odd.text);
  const errors = [...wide.errors, ...old.errors, ...odd.errors];
  check(errors.length === 0, "nessun errore nella pagina" + (errors.length ? ": " + errors.join(" | ") : ""));
  console.log(failed ? "FALLITI: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
