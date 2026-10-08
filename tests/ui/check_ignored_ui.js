// The "Ignored devices" window: rows with only the three dots (Restore, Forget), each with its own 5 s countdown (the pressed item becomes Undo),
// the lock of the group buttons, a notice at the end without Undo, guided typing (colons of a MAC, right arrow = dot in an IP), the + panel.
// Needs jsdom (see check_evidence_ui.js).
// from the vedetta/ folder:  node ../tests/ui/check_ignored_ui.js [it|en]
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

// the server, in memory
const srv = {
  items: [{ id: "a1", kind: "ip", value: "192.168.1.50", label: "Cam garage" }, { id: "a2", kind: "name", value: "iphone-ale", label: "iPhone di Ale" }],
  macs: [{ mac: "AA:BB:CC:00:00:01", ip: "192.168.1.21", hostname: "tv-salotto", vendor: "Acme" }, { mac: "AA:BB:CC:00:00:02", ip: "192.168.1.22", hostname: "", vendor: "Foo" }],
  calls: [],
};
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
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      const method = (opts && opts.method) || "GET", body = opts && opts.body ? JSON.parse(opts.body) : null;
      let b = {};
      const u = url.split("?")[0];
      if (u === "/api/ignored" && method === "GET") b = { items: srv.items };
      else if (u === "/api/ignored" && method === "POST") { srv.calls.push(["add", body]); srv.items = srv.items.concat([{ id: "n" + srv.items.length, kind: body.kind, value: body.value, label: body.label }]); b = { items: srv.items }; }
      else if (u.startsWith("/api/ignored/") && method === "DELETE") { const id = decodeURIComponent(u.split("/").pop()); srv.calls.push(["restore-item", id]); srv.items = srv.items.filter((x) => x.id !== id); b = { items: srv.items }; }
      else if (u === "/api/ignored/forget") { srv.calls.push(["forget", body]); srv.items = srv.items.filter((x) => x.id !== body.id); srv.macs = srv.macs.filter((x) => x.mac !== body.mac); b = { items: srv.items, macs: srv.macs }; }
      else if (u === "/api/new-devices/ignored") b = srv.macs;
      else if (u === "/api/new-devices/unignore") { srv.calls.push(["restore-mac", body.mac]); srv.macs = srv.macs.filter((x) => x.mac !== body.mac); b = srv.macs; }
      else if (u.startsWith("/api/ha/devices") && !u.includes("/debug")) b = data.devices;
      else if (u.startsWith("/api/ha/summary")) b = data.summary;
      else if (u.startsWith("/api/ha/logbook")) b = data.logbook;
      else if (u.startsWith("/api/ha/history?")) b = data.history_all;
      return ok(b);
    };
    win.EventSource = class { constructor() { setTimeout(() => this.onopen && this.onopen(), 5); } addEventListener() {} close() {} };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const win = dom.window, doc = win.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }
const dlg = () => doc.getElementById("ignored");
const rows = () => Array.from(dlg().querySelectorAll(".ig-item"));
const dots = (i) => rows()[i].querySelector('[data-ign="more"]');
const menuItems = () => Array.from(dlg().querySelectorAll(".ig-menu .menu-item"));
const bulk = (k) => dlg().querySelector('[data-bulk="' + k + '"]');
const outside = () => dlg().querySelector(".mi-title").dispatchEvent(new win.MouseEvent("pointerdown", { bubbles: true }));
const off = (el) => el.getAttribute("aria-disabled") === "true";
const snacks = () => Array.from(doc.querySelectorAll(".snack")).map((s) => s.textContent);

(async () => {
  await wait(800);
  doc.getElementById("btn-menu").click();
  doc.querySelector("#menu [data-ignored]").click();
  await wait(300);
  check(dlg().hasAttribute("open"), "la finestra si apre");
  check(rows().length === 4, "quattro righe (due dalla ricerca, due dalla rete)");
  check(rows().every((r) => r.querySelectorAll("button").length === 1 && r.querySelector('[data-ign="more"]')), "ogni riga ha solo i tre puntini a destra");
  check(!!dlg().querySelector(".ig-add-btn.icon-btn") && !dlg().querySelector(".ig-count"), "il + e' un tasto rotondo e il conteggio non c'e'");
  check(!!bulk("restore") && !!bulk("forget"), "in basso ci sono Ripristina tutti e Dimentica tutti");

  // row 0: Forget; row 1: Restore; row 2: Forget then Undo. All together.
  dots(0).click(); await wait(50);
  check(menuItems().length === 2, "il menu ha due voci: Ripristina e Dimentica");
  menuItems()[1].click(); await wait(50);
  const c0 = dlg().querySelector(".ig-menu .menu-item.counting");
  check(c0 && c0.querySelector(".fill") && c0.querySelectorAll(".mdi").length === 1 && off(menuItems()[0]), "Dimentica diventa Annulla con il colore che scorre, l'altra voce e' spenta");
  check(srv.calls.length === 0, "finche' il conto corre il server non viene toccato");
  outside(); await wait(50);
  check(!dlg().querySelector(".ig-menu"), "fuori dal menu: il menu si chiude");
  check(off(bulk("restore")) && off(bulk("forget")), "con un conto in corso i tasti di gruppo sono spenti");
  bulk("forget").click(); await wait(50);
  check(!dlg().querySelector(".ig-all.counting"), "e un clic sui tasti di gruppo non fa partire nulla");

  dots(1).click(); await wait(50);
  check(menuItems().every((x) => !off(x)), "il menu di un'altra riga e' libero (i conti sono indipendenti)");
  menuItems()[0].click(); await wait(50);   // restore row 1
  outside(); await wait(50);

  dots(2).click(); await wait(50);
  menuItems()[1].click(); await wait(300);
  dlg().querySelector(".ig-menu .menu-item.counting").click(); await wait(50);   // Undo
  check(!!dlg().querySelector(".ig-menu") && menuItems().every((x) => !off(x) && !x.classList.contains("counting")), "Annulla lascia il menu aperto, con le due voci attive");
  outside(); await wait(50);

  dots(0).click(); await wait(50);
  check(!!dlg().querySelector(".ig-menu .menu-item.counting"), "rientrando nei tre puntini della riga, il conto e' ancora li' (si puo' annullare)");
  outside(); await wait(50);

  check(rows().length === 4, "durante il conto le righe sono ancora tutte in lista");
  await wait(5300);
  check(rows().length === 2 && srv.calls.some((c) => c[0] === "forget" && c[1].id === "a1") && srv.calls.some((c) => c[0] === "restore-item" && c[1] === "a2"), "alla fine le due righe spariscono e il server riceve Dimentica e Ripristina");
  check(!srv.calls.some((c) => (c[1] && (c[1].mac === "AA:BB:CC:00:00:01")) || c[1] === "AA:BB:CC:00:00:01"), "la riga annullata non e' stata toccata");
  const sn = snacks();
  check(sn.some((s) => /a1|Cam garage/.test(s)) && sn.some((s) => /iPhone di Ale/.test(s)), "due notifiche con il nome del dispositivo");
  check(!doc.querySelector(".snack .snack-action"), "le notifiche non hanno il pulsante Annulla");
  check(!off(bulk("restore")) && !off(bulk("forget")), "finiti i conti, i tasti di gruppo si riaccendono");

  // guided typing, in the + panel
  dlg().querySelector(".ig-add-btn").click(); await wait(100);
  const f = dlg().querySelector(".ig-field");
  f.value = "aabbccd"; f.setSelectionRange(7, 7); f.dispatchEvent(new win.Event("input", { bubbles: true }));
  check(f.value === "AA:BB:CC:D", "nel MAC i due punti compaiono da soli (" + f.value + ")");
  dlg().querySelector('[data-ign-kind="ip"]').click(); await wait(20);
  f.value = "192.16"; f.setSelectionRange(6, 6); f.dispatchEvent(new win.Event("input", { bubbles: true }));
  const arrow = () => f.dispatchEvent(new win.KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true }));
  arrow(); f.value += "1"; f.setSelectionRange(f.value.length, f.value.length); f.dispatchEvent(new win.Event("input", { bubbles: true })); arrow();
  f.value += "12"; f.setSelectionRange(f.value.length, f.value.length); f.dispatchEvent(new win.Event("input", { bubbles: true }));
  check(f.value === "192.16.1.12", "nell'IP la freccia destra scrive il punto: " + f.value);
  f.value = "192."; f.setSelectionRange(4, 4); const before = f.value; arrow();
  check(f.value === before, "la freccia non aggiunge un secondo punto dopo un punto");
  dlg().querySelector('[data-ign-kind="mac"]').click(); await wait(20);
  f.value = "AABBCCDDEEFF"; f.dispatchEvent(new win.Event("input", { bubbles: true }));
  dlg().querySelector(".ig-add").dispatchEvent(new win.Event("submit", { bubbles: true, cancelable: true })); await wait(200);
  check(srv.calls.some((c) => c[0] === "add" && c[1].kind === "mac" && c[1].value === "AA:BB:CC:DD:EE:FF"), "l'aggiunta a mano invia il MAC con i due punti");
  check(rows().length === 3, "la riga nuova compare in cima");

  // the group buttons: undo, then to the end
  bulk("forget").click(); await wait(50);
  check(bulk("forget").classList.contains("counting") && off(bulk("restore")), "Dimentica tutti diventa Annulla e Ripristina tutti si spegne");
  dots(0).click(); await wait(50);
  check(menuItems().every(off), "durante il conto di gruppo le voci delle righe sono spente");
  outside(); await wait(50);
  bulk("forget").click(); await wait(50);
  check(!bulk("forget").classList.contains("counting") && !off(bulk("restore")), "premendo Annulla il gruppo torna com'era");
  bulk("forget").click(); await wait(5400);
  check(rows().length === 0 && dlg().querySelector(".ig-empty").classList.contains("on"), "a fine conto di gruppo le righe spariscono e compare lo stato vuoto");
  check(snacks().some((s) => /3/.test(s)), "una sola notifica con il numero");
  check(errors.length === 0, "nessun errore nella pagina" + (errors.length ? ": " + errors.join("; ") : ""));
  console.log(failed ? "FALLITO: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
