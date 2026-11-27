// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The Sentinel on the page: the bell on a card ("tell me if it disappears") next to the flag, plain icon, pressed when on, saved with
// {"watch": true|false}; in the menu, «Alerts» opens a window like the other ones (the X first on the left, the buttons at the foot)
// with the switch of the events in Home Assistant, the notify services (None first, then the ones Home Assistant has), «Send a test»
// and what Home Assistant answered; every change is saved at once. Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_alerts_ui.js [it|en]
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
const HA = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "locales", lang, "ha.json"), "utf8"));
const out = fs.mkdtempSync(path.join(os.tmpdir(), "vedetta-ui-"));
const built = spawnSync(process.env.PYTHON || "python", [path.join(__dirname, "build_page.py"), out, lang], { cwd: path.join(__dirname, "..", "..", "vedetta"), encoding: "utf8" });
if (built.status !== 0) { console.log("build_page.py failed:\n" + built.stdout + built.stderr); process.exit(1); }
const html = fs.readFileSync(path.join(out, "page.html"), "utf8");
const data = JSON.parse(fs.readFileSync(path.join(out, "data.json"), "utf8"));
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }

const errors = [], overrides = [], saves = [], tests = [];
let cfg = { ha_events: true, notify_service: "", notify_order: [{ service: "notify.gone_phone", delay_s: 0 }] };    // a recipient HA no longer has
let testAnswer = { ok: true };
let overrideHold = null;
let sentinelHold = null;                               // the same for the saves of Alerts: a promise, or "fail" for the next one                               // a promise the save waits for (a slow Home Assistant); "fail" = the server refuses
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
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      const method = (opts && opts.method) || "GET";
      let b = {};
      if (url.includes("/override")) {
        overrides.push(JSON.parse(opts.body));
        if (overrideHold === "fail") return Promise.resolve({ ok: false, status: 500, headers: { get: () => null }, json: () => Promise.resolve({}), text: () => Promise.resolve("{}") });
        if (overrideHold) return overrideHold.then(() => ok({ ok: true }));
        b = { ok: true };
      }
      else if (url.startsWith("/api/sentinel/services")) b = { services: ["notify.tv_salotto", "notify.mobile_app_pixel", "notify.persistent_notification"], waiting: 0,
        last: { "notify.gone_phone": { at: 1700000000, ok: false, error: "not_found" } } };
      else if (url.startsWith("/api/sentinel/test")) { tests.push(JSON.parse(opts.body)); if (testAnswer === "down") return Promise.reject(new TypeError("Failed to fetch")); b = testAnswer; }
      else if (url.startsWith("/api/sentinel") && method === "POST") {
        const c = JSON.parse(opts.body);
        saves.push(c);
        if (sentinelHold === "fail") { sentinelHold = null; return Promise.resolve({ ok: false, status: 500, headers: { get: () => null }, json: () => Promise.resolve({}), text: () => Promise.resolve("{}") }); }
        const apply = () => { cfg = Object.assign({}, cfg, c); return ok(cfg); };
        if (sentinelHold) return sentinelHold.then(apply);
        return apply();
      }
      else if (url.startsWith("/api/sentinel")) b = cfg;
      else if (url.startsWith("/api/ha/devices") && !url.includes("/debug") && !url.includes("/evidence")) b = data.devices;
      else if (url.startsWith("/api/ha/summary")) b = data.summary;
      else if (url.includes("/evidence")) b = { name: { basis: "unknown", certainty: 0, rejected: [] }, brand: { basis: "none", certainty: 0, rejected: [] }, group: { basis: "none", certainty: 0, rejected: [], clues: [], value: "generic" } };
      else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
      else if (url.startsWith("/api/ha/history?")) b = data.history_all;
      return ok(b);
    };
    win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const win = dom.window, doc = win.document;
const q = (s) => doc.querySelector(s);
const bell = () => q("#more .mi-watch");

(async () => {
  await wait(800);
  // --- the bell on a card
  q('.tile[data-id="d2"]').click();
  await wait(400);
  check(!!bell() && !!q("#more .mi-flag") && q("#more .mi-flag").nextElementSibling === bell(), "sulla scheda la campanella e' accanto alla bandierina");
  check(bell().getAttribute("aria-pressed") === "false" && !bell().classList.contains("on") && bell().textContent.trim() === "" && !!bell().querySelector("svg"), "spenta: solo icona, non premuta");
  check(bell().title.length > 0 && bell().title === bell().getAttribute("aria-label"), "con il suo testo (" + bell().title + ")");
  bell().click();
  await wait(200);
  check(overrides.length === 1 && overrides[0].watch === true, "il tocco salva watch: true");
  check(bell().getAttribute("aria-pressed") === "true" && bell().classList.contains("on"), "accesa: premuta");
  const tileBell = () => q('.tile[data-id="d2"] .tile-watch');
  check(!!tileBell() && !tileBell().hidden && tileBell().title.length > 0, "accesa: sulla tile compare la campanella in basso a sinistra dell'icona");
  bell().click();
  await wait(200);
  check(overrides.length === 2 && overrides[1].watch === false && bell().getAttribute("aria-pressed") === "false", "un altro tocco la spegne (watch: false)");
  check(tileBell().hidden, "spenta: la campanella sparisce dalla tile");
  // a slow server: the bell changes at the touch, not when the answer comes
  let release;
  overrideHold = new Promise((r) => { release = r; });
  bell().click();
  await wait(60);
  check(bell().getAttribute("aria-pressed") === "true" && !tileBell().hidden, "server lento: la campanella si accende subito al tocco, senza aspettare la risposta");
  release();
  await wait(100);
  check(overrides.length === 3 && overrides[2].watch === true && bell().getAttribute("aria-pressed") === "true", "e resta accesa quando il server ha salvato");
  // two quick taps on a slow server: the second waits for the first, the bell ends as the last tap and as the server (19/11 review)
  let release2;
  overrideHold = new Promise((r) => { release2 = r; });
  const ovBefore = overrides.length;
  bell().click();
  await wait(20);
  bell().click();
  await wait(20);
  check(overrides.length === ovBefore + 1, "il secondo tocco aspetta il primo (" + (overrides.length - ovBefore) + " inviati)");
  overrideHold = null;
  release2();
  await wait(200);
  check(overrides.length === ovBefore + 2 && overrides[overrides.length - 1].watch === true && bell().getAttribute("aria-pressed") === "true", "poi parte il secondo: accesa, come l'ultimo tocco");
  // nobody gets the alerts (no recipient, events off, as after the install): the bell says so instead of promising (19/11 review)
  const cfgWas = cfg;
  bell().click();
  await wait(200);
  cfg = { ha_events: false, notify_service: "", notify_order: [] };
  bell().click();
  await wait(300);
  const snacks = Array.from(doc.querySelectorAll(".snack")), said = snacks.length ? snacks[snacks.length - 1].textContent : "";
  check(said.includes(HA["js.ha.watch.added_nobody"]), "nessun destinatario: la campanella lo dice invece di promettere (" + said + ")");
  cfg = cfgWas;
  overrideHold = "fail";
  bell().click();
  await wait(150);
  check(bell().getAttribute("aria-pressed") === "true" && !tileBell().hidden && !!q(".snackbar, .snack, [role=status]"), "se il salvataggio fallisce torna com'era e lo dice");
  overrideHold = null;
  bell().click();
  await wait(150);
  overrides.length = 2;                                 // the counts below are the ones of the first two touches
  q('#more [data-act="back"]') ? q('#more [data-act="back"]').click() : null;
  const more = q("#more");
  if (more.hasAttribute("open")) more.removeAttribute("open");
  await wait(100);

  // --- the Alerts window
  q("#btn-menu").click();
  await wait(100);
  const item = q("#menu [data-alerts]");
  check(!!item && !!item.querySelector("svg"), "nel menu c'e' la voce Avvisi, con la sua icona");
  item.click();
  await wait(200);
  const dlg = q("#alertsdlg");
  check(q("#menu").hidden && dlg.hasAttribute("open"), "la voce chiude il menu e apre la finestra");
  const head = dlg.querySelector(".al-top");
  check(head && head.firstElementChild.matches('button[data-al="close"]') && !!head.querySelector('[data-al="test"]'), "una pagina come Reti: in alto la X a sinistra, il titolo, «Invia una prova» a destra");
  const cssDir = path.join(__dirname, "..", "..", "vedetta", "app", "frontend", "ha", "css");
  const css = fs.readdirSync(cssDir).map((f) => fs.readFileSync(path.join(cssDir, f), "utf8")).join("\n");
  check(/#alertsdlg \{[^}]*position: fixed; inset: 0;[^}]*overflow: auto;[^}]*overscroll-behavior: contain/.test(css) && /html:has\(:is\(#netview, #alertsdlg\)\[open\]\) \{ overflow: hidden; \}/.test(css),
    "la pagina copre tutto e scorre da sola: dietro la pagina principale resta ferma (anche con Reti)");
  const sw = () => dlg.querySelector('[data-al="events"]');
  check(sw() && sw().getAttribute("role") === "switch" && sw().getAttribute("aria-checked") === "true", "l'interruttore degli eventi e' acceso (come sul server)");
  // the table of the recipients, in the style of Networks
  const rowsOf = () => Array.from(dlg.querySelectorAll(".al-rw")).map((r) => r.getAttribute("data-svc"));
  const rowOf = (s) => dlg.querySelector('.al-rw[data-svc="' + s + '"]');
  const num = (s) => rowOf(s).querySelector(".al-num").textContent;
  check(!!dlg.querySelector('.al-grid[role="table"]') && dlg.querySelectorAll('.al-hd [role="columnheader"]').length === 6, "una tabella come Reti, con sei colonne");
  check(rowsOf().join(",") === "notify.gone_phone,notify.mobile_app_pixel,notify.persistent_notification,notify.tv_salotto",
    "le righe: prima chi e' in fila, poi gli altri servizi di Home Assistant in ordine di nome: " + rowsOf().join(","));
  check(num("notify.gone_phone") === "1" && !!rowOf("notify.gone_phone").querySelector(".al-gone") && rowOf("notify.gone_phone").querySelector(".al-last.fail"),
    "un destinatario che HA non ha piu' resta al suo posto, segnato, con l'ultimo invio fallito");
  check(rowOf("notify.tv_salotto").textContent.indexOf("notify.") < 0 && rowOf("notify.tv_salotto").textContent.indexOf("tv_salotto") >= 0, "il nome si legge senza «notify.»");
  check(!!dlg.querySelector(".al-watch"), "una riga dice dove sta la campanella");
  const on = (s) => rowOf(s).querySelector("[data-al-on]");
  on("notify.tv_salotto").click();
  await wait(150);
  on("notify.mobile_app_pixel").click();
  await wait(150);
  on("notify.gone_phone").click();
  await wait(150);
  const lastSave = () => saves[saves.length - 1].notify_order;
  check(JSON.stringify(lastSave()) === JSON.stringify([{ service: "notify.tv_salotto", delay_s: 0 }, { service: "notify.mobile_app_pixel", delay_s: 0 }]),
    "gli interruttori mettono in fila nell'ordine dei tocchi; spento, esce dalla fila e il primo non aspetta: " + JSON.stringify(lastSave()));
  check(num("notify.tv_salotto") === "1" && num("notify.mobile_app_pixel") === "2" && on("notify.tv_salotto").getAttribute("aria-checked") === "true", "i numeri 1 e 2 sulle righe");
  const dd = () => rowOf("notify.mobile_app_pixel").querySelector("[data-al-dd]");
  check(!rowOf("notify.tv_salotto").querySelector("[data-al-dd]") && !!dd() && !dlg.querySelector("select"), "il primo parte subito; dal secondo si sceglie il ritardo (con il menu dell'app, non quello del browser)");
  dd().click();
  await wait(60);
  const menu = () => dlg.querySelector(".menu.al-menu");
  check(!!menu() && menu().querySelectorAll('.menu-item[role="menuitemradio"]').length === 6 && dd().getAttribute("aria-expanded") === "true" &&
    menu().querySelector('[aria-checked="true"]').getAttribute("data-al-wait") === "0", "il tasto apre il menu dell'app: sei ritardi, spuntato quello attuale");
  check(menu().style.width === Math.round(dd().getBoundingClientRect().width) + "px" && menu().style.left === Math.max(8, Math.round(dd().getBoundingClientRect().left)) + "px",      // 8 px from the screen's edge at least
    "il menu sta sotto il tasto e largo come lui: resta nella colonna Ritardo");
  dlg.querySelector(".al-hint").click();
  await wait(60);
  check(!menu() && dd().getAttribute("aria-expanded") === "false", "un tocco fuori chiude il menu");
  dd().click();
  await wait(60);
  const ev = new win.Event("cancel", { cancelable: true });
  dlg.dispatchEvent(ev);
  check(!menu() && ev.defaultPrevented && dlg.hasAttribute("open"), "Esc chiude prima il menu, la pagina resta aperta");
  dd().click();
  await wait(60);
  menu().querySelector('[data-al-wait="120"]').focus();
  menu().querySelector('[data-al-wait="120"]').click();
  await wait(150);
  check(!menu() && lastSave()[1].delay_s === 120 && /2/.test(dd().textContent), "la scelta chiude il menu e si salva subito: 2 min dopo il precedente");
  check(doc.activeElement === dd(), "dopo la scelta il punto torna sul tasto del ritardo (18/11)");
  // a phone (19/11 review): the button near the right edge, the menu stays on the screen; a sideways scroll of the table closes it
  const vwWas = Object.getOwnPropertyDescriptor(win.Element.prototype, "clientWidth");
  Object.defineProperty(doc.documentElement, "clientWidth", { configurable: true, get: () => 360 });
  const rectAt = (left) => () => ({ left, right: left + 132, top: 200, bottom: 232, width: 132, height: 32, x: left, y: 200 });
  dd().getBoundingClientRect = rectAt(300);
  dd().click();
  await wait(60);
  check(!!menu() && parseFloat(menu().style.left) + parseFloat(menu().style.width) <= 352 && parseFloat(menu().style.left) >= 8,
    "vicino al bordo destro il menu resta nello schermo (left " + (menu() && menu().style.left) + ")");
  const tw = dlg.querySelector(".al-tw");
  tw.dispatchEvent(new win.Event("scroll"));
  await wait(30);
  check(!menu() && dd().getAttribute("aria-expanded") === "false", "scorrere la tabella di lato chiude il menu (non resta sospeso lontano dal tasto)");
  dd().click();
  await wait(60);
  menu().dispatchEvent(new win.Event("scroll"));
  await wait(30);
  check(!!menu(), "scorrere dentro il menu non lo chiude");
  dlg.dispatchEvent(new win.Event("cancel", { cancelable: true }));
  delete doc.documentElement.clientWidth;
  if (vwWas) Object.defineProperty(win.Element.prototype, "clientWidth", vwWas);
  await wait(30);
  rowOf("notify.mobile_app_pixel").querySelector("[data-al-up]").focus();
  rowOf("notify.mobile_app_pixel").querySelector("[data-al-up]").click();
  await wait(150);
  // 18/11 review: the page is drawn again, the focus stays in the same row (the up arrow is now disabled: the down arrow of that row)
  check(doc.activeElement && doc.activeElement.getAttribute("data-al-down") === "notify.mobile_app_pixel", "dopo la freccia il punto resta sulla stessa riga (" + (doc.activeElement && doc.activeElement.outerHTML.slice(0, 60)) + ")");
  check(lastSave()[0].service === "notify.mobile_app_pixel" && lastSave()[0].delay_s === 0 && lastSave()[1].service === "notify.tv_salotto" && num("notify.mobile_app_pixel") === "1",
    "la freccia su lo porta primo (e il primo non aspetta)");
  check(rowOf("notify.mobile_app_pixel").querySelector("[data-al-up]").disabled && rowOf("notify.tv_salotto").querySelector("[data-al-down]").disabled, "il primo non sale, l'ultimo non scende");
  rowOf("notify.persistent_notification").querySelector("[data-al-try]").focus();
  rowOf("notify.persistent_notification").querySelector("[data-al-try]").click();
  await wait(150);
  check(doc.activeElement === rowOf("notify.persistent_notification").querySelector("[data-al-try]"), "dopo «Prova» il punto torna su «Prova», mai su una freccia (18/11: un secondo Invio spostava il destinatario)");
  check(tests.length === 1 && tests[0].service === "notify.persistent_notification" && rowOf("notify.persistent_notification").querySelector(".al-last.ok"), "«Prova» manda solo a quella riga e ne mostra l'esito");
  const saved = saves.length;
  sw().click();
  await wait(200);
  check(saves.length === saved + 1 && saves[saved].ha_events === false && sw().getAttribute("aria-checked") === "false", "l'interruttore degli eventi si salva subito");
  testAnswer = { ok: true, queued: 2 };
  dlg.querySelector('[data-al="test"]').focus();
  dlg.querySelector('[data-al="test"]').click();
  await wait(200);
  check(doc.activeElement === dlg.querySelector('[data-al="test"]'), "dopo «Invia una prova» il punto torna sul tasto (18/11)");
  check(tests.length === 2 && !("service" in tests[1]) && dlg.querySelector(".al-result.ok") && /2/.test(dlg.querySelector(".al-result.ok").textContent), "«Invia una prova» va a tutta la fila e dice quanti destinatari");
  check(/^[^.]+\. \S.*2/.test(dlg.querySelector(".al-result.ok").textContent), "due frasi separate da un punto, non attaccate (19/11): " + dlg.querySelector(".al-result.ok").textContent);
  testAnswer = { ok: false, error: "call_service: not_found Service not found" };
  dlg.querySelector('[data-al="test"]').click();
  await wait(200);
  const fail = dlg.querySelector(".al-result.fail");
  check(tests.length === 3 && fail && fail.textContent.indexOf("not_found") >= 0, "una prova rifiutata dice cosa ha risposto Home Assistant");
  testAnswer = { ok: false, error: "no_home_assistant" };
  dlg.querySelector('[data-al="test"]').click();
  await wait(200);
  check(dlg.querySelector(".al-result.fail") && dlg.querySelector(".al-result.fail").textContent.indexOf("no_home_assistant") < 0, "fuori da Home Assistant una frase, non il codice");
  testAnswer = "down";
  dlg.querySelector('[data-al="test"]').click();
  await wait(200);
  const down = dlg.querySelector(".al-result.fail");
  check(down && !/:\s*$/.test(down.textContent.trim()) && down.textContent.trim().length > 12, "la richiesta non arriva: una frase intera, non «Non inviata: » vuoto (19/11): " + (down && down.textContent));
  // two switches touched quickly on a slow Home Assistant: the saves go one after the other, the page ends as the server (19/11 review)
  const shown = () => ["notify.mobile_app_pixel", "notify.persistent_notification", "notify.tv_salotto"].map((x) => on(x).getAttribute("aria-checked") === "true");
  const server = () => ["notify.mobile_app_pixel", "notify.persistent_notification", "notify.tv_salotto"].map((x) => cfg.notify_order.some((o) => o.service === x));
  let releaseSave;
  sentinelHold = new Promise((r) => { releaseSave = r; });
  const sent = saves.length;
  on("notify.persistent_notification").click();
  await wait(30);
  on("notify.tv_salotto").click();
  await wait(30);
  check(saves.length === sent + 1, "the second save waits for the first (" + (saves.length - sent) + " sent)");
  sentinelHold = null;
  releaseSave();
  await wait(200);
  check(saves.length === sent + 2 && JSON.stringify(shown()) === JSON.stringify(server()), "both saved, the page shows what the server has: " + JSON.stringify(shown()) + " / " + JSON.stringify(server()));
  // the first of two fails: the second is still saved, the page is read again and shows what the server has
  sentinelHold = "fail";
  on("notify.persistent_notification").click();
  await wait(10);
  on("notify.mobile_app_pixel").click();
  await wait(300);
  check(JSON.stringify(shown()) === JSON.stringify(server()), "after a refused save the page shows what the server has: " + JSON.stringify(shown()) + " / " + JSON.stringify(server()));
  dlg.querySelector('.al-top [data-al="close"]').click();
  await wait(50);
  check(!dlg.hasAttribute("open"), "la X chiude la pagina");
  check(errors.length === 0, "nessun errore nella pagina" + (errors.length ? ": " + errors[0] : ""));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
