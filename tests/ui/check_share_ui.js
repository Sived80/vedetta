// The button that shares a device with Home Assistant (MQTT) in the open card: when the link with MQTT is not active (no broker, publishing off) it stays where it is but is disabled - no message, no other change of
// look (the same classes, the same icon, the same word) - and it works when the link is active. The page learns it from the summary (S.mqtt.active). Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_share_ui.js [it|en]
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

function openPage(mqtt, failSave) {
  const errors = [], posts = [];
  const local = JSON.parse(JSON.stringify(data));          // each page has its own copy: a click that saves would change the data of the next page
  for (const d of local.devices.devices) if (d.id === "d2") d.ha_share = false;
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
        let b = {};
        if (url.includes("/override") && failSave) { posts.push(JSON.parse(opts.body)); return Promise.resolve({ ok: false, status: 500, headers: { get: () => null }, json: () => Promise.resolve({}), text: () => Promise.resolve("{}") }); }
        if (url.includes("/override")) { posts.push(JSON.parse(opts.body)); b = { ok: true }; }
        else if (url.startsWith("/api/ha/devices") && !url.includes("/debug") && !url.includes("/evidence")) b = local.devices;
        else if (url.startsWith("/api/ha/summary")) b = Object.assign({}, local.summary, { mqtt: mqtt });
        else if (url.includes("/evidence")) b = { name: { basis: "unknown", certainty: 0, rejected: [] }, brand: { basis: "none", certainty: 0, rejected: [] }, group: { basis: "none", certainty: 0, rejected: [], clues: [], value: "generic" } };
        else if (url.startsWith("/api/ha/logbook")) b = local.logbook;
        else if (url.startsWith("/api/ha/history?")) b = local.history_all;
        return ok(b);
      };
      win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
      win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
    },
  });
  return { dom, errors, posts };
}

(async () => {
  // --- link not active: the button is there, disabled, with no message and the look it always had
  const off = openPage({ active: false, connected: false });
  await wait(800);
  off.dom.window.document.querySelector('.tile[data-id="d2"]').click();
  await wait(400);
  const btnOff = off.dom.window.document.querySelector('#more [data-act="share"]');
  check(!!btnOff, "MQTT non attivo: il tasto di condivisione c'e' ancora");
  check(!!btnOff && btnOff.disabled, "MQTT non attivo: il tasto e' disattivato");
  check(!!btnOff && !btnOff.hasAttribute("title") && !btnOff.hasAttribute("aria-label"), "MQTT non attivo: nessun messaggio (ne' suggerimento)");
  check(!!btnOff && btnOff.className === "btn tonal rp" && !!btnOff.querySelector("svg") && !!btnOff.querySelector("span").textContent.trim(), "la grafica e' quella di sempre: stesse classi, stessa icona, stessa parola ('" + (btnOff && btnOff.textContent.trim()) + "')");
  btnOff && btnOff.click();
  await wait(200);
  check(off.posts.length === 0, "un clic sul tasto disattivato non salva nulla");
  check(off.errors.length === 0, "nessun errore nella pagina (MQTT non attivo)" + (off.errors.length ? ": " + off.errors.join("; ") : ""));
  off.dom.window.close();

  // --- link active: the button works as it always did
  const on = openPage({ active: true, connected: true });
  await wait(800);
  on.dom.window.document.querySelector('.tile[data-id="d2"]').click();
  await wait(400);
  const btnOn = on.dom.window.document.querySelector('#more [data-act="share"]');
  check(!!btnOn && !btnOn.disabled && !btnOn.hasAttribute("title"), "MQTT attivo: il tasto e' attivo e senza suggerimenti");
  check(!!btnOn && btnOn.className === btnOff.className, "stessa grafica con MQTT attivo e non attivo");
  btnOn.click();
  await wait(300);
  check(on.posts.length === 1 && on.posts[0].ha_share === true, "MQTT attivo: il clic salva la condivisione");
  check(on.errors.length === 0, "nessun errore nella pagina (MQTT attivo)" + (on.errors.length ? ": " + on.errors.join("; ") : ""));
  // the message says what happened: shared after sharing, removed after removing (it was the other way round: the card was updated before the message was chosen)
  const texts = (page) => Array.from(page.dom.window.document.querySelectorAll(".snack .snack-text")).map((n) => n.textContent);
  const words = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "locales", lang, "ha.json"), "utf8"));
  check(JSON.stringify(texts(on)) === JSON.stringify([words["js.ha.share.added"]]), "dopo aver condiviso il messaggio dice «" + words["js.ha.share.added"] + "» (dice: " + JSON.stringify(texts(on)) + ")");
  on.dom.window.document.querySelector('#more [data-act="share"]').click();
  await wait(300);
  check(on.posts.length === 2 && on.posts[1].ha_share === false, "il secondo clic toglie la condivisione");
  check(JSON.stringify(texts(on).slice(-1)) === JSON.stringify([words["js.ha.share.removed"]]), "dopo aver tolto la condivisione il messaggio dice «" + words["js.ha.share.removed"] + "» (dice: " + JSON.stringify(texts(on)) + ")");
  on.dom.window.close();

  // --- the save fails: the error is told, and the success message is NOT shown as well
  const bad = openPage({ active: true, connected: true }, true);
  await wait(800);
  bad.dom.window.document.querySelector('.tile[data-id="d2"]').click();
  await wait(400);
  bad.dom.window.document.querySelector('#more [data-act="share"]').click();
  await wait(300);
  check(bad.dom.window.document.querySelectorAll(".snack.error").length === 1, "salvataggio non riuscito: un messaggio di errore");
  check(!texts(bad).includes(words["js.ha.share.added"]) && !texts(bad).includes(words["js.ha.share.removed"]), "salvataggio non riuscito: nessun messaggio di successo (dice: " + JSON.stringify(texts(bad)) + ")");
  bad.dom.window.close();

  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
