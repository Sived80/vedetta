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
// The expected texts come from the translation file of the language under test, so the checks hold for every language (a new one needs no change here).
const L = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "locales", lang, "ha.json"), "utf8"));
const tx = (key, params) => {
  params = params || {};
  const form = params.n === undefined ? key : [key + "_" + new Intl.PluralRules(lang).select(params.n), key + "_other", key].find((k) => L[k] !== undefined);
  return L[form].replace(/\{(\w+)\}/g, (_, name) => params[name]);
};
// The same text as a pattern: the placeholders that the test does not know (a time, a name) match anything.
const rx = (key) => new RegExp(L[key].replace(/[.*+?^$()|[\]\\]/g, "\\$&").replace(/\{\w+\}/g, ".+"));
const EVERY10 = tx("js.ha.health.every", { every: tx("js.ha.health.every_min", { n: 10 }) });
const SIM_ON = (k) => tx("js.ha.health.sim.on", { name: tx("js.ha.health.sim." + k) });

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
function boot(debug, health, stored, serverHidden, preview) {
  const errors = [], calls = [], hidden = (serverHidden || []).slice();     // `hidden` is what the server keeps; `stored` is what an older version left in the browser
  const vc = new VirtualConsole();
  vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
  vc.on("error", (e) => errors.push("console.error: " + e));
  const dom = new JSDOM(html, {
    runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
    beforeParse(win) {
      win.addEventListener("unhandledrejection", (ev) => errors.push("rejection: " + (ev.reason && ev.reason.stack || ev.reason)));
      if (debug) win.localStorage.setItem("vedetta-debug", "1");
      if (preview) win.VEDETTA_PREVIEW = "health";
      if (stored) win.localStorage.setItem("vedetta-health-hidden", JSON.stringify(stored));
      win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
      win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
      win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
      win.HTMLElement.prototype.scrollIntoView = function () {};
      win.TextDecoder = require("util").TextDecoder;
      win.fetch = (url, opts) => {
        calls.push(url);
        const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
        let b = {};
        if (url.startsWith("/api/ha/health/hidden")) {
          const body = JSON.parse(opts.body);
          body.show.forEach((id) => { const i = hidden.indexOf(id); if (i >= 0) hidden.splice(i, 1); });
          body.hide.forEach((id) => { if (hidden.indexOf(id) < 0) hidden.push(id); });
          b = { hidden: hidden.slice() };
        } else if (url.startsWith("/api/ha/health")) b = Object.assign({}, health(), { hidden: hidden.slice() });
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
  return { win, doc, q, qa, click, text, errors, calls, hidden };
}
const running = (list) => () => ({ running: true, findings: list });
// The way in is the tile of the carousel: it turns by itself and a click on another tile passes to the next; this goes to the health one and opens it.
const TITLE = new RegExp(L["js.ha.health.title"] + "|" + L["js.ha.health.sim.tile"]);
async function openHealth(p) {
  for (let i = 0; i < 10 && !TITLE.test(p.text("#rot .t-l")); i++) await p.click("#rot");
  await p.click("#rot .hs-go");
}

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

  // --- nothing wrong: no four empty tiles, a short report (what was checked, the last check, the last problem); the same facts once
  const quiet = (report) => () => ({ running: true, findings: [], report });
  p = boot(true, quiet({ judged: NOW - 60, last_problem: { rule: "H20", end: NOW - 3 * 86400 } }));
  await wait(1500);
  await openHealth(p);
  check(!p.q(".hs-tile") && !!p.q(".hs-report"), "senza problemi: niente quattro tile a zero, un resoconto");
  check(rx("js.ha.health.report.checked").test(p.text(".hs-report p")), "il resoconto dice cosa e' stato controllato");
  check(rx("js.ha.health.report.judged").test(p.text(".hs-report")) && rx("js.ha.health.report.last").test(p.text(".hs-report")), "il resoconto dice l'ultimo controllo e l'ultimo problema");
  check(p.qa(".hs-report .hs-rep-f").length === 2 && !p.q(".hs-report .stat-box"), "solo la frase e due righe: nessun numero gia' mostrato dalle altre schermate");
  p = boot(true, quiet(null));
  await wait(1500);
  check(rx("js.ha.health.report.looking").test(p.text(".hs-report")) && rx("js.ha.health.report.never").test(p.text(".hs-report")), "prima del primo giudizio e senza storia: lo dice");

  // --- the debug mode on: two dots, four tiles
  p = boot(true, running(FINDINGS));
  await wait(1500);
  const { q, qa, click, text } = p;
  check(!!q(".hs-stack") && !q(".hs-dots"), "col debug la scheda ha lo strato della salute e nessun puntino");
  check(TITLE.test(text("#rot .t-l")) && /3/.test(text("#rot .stat-box-val")), "con rilievi il carosello salta alla tile «Salute della rete» e dice quanti sono: " + text("#rot"));
  check(!!q("#rot .hs-go") && text("#rot .hs-go").includes(tx("js.ha.health.card.open")), "la tile ha il tasto «Apri» ben visibile");
  const heldOn = text("#rot .t-l");
  await wait(5000);
  check(text("#rot .t-l") === heldOn, "la tile resta ferma qualche secondo, il carosello non scappa via");
  check(!!q("#card-network .hs-pane.net #gauge") && !!q("#card-network .hs-pane.net #badges") && !!q("#card-network .hs-pane.net #search-row"), "la schermata rete tiene il cerchio, i badge e la ricerca (con i loro gestori)");
  await click("#rot");
  await wait(300);
  check(q(".hs-stack").getAttribute("data-at") === "0" && TITLE.test(text("#rot .t-l")) === false, "un tocco sul corpo della tile passa alla successiva, non apre il pannello");
  for (let i = 0; i < 10 && !TITLE.test(text("#rot .t-l")); i++) await click("#rot");
  await click("#rot .hs-go");
  check(q(".hs-stack").getAttribute("data-at") === "1" && q(".hs-pane.health .hs-d-head").firstElementChild.dataset.act === "exit", "il tasto «Apri» apre la schermata e la X e' in alto a sinistra");
  const tiles = qa(".hs-tile");
  check(tiles.length === 4 && tiles.map((t) => t.querySelector(".t-l").textContent.trim()).join() === ["addr", "drop", "boot", "lat"].map((k) => tx("js.ha.health.tile." + k)).join(), "quattro tile: " + tiles.map((t) => t.querySelector(".t-l").textContent.trim()).join());
  const active = tiles.map((t) => t.querySelector(".stat-box-val").textContent.trim()).join();
  check(active === "1,1,1,0", "i numeri «Attivi» vengono dal server: " + active);

  // --- a tile opens the big one: the X on the left, no total, no coloured icon; a row for each finding
  await click(tiles[0]);
  check(q(".hs-stack").getAttribute("data-at") === "2" && q(".hs-pane.detail .hs-d-head").firstElementChild.dataset.act === "close", "la tile si apre e la X di chiusura e' il primo elemento a sinistra");
  check(!q(".hs-pane.detail .hs-d-head .hs-d-count") && !q(".hs-pane.detail .hs-d-head .hs-lv") && qa(".hs-pane.detail .hs-d-head button").length === 1, "nella testata dell'elenco: solo la X, niente totale, niente icona colorata");
  check(qa(".hs-row").length === 1 && text(".hs-rf").includes(tx("js.ha.devices_count", { n: 2 }) + " · 192.168.1.50"), "la riga dice quanti dispositivi e l'IP: " + text(".hs-rf"));

  // --- a row opens the detail: who (name left, IP right), what, when, what to do; no MAC
  await click(".hs-row-main");
  check(q(".hs-pane.detail .hs-d-head").firstElementChild.dataset.act === "back" && q(".hs-pane.detail .hs-d-head").lastElementChild.dataset.act === "hide" && qa(".hs-pane.detail .hs-d-head button").length === 2, "nel dettaglio: la X a sinistra torna indietro, a destra resta solo l'occhio barrato");
  const devs = qa(".hs-dev");
  check(devs.length === 2 && devs[0].querySelector("b").textContent === "Router casa" && devs[0].querySelector("span").textContent === "192.168.1.50", "l'elenco dei dispositivi: nome a sinistra, IP a destra");
  check(devs[1].textContent.includes(tx("js.ha.health.unknown", { mac: "…00:99" })) && !/aa:bb:cc:00:00:99/i.test(q(".hs-pg").textContent), "un dispositivo senza scheda si riconosce dalla coda del MAC, il MAC intero non c'e'");
  check((rx("js.ha.health.when_today").test(text(".hs-pg")) || rx("js.ha.health.when_day").test(text(".hs-pg"))) && /IP/.test(text(".hs-pg")) && !!q(".hs-act"), "il dettaglio ha cosa, quando e cosa fare");

  // --- the device opens its card; a device without a card does nothing
  await click(devs[0]);
  check(q("#more").hasAttribute("open"), "toccando un dispositivo si apre la sua scheda");
  q("#more").removeAttribute("open");
  check(devs[1].disabled === true, "un dispositivo senza scheda non e' toccabile");

  // --- the X goes back one step, Esc too; the eye hides, and the choice is kept
  await click(".hs-pane.detail .hs-d-head [data-act='back']");
  check(qa(".hs-row").length === 1 && q(".hs-stack").getAttribute("data-at") === "2", "la X nel dettaglio torna all'elenco");
  await click(".hs-row-main");
  p.doc.dispatchEvent(new p.win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await wait(40);
  check(qa(".hs-row").length === 1, "Esc torna all'elenco");
  await click(".hs-row-main");
  await click(".hs-pane.detail .hs-d-head [data-act='hide']");
  check(qa(".hs-row:not(.dim)").length === 0 && text(".hs-hidrow").includes(tx("js.ha.health.hidden", { n: 1 })) && !!q(".hs-empty"), "Nascondi riporta all'elenco: nessun problema e «1 nascosto»");
  await click(".hs-pane.detail .hs-d-head [data-act='close']");
  check(/(^|,)0\/1(,|$)/.test(qa(".hs-tile").map((t) => t.querySelector(".stat-box-val").textContent.replace(/\s/g, "")).join()), "sulla tile il conteggio dei nascosti e' visibile: attivi 0, nascosti 1 (0/1)");
  await click(".hs-tile[data-key='addr']");
  check(p.hidden.join() === "H20:192.168.1.50", "la scelta e' salvata dal server, non nel browser");
  await click(".hs-hidrow");
  check(qa(".hs-row.dim").length === 1 && text(".hs-row.dim .hs-rf").includes(tx("js.ha.devices_count", { n: 2 }) + " · 192.168.1.50"), "il nascosto si apre e dice quanti dispositivi e l'IP");
  await click(".hs-row.dim [data-act='restore']");
  check(qa(".hs-row:not(.dim)").length === 1 && !q(".hs-hidrow"), "Ripristina lo riporta tra gli attivi");
  await click(".hs-pane.detail .hs-d-head [data-act='close']");
  check(q(".hs-stack").getAttribute("data-at") === "1", "la X dell'elenco chiude la tile grande e torna alle quattro");

  // --- the X of the screen goes back to the carousel, Esc too
  await click(".hs-pane.health [data-act='exit']");
  check(q(".hs-stack").getAttribute("data-at") === "0", "la X della schermata torna al carosello");
  await click("#rot .hs-go");
  p.doc.dispatchEvent(new p.win.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  await wait(40);
  check(q(".hs-stack").getAttribute("data-at") === "0", "Esc dalla schermata torna al carosello");
  await click("#rot .hs-go");

  // --- a device that restarts: the name and the IP at the top, the dots of the restarts, when, what to do
  await click(qa(".hs-tile")[2]);
  await click(".hs-row-main");
  check(/Luce cucina\s*192\.168\.1\.37/.test(text(".hs-nm")), "un solo dispositivo: nome e IP in alto");
  check(qa(".hs-strip .hs-dots i").length === 11 && !q(".hs-strip svg") && text(".hs-sl").includes(tx("js.ha.health.times", { n: 11 })) && text(".hs-sl").includes(EVERY10), "i puntini dei riavvii: undici, «ogni 10 min»");
  check(text(".hs-ln").includes(EVERY10) && !!q(".hs-act"), "la causa e l'azione ci sono");
  await click(".hs-pane.detail .hs-d-head [data-act='back']"); await click(".hs-pane.detail .hs-d-head [data-act='close']");

  // --- many devices: the list scrolls inside, the box does not grow
  await click(qa(".hs-tile")[1]);
  await click(".hs-row-main");
  check(qa(".hs-dev").length === 6, "sei dispositivi: l'elenco ha sei righe che scorrono dentro la scheda");
  await click(".hs-pane.detail .hs-d-head [data-act='back']"); await click(".hs-pane.detail .hs-d-head [data-act='close']");

  // --- the debug mode off: the screens go and the network screen is as before
  p.doc.dispatchEvent(new p.win.KeyboardEvent("keydown", { key: "D", ctrlKey: true, shiftKey: true, bubbles: true }));
  await wait(200);
  check(!q(".hs-stack") && !q(".hs-dots") && q("#card-network .card-content > #badges") && q("#card-network .card-content > .hero-row #gauge") && q("#card-network .card-content > #search-row"), "spento il debug, la scheda torna com'era (badge, cerchio e ricerca al loro posto)");
  p.doc.dispatchEvent(new p.win.KeyboardEvent("keydown", { key: "D", ctrlKey: true, shiftKey: true, bubbles: true }));
  await wait(600);
  check(!!q(".hs-stack"), "riacceso il debug, la schermata torna");
  check(p.errors.length === 0, "nessun errore nella pagina" + (p.errors.length ? ": " + p.errors[0] : ""));

  // --- a choice that was made before is still there at the next visit
  p = boot(true, running(FINDINGS), null, ["H05:" + D[1].id]);
  await wait(1500);
  await openHealth(p);
  check(p.qa(".hs-tile").map((t) => t.querySelector(".stat-box-val").textContent.trim()).join() === "1,1,0/1,0", "il nascosto di una visita precedente resta nascosto: i numeri sono 1,1,0/1,0");

  // --- the preview of the public demo: no debug mode, the feature shown with made-up findings and marked "coming soon", nothing asked of the server
  p = boot(false, running([]), null, null, true);
  await wait(1500);
  check(!p.doc.documentElement.hasAttribute("data-debug") && !!p.q(".hs-stack") && !p.calls.some((u) => u.includes("/api/ha/health")), "anteprima: senza debug la schermata c'e' e non chiede nulla al server");
  await openHealth(p);
  check(p.text("#rot .hs-soon") === tx("js.ha.health.soon") && TITLE.test(p.text("#rot .t-l")) && p.text("#rot .t-l") !== tx("js.ha.health.sim.tile"), "anteprima: la tile dice «in arrivo» e porta il suo nome");
  check(p.qa(".hs-tile").length === 4 && p.text(".hs-pane.health .hs-soon") === tx("js.ha.health.soon") && !p.q(".hs-sim"), "anteprima: quattro tile, «in arrivo» nella testata, nessun pulsante per cambiare scenario");
  check(p.text("#rot .t-mid .hs-soon") === tx("js.ha.health.soon") && !p.q("#rot .t-head .hs-soon"), "anteprima: «in arrivo» sta sopra le caselle, non nel titolo dove verrebbe tagliato");
  check(p.errors.length === 0, "anteprima: nessun errore nella pagina" + (p.errors.length ? ": " + p.errors[0] : ""));

  // --- made-up findings (debug only): the button of the head steps through the scenarios, nothing goes to the server
  p = boot(true, quiet(null));
  await wait(1500);
  await openHealth(p);
  check(p.text(".hs-sim") === tx("js.ha.health.sim.off") && !p.q(".hs-sim.on"), "il pulsante «Simula» e' nella testata e a riposo");
  await p.click(".hs-sim");
  await wait(150);
  check(p.q(".hs-sim.on") && p.text(".hs-sim") === SIM_ON("calm") && !!p.q(".hs-tiles.quiet"), "primo scenario: tutto bene, il resoconto della rete tranquilla");
  await p.click(".hs-sim");
  await wait(150);
  check(p.text(".hs-sim") === SIM_ON("one") && p.qa(".hs-tile").length === 4, "secondo scenario: un problema, le quattro tile");
  await p.click(".hs-tile[data-key='boot']");
  await p.click(".hs-row-main");
  await p.click(".hs-pane.detail .hs-d-head [data-act='hide']");
  check(p.hidden.length === 0 && !p.calls.some((u) => u.includes("/health/hidden")), "nascondere un rilievo finto non scrive nulla sul server");
  await p.click(".hs-pane.detail .hs-d-head [data-act='close']");
  await p.click(".hs-pane.health [data-act='exit']");
  await wait(300);
  check(p.text("#rot .t-l") === tx("js.ha.health.sim.tile"), "con la simulazione accesa la tile del carosello lo dice");
  await openHealth(p);
  for (let i = 0; i < 4; i++) { await p.click(".hs-sim"); await wait(100); }
  check(!p.q(".hs-sim.on") && p.text(".hs-sim") === tx("js.ha.health.sim.off"), "dopo l'ultimo scenario si torna ai dati veri");
  check(p.errors.length === 0, "simulazione: nessun errore nella pagina" + (p.errors.length ? ": " + p.errors[0] : ""));

  // --- an older version kept the choice in the browser: it goes to the server once, then leaves the browser
  p = boot(true, running(FINDINGS), ["H05:" + D[1].id]);
  await wait(1500);
  check(p.hidden.join() === "H05:" + D[1].id && p.win.localStorage.getItem("vedetta-health-hidden") === null, "la scelta vecchia del browser passa al server e poi sparisce dal browser");
  await openHealth(p);
  check(p.qa(".hs-tile").map((t) => t.querySelector(".stat-box-val").textContent.trim()).join() === "1,1,0/1,0", "dopo il passaggio il nascosto vale ancora");
  console.log(failed ? "FALLITI: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
