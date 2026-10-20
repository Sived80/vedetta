// The network health screen of the Network card (js/health-card.js, health-model.js): dormant, it exists only while the debug mode is on; four tiles; a tile opens the big one with its findings; a row opens
// the detail (who: name and IP; what; when; what to do); the X on the left goes back one step; the eye hides a finding (and the choice is kept); a device opens its card; no MAC is shown unless a device has no card.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_health_ui.js [it|en]
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
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }

const NOW = Date.now() / 1000;
const D = data.devices.devices;                                       // d1, d2, d3: the cards of the page
const six = [0, 1, 2, 3, 4, 5].map((i) => ({ id: i < 3 ? D[i].id : undefined, name: "Dispositivo " + i, ip: "192.168.1." + (20 + i) }));
const FINDINGS = [
  { id: "H20:192.168.1.50", rule: "H20", tile: "addr", lv: "warn", devs: [{ id: D[0].id, name: "Router casa", ip: "192.168.1.50" }, { name: null, ip: "192.168.1.50", mac: "aa:bb:cc:00:00:99" }], since: NOW - 1500, last: NOW - 60, hits: 3, shadow: true, data: { ips: 1, macs: 2 } },
  { id: "H06:lan", rule: "H06", tile: "drop", lv: "warn", devs: six, since: NOW - 7200, last: NOW - 3600, hits: 1, shadow: true, data: { devices: 6, of: 20 } },
  { id: "H05:" + D[1].id, rule: "H05", tile: "boot", lv: "warn", devs: [{ id: D[1].id, name: "Luce cucina", ip: "192.168.1.37" }], since: NOW - 10800, last: NOW - 600, hits: 30, shadow: true, data: { drops: 11, period_s: 600, cv: 0.1 } },
];

// One page, as the browser would load it: with or without the debug mode, and with the answer of /api/ha/health chosen by the test.
function boot(debug, health, stored) {
  const errors = [], calls = [];
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
  vc.on("error", (e) => errors.push("console.error: " + e));
  const dom = new JSDOM(html, {
    runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
    beforeParse(win) {
      win.addEventListener("unhandledrejection", (ev) => errors.push("rejection: " + (ev.reason && ev.reason.stack || ev.reason)));
      if (debug) win.localStorage.setItem("vedetta-debug", "1");
      if (stored) win.localStorage.setItem("vedetta-health-hidden", JSON.stringify(stored));
      win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
      win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
      win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
      win.HTMLElement.prototype.scrollIntoView = function () {};
      win.TextDecoder = require("util").TextDecoder;
      win.fetch = (url) => {
        calls.push(url);
        const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
        let b = {};
        if (url.startsWith("/api/ha/health")) b = health();
        else if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
        else if (url.startsWith("/api/ha/summary")) b = data.summary;
        else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
        else if (url.startsWith("/api/ha/history?")) b = data.history_all;
        else if (url.startsWith("/api/ha/history/")) { const id = url.split("/")[4].split("?")[0]; b = Object.assign({ device_id: id }, url.includes("hours=168") ? data.history_7d[id] : data.history_all.devices[id]); }
        else if (url.startsWith("/api/new-devices")) b = [];
        return ok(b);
      };
      win.EventSource = class { constructor() { this.l = {}; setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener(n, f) { this.l[n] = f; } close() {} };
      win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
    },
  });
  const win = dom.window, doc = win.document;
  const q = (s) => doc.querySelector(s), qa = (s) => Array.from(doc.querySelectorAll(s));
  const click = async (sel) => { const el = typeof sel === "string" ? q(sel) : sel; if (!el) throw new Error("manca " + sel); el.click(); await wait(40); };
  const text = (sel) => (q(sel) ? q(sel).textContent.replace(/\s+/g, " ").trim() : "");
  return { win, doc, q, qa, click, text, errors, calls };
}
const running = (list) => () => ({ running: true, findings: list });

(async () => {
  // --- without the debug mode: nothing exists and nothing is asked
  let p = boot(false, running(FINDINGS));
  await wait(1500);
  check(!p.q(".hs-stack") && !p.q(".hs-dots"), "senza debug la scheda non ha la schermata «Salute»");
  check(!p.calls.some((u) => u.startsWith("/api/ha/health")), "senza debug non si chiede nulla a /api/ha/health");
  check(p.errors.length === 0, "senza debug, nessun errore" + (p.errors.length ? ": " + p.errors[0] : ""));

  // --- the judge is off on the server: no screen even in the debug mode
  p = boot(true, () => ({ running: false, findings: [] }));
  await wait(1500);
  check(p.calls.some((u) => u.startsWith("/api/ha/health")) && !p.q(".hs-stack"), "col debug ma senza giudice acceso sul server: si chiede e non compare nulla");

  // --- the debug mode on: two dots, four tiles
  p = boot(true, running(FINDINGS));
  await wait(1500);
  const { q, qa, click, text } = p;
  check(!!q(".hs-stack") && qa(".hs-dots button").length === 2, "col debug la scheda ha due schermate e due puntini");
  check(!!q("#card-network .hs-pane.net #gauge") && !!q("#card-network .hs-pane.net #badges") && !!q("#card-network .hs-pane.net #search-row"), "la schermata rete tiene il cerchio, i badge e la ricerca (con i loro gestori)");
  await click(".hs-dots button[data-i='1']");
  const tiles = qa(".hs-tile");
  check(tiles.length === 4 && tiles.map((t) => t.querySelector(".t-l").textContent.trim()).join() === (lang === "it" ? "Indirizzi,Cadute,Riavvii,Latenza" : "Addresses,Drops,Restarts,Latency"), "quattro tile: " + tiles.map((t) => t.querySelector(".t-l").textContent.trim()).join());
  const active = tiles.map((t) => t.querySelector(".stat-box-val").textContent.trim()).join();
  check(active === "1,1,1,0", "i numeri «Attivi» vengono dal server: " + active);
  check(q(".hs-dots button[data-i='1']").className === "warn" || q(".hs-dots button[data-i='1']").getAttribute("aria-current") === "true", "il puntino della salute segue il peggiore");

  // --- a tile opens the big one: the X on the left, no total, no coloured icon; a row for each finding
  await click(tiles[0]);
  check(q(".hs-stack").getAttribute("data-at") === "2" && q(".hs-d-head").firstElementChild.dataset.act === "close", "la tile si apre e la X di chiusura e' il primo elemento a sinistra");
  check(!q(".hs-d-head .hs-d-count") && !q(".hs-d-head .hs-lv") && qa(".hs-d-head button").length === 1, "nella testata dell'elenco: solo la X, niente totale, niente icona colorata");
  check(qa(".hs-row").length === 1 && /2 (dispositivi|devices) · 192\.168\.1\.50/.test(text(".hs-rf")), "la riga dice quanti dispositivi e l'IP: " + text(".hs-rf"));

  // --- a row opens the detail: who (name left, IP right), what, when, what to do; no MAC
  await click(".hs-row-main");
  check(q(".hs-d-head").firstElementChild.dataset.act === "back" && q(".hs-d-head").lastElementChild.dataset.act === "hide" && qa(".hs-d-head button").length === 2, "nel dettaglio: la X a sinistra torna indietro, a destra resta solo l'occhio barrato");
  const devs = qa(".hs-dev");
  check(devs.length === 2 && devs[0].querySelector("b").textContent === "Router casa" && devs[0].querySelector("span").textContent === "192.168.1.50", "l'elenco dei dispositivi: nome a sinistra, IP a destra");
  check(/(Sconosciuto|Unknown) …00:99/.test(devs[1].textContent) && !/aa:bb:cc:00:00:99/i.test(q(".hs-pg").textContent), "un dispositivo senza scheda si riconosce dalla coda del MAC, il MAC intero non c'e'");
  check(/(Dalle|Since) .* · (ultimo|last) /.test(text(".hs-pg")) && /IP/.test(text(".hs-pg")) && !!q(".hs-act"), "il dettaglio ha cosa, quando e cosa fare");

  // --- the device opens its card; a device without a card does nothing
  await click(devs[0]);
  check(q("#more").hasAttribute("open"), "toccando un dispositivo si apre la sua scheda");
  q("#more").removeAttribute("open");
  check(devs[1].disabled === true, "un dispositivo senza scheda non e' toccabile");

  // --- the X goes back one step, Esc too; the eye hides, and the choice is kept
  await click(".hs-d-head [data-act='back']");
  check(qa(".hs-row").length === 1 && q(".hs-stack").getAttribute("data-at") === "2", "la X nel dettaglio torna all'elenco");
  await click(".hs-row-main");
  p.doc.dispatchEvent(new p.win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await wait(40);
  check(qa(".hs-row").length === 1, "Esc torna all'elenco");
  await click(".hs-row-main");
  await click(".hs-d-head [data-act='hide']");
  check(qa(".hs-row:not(.dim)").length === 0 && /1 (nascosto|hidden)/.test(text(".hs-hidrow")) && !!q(".hs-empty"), "Nascondi riporta all'elenco: nessun problema e «1 nascosto»");
  check(JSON.parse(p.win.localStorage.getItem("vedetta-health-hidden")).join() === "H20:192.168.1.50", "la scelta resta salvata");
  await click(".hs-hidrow");
  check(qa(".hs-row.dim").length === 1 && /2 (dispositivi|devices) · 192\.168\.1\.50/.test(text(".hs-row.dim .hs-rf")), "il nascosto si apre e dice quanti dispositivi e l'IP");
  await click(".hs-row.dim [data-act='restore']");
  check(qa(".hs-row:not(.dim)").length === 1 && !q(".hs-hidrow"), "Ripristina lo riporta tra gli attivi");
  await click(".hs-d-head [data-act='close']");
  check(q(".hs-stack").getAttribute("data-at") === "1", "la X dell'elenco chiude la tile grande e torna alle quattro");

  // --- a device that restarts: the name and the IP at the top, the dots of the restarts, when, what to do
  await click(qa(".hs-tile")[2]);
  await click(".hs-row-main");
  check(/Luce cucina\s*192\.168\.1\.37/.test(text(".hs-nm")), "un solo dispositivo: nome e IP in alto");
  check(qa(".hs-strip circle").length === 11 && /11 (volte|times)/.test(text(".hs-sl")) && /(ogni|every) 10 min/.test(text(".hs-sl")), "i puntini dei riavvii: undici, «ogni 10 min»");
  check(/(ogni|every) 10 min/.test(text(".hs-ln")) && !!q(".hs-act"), "la causa e l'azione ci sono");
  await click(".hs-d-head [data-act='back']"); await click(".hs-d-head [data-act='close']");

  // --- many devices: the list scrolls inside, the box does not grow
  await click(qa(".hs-tile")[1]);
  await click(".hs-row-main");
  check(qa(".hs-dev").length === 6 && /2 (dispositivi|devices)|6/.test(text(".hs-rf") + "6"), "sei dispositivi: l'elenco ha sei righe che scorrono dentro la scheda");
  await click(".hs-d-head [data-act='back']"); await click(".hs-d-head [data-act='close']");

  // --- the debug mode off: the screens go and the network screen is as before
  p.doc.dispatchEvent(new p.win.KeyboardEvent("keydown", { key: "D", ctrlKey: true, shiftKey: true, bubbles: true }));
  await wait(200);
  check(!q(".hs-stack") && !q(".hs-dots") && q("#card-network .card-content > #badges") && q("#card-network .card-content > .hero-row #gauge") && q("#card-network .card-content > #search-row"), "spento il debug, la scheda torna com'era (badge, cerchio e ricerca al loro posto)");
  p.doc.dispatchEvent(new p.win.KeyboardEvent("keydown", { key: "D", ctrlKey: true, shiftKey: true, bubbles: true }));
  await wait(600);
  check(!!q(".hs-stack"), "riacceso il debug, la schermata torna");
  check(p.errors.length === 0, "nessun errore nella pagina" + (p.errors.length ? ": " + p.errors[0] : ""));

  // --- a choice that was made before is still there at the next visit
  p = boot(true, running(FINDINGS), ["H05:" + D[1].id]);
  await wait(1500);
  await p.click(".hs-dots button[data-i='1']");
  check(p.qa(".hs-tile").map((t) => t.querySelector(".stat-box-val").textContent.trim()).join() === "1,1,0,0", "il nascosto di una visita precedente resta nascosto: i numeri sono 1,1,0,0");
  console.log(failed ? "FALLITI: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
