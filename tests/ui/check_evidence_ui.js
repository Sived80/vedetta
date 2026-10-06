// Evidence on the rows Name, Brand and Type of the device sheet: bar + certainty + (i) that opens a small pop-up,
// closed by pressing outside it. Needs jsdom (npm install in this folder); without it the check is skipped.
//   from the vedetta/ folder:  node ../tests/ui/check_evidence_ui.js
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
const css = fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "static", "ha", "ha.css"), "utf8");
const IT = lang === "it";

const EV = {
  name: { value: "Router casa", certainty: 65, basis: "source", source: "upnp", placeholder: false, rejected: [{ source: "dhcp", value: "esp32-abc", cleaned: null }] },
  brand: { value: "TP-Link", certainty: 45, basis: "found", source: "oui", rejected: [{ kind: "vendor", value: "Espressif", role: "component" }] },
  group: { value: "router", certainty: 83, basis: "scored", reason: null, clues: [{ source: "ruolo di rete", points: 10 }], rejected: [{ value: "iot", points: 3, why: "behind" }] },
};
let evCalls = 0;
const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
vc.on("error", (e) => errors.push("console.error: " + e));
const sources = [];
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
  beforeParse(win) {
    win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); this.dispatchEvent(new win.Event("close")); };
    win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
    win.fetch = (url) => {
      let body = {};
      if (url.includes("/evidence")) { evCalls++; body = EV; }
      else if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) body = data.devices;
      else if (url.startsWith("/api/ha/summary")) body = data.summary;
      else if (url.startsWith("/api/ha/logbook")) body = data.logbook;
      else if (url.startsWith("/api/ha/history?")) body = data.history_all;
      else if (url.startsWith("/api/ha/history/")) { const id = url.split("/")[4].split("?")[0]; body = Object.assign({ device_id: id }, url.includes("hours=168") ? data.history_7d[id] : data.history_all.devices[id]); }
      return Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(body) });
    };
    win.EventSource = class {
      constructor(url) { this.url = url; this.l = {}; sources.push(this); setTimeout(() => this.onopen && this.onopen(), 5); }
      addEventListener(n, f) { this.l[n] = f; } close() {}
      emit(n, obj) { this.l[n]({ data: JSON.stringify(obj) }); }
    };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const win = dom.window, doc = win.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const q = (s) => doc.querySelector(s), qa = (s) => Array.from(doc.querySelectorAll(s));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }
const ev = (type, target, init) => target.dispatchEvent(new win.Event(type, Object.assign({ bubbles: true, cancelable: true }, init || {})));
const key = (k) => doc.dispatchEvent(new win.KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));

(async () => {
  await wait(800);
  q('.tile[data-id="d1"]').click();
  await wait(500);

  // --- the three rows replace the separate card: no duplicate, same list, same width as the attributes
  check(!q("#mi-evidence"), "nessuna scheda 'Prove' separata");
  const labels = qa("#mi-attrs .attr dt").map((x) => x.textContent);
  check(labels.slice(0, 3).join() === (IT ? "Nome,Marca,Tipo" : "Name,Brand,Type"), "le prime tre righe: " + labels.slice(0, 3).join());
  check(labels.filter((l) => l === (IT ? "Marca" : "Brand")).length === 1 && labels.filter((l) => l === (IT ? "Tipo" : "Type")).length === 1, "Marca e Tipo compaiono una volta sola (anche aprendo 'Altri attributi')");
  check(qa("#mi-attrs .attr.ev-attr").length === 3 && qa("#mi-attrs .attr.ev-attr .ev-bar").length === 3, "tre righe con barra sottile");
  const sheetText = q("dialog#more").textContent.toLowerCase();
  check(!sheetText.includes("perch") && !sheetText.includes("why"), "nessuna scritta 'perché' nella scheda");
  check(qa("#mi-attrs .attr").every((r) => r.parentElement === q("#mi-attrs") || r.closest("#attr-more")), "tutte le righe stanno nello stesso elenco degli attributi");

  // --- values and numbers
  const val = (k) => q('[data-ev-v="' + k + '"]').textContent;
  const pct = (k) => q('[data-ev-pct="' + k + '"]').textContent;
  check(val("name") === "Router casa" && val("brand") === "TP-Link" && val("group").length > 0, "valori nelle tre righe: " + [val("name"), val("brand"), val("group")].join(" | "));
  check(pct("name") === "65%" && pct("brand") === "45%" && pct("group") === "83%", "percentuali: " + [pct("name"), pct("brand"), pct("group")].join(" "));
  check(qa("#mi-attrs .ev-bar i").map((i) => i.style.width).join() === "65%,45%,83%", "larghezza delle barre");
  check(q('[data-ev-bar="brand"]').className.includes("lvl-mid") && q('[data-ev-bar="group"]').className.includes("lvl-high"), "colore per livello");
  check(qa("[data-ev-i]").length === 3 && qa("[data-ev-i]").every((b) => b.closest(".ev-line") && b.previousElementSibling.classList.contains("ev-pct")), "la (i) sta subito dopo la percentuale, sulla stessa riga");

  check(qa("[data-ev-i] path").every((p) => (p.getAttribute("d") || "").startsWith("M11,9H13V7H11")), "la (i) ha il disegno di 'informazioni', non un'icona generica");

  // --- it does not move: the space of percentage and (i) is fixed in the CSS, a longer number takes no extra width
  const rule = (sel) => (css.match(new RegExp(sel.replace(/[.]/g, "\\.") + "\\s*\\{([^}]*)\\}")) || [, ""])[1];
  check(/width:\s*3\.4em/.test(rule(".ev-pct")) && /text-align:\s*right/.test(rule(".ev-pct")) && /tabular-nums/.test(rule(".ev-pct")), "percentuale: larghezza fissa, allineata a destra, cifre tabulari");
  check(/flex:\s*none/.test(rule(".ev-i")) && /width:\s*32px/.test(rule(".ev-i")), "(i): dimensione fissa");
  check(/min-height:\s*32px/.test(rule(".ev-line")) && /height:\s*4px/.test(rule(".ev-bar")), "riga e barra: altezza fissa");
  // the value changes (certainty 5 -> 100): only the text and the bar change
  EV.name.certainty = 5; EV.group.certainty = 100;
  ev("click", q("#mi-attrs"));
  sources[sources.length - 1].emit("device", { type: "device", rev: 5, device: Object.assign({}, data.devices.devices[0], { name: "Router salotto" }) });
  await wait(300);
  check(val("name") === "Router salotto", "rinominare aggiorna il valore nella riga");
  EV.name.value = "Router salotto";
  await wait(50);
  check(pct("name") === "5%" && pct("group") === "100%" && q('[data-ev-bar="group"] i').style.width === "100%", "nuovi numeri: " + [pct("name"), pct("group")].join(" "));
  EV.name.certainty = 65; EV.group.certainty = 83;

  // --- the pop-up
  const btn = (k) => q('[data-ev-i="' + k + '"]');
  const pop = () => q("#ev-pop");
  const popText = () => (pop() ? pop().textContent : "");
  btn("brand").click();
  check(!!pop() && !!pop().closest("dialog#more") && btn("brand").getAttribute("aria-expanded") === "true", "(i) apre un pop-up dentro la scheda");
  check(popText().includes("45%") && popText().includes("Espressif") && popText().includes(IT ? "Ipotesi scartate (1)" : "Rejected hypotheses (1)"), "il pop-up spiega e mostra l'ipotesi scartata");
  check(qa("#ev-pop").length === 1, "un solo pop-up");
  if (pop()) { ev("click", pop()); ev("mousedown", pop()); }
  check(!!pop(), "premere dentro il pop-up non lo chiude");
  btn("group").click();
  check(qa("#ev-pop").length === 1 && popText().includes("83%") && btn("brand").getAttribute("aria-expanded") === "false", "un'altra (i) sposta il pop-up, non ne crea due");
  btn("group").click();
  check(!pop(), "premere di nuovo la stessa (i) lo chiude");
  btn("name").click();
  check(!!pop(), "riaperto");
  ev("mousedown", q(".mi-title"));
  check(!pop() && btn("name").getAttribute("aria-expanded") === "false", "premere fuori (titolo) lo chiude");
  btn("name").click();
  ev("pointerdown", q("#mi-attrs"));
  check(!pop(), "premere fuori (elenco) lo chiude");
  btn("brand").click();
  ev("pointerdown", q("dialog#more"));
  check(!pop(), "premere sullo sfondo della finestra lo chiude");
  btn("brand").click();
  key("Escape");
  check(!pop() && q("dialog#more").hasAttribute("open"), "Esc chiude il pop-up e non la scheda");
  btn("brand").click();
  q(".mi-body").dispatchEvent(new win.Event("scroll"));
  check(!pop(), "scorrere la scheda lo chiude");
  btn("brand").click();
  q("dialog#more").dispatchEvent(new win.Event("close"));
  check(!pop(), "chiudere la scheda lo chiude");
  ev("mousedown", doc.body);

  if (errors.length) console.log(errors.join(String.fromCharCode(10)));
  console.log("richieste di prove al server:", evCalls);
  check(evCalls >= 1 && evCalls <= 4, "poche richieste al server (" + evCalls + ")");
  check(errors.length === 0, errors.length ? errors.join("\n") : "nessun errore nella pagina");
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
