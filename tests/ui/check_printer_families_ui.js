// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The printer group and its two families (1.1.1, chosen by the person: a subgroup of Printers, like the families of the smart home group; Home
// Assistant keeps seeing "printer"): with paper printers and two 3D printers the group shows two subtitles, printers then 3D printers, each
// with its cards and its count, in the card view and in the list view; with one family only the subtitle is hidden (a lone «Printers» under
// «Printers» says nothing). When the printer group is chosen in the ring, chips of its two families narrow the list. A printer card has a
// «Family» picker with Auto and the two printer families only (no smart home family); the choice is saved and moves the card at once.
// Invented devices only.   Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_printer_families_ui.js [it|en]
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

// invented devices: two paper printers (one with no family from the server: it is a printer) and two 3D printers, next to the page's own
const base = data.devices.devices[0];
const list = data.devices.devices.filter((d) => d.type !== "printer");
data.devices.devices = list;
let n = 30;
function add(extra) {
  n++;
  list.push(Object.assign({}, base, { id: "d" + n, name: "Dev " + n, ip: "192.0.2." + n, mac: "02:00:00:00:00:" + n, type: "printer", family: null, family_user: null,
    type_user: null, icon: null, brand: null, vendor: null, logo: null }, extra));
}
add({ name: "Ufficio", family: "printers", icon: "printer" });
add({ name: "Filamento garage", family: "printer3d", icon: "printer-3d" });
add({ name: "Resina", family: "printer3d", icon: "printer-3d" });
add({ name: "Etichette", family: null, icon: "printer" });

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
      if (opts && opts.method === "POST") posted.push({ url, body: JSON.parse(opts.body || "{}") });
      const ok = (b) => Promise.resolve({ ok: true, status: 200, headers: { get: () => null }, blob: () => Promise.resolve(new win.Blob([""])), json: () => Promise.resolve(b), text: () => Promise.resolve(JSON.stringify(b)) });
      let b = {};
      if (url.startsWith("/api/settings")) b = { alerts: true, poll_interval: 30, miss_limit: 3, phone_hold_ha: true, group_order: [] };
      else if (url.includes("/evidence")) b = { name: { basis: "unknown", certainty: 0, rejected: [] }, brand: { basis: "none", certainty: 0, rejected: [] }, group: { basis: "none", certainty: 0, rejected: [], clues: [], value: "printer" } };
      else if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
      else if (url.startsWith("/api/ha/summary")) b = data.summary;
      else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
      else if (url.startsWith("/api/ha/history?")) b = data.history_all;
      else if (url.includes("/override")) b = { ok: true };
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
const shownTiles = () => [...doc.querySelectorAll("#groups .tile")].filter((el) => el.isConnected).map((el) => el.dataset.id);
const group = () => doc.querySelector('#groups section.group[data-type="printer"]');
const visibleFams = () => [...group().querySelectorAll(".fam")].filter((f) => !f.querySelector(".fam-head").hidden).map((f) => f.dataset.family);
const tilesIn = (family) => { const f = group().querySelector('.fam[data-family="' + family + '"]'); return f ? [...f.querySelectorAll(".tile")].map((t) => t.dataset.id).sort().join() : ""; };

async function chooseFamily(id, family) {
  doc.querySelector('#groups .tile[data-id="' + id + '"]').click();
  await wait(150);
  const dlg = doc.getElementById("more");
  const btn = dlg.querySelector('[data-act="family-menu"]');
  if (btn) {
    btn.click();
    await wait(40);
    dlg.querySelector('.type-menu [data-family="' + family + '"]').click();
    await wait(120);
  }
  if (dlg.querySelector('[data-act="close"]')) dlg.querySelector('[data-act="close"]').click();
  await wait(60);
  return !!btn;
}

(async () => {
  await wait(900);
  check(!!group() && group().querySelector(".hd-title").textContent === LOCALE["js.ha.type.printer"], "the printer group keeps its name");
  check(visibleFams().join() === "printers,printer3d", "two subtitles, printers then 3D printers: " + visibleFams().join());
  const titles = [...group().querySelectorAll(".fam .fam-title")].map((h) => h.textContent);
  check(titles.join("|") === [LOCALE["js.ha.family.printers"], LOCALE["js.ha.family.printer3d"]].join("|"), "each has its name: " + titles.join("|"));
  const fam3d = group().querySelector('.fam[data-family="printer3d"]');
  check(tilesIn("printer3d") === "d32,d33" && fam3d.querySelector(".fam-count").textContent === "2", "the 3D printers are under their subtitle, with their count");
  check(tilesIn("printers") === "d31,d34", "a printer with no family is with the printers: " + tilesIn("printers"));
  const famPaper = group().querySelector('.fam[data-family="printers"]');
  check(!!fam3d.querySelector(".fam-ic svg") && fam3d.querySelector(".fam-ic").innerHTML !== famPaper.querySelector(".fam-ic").innerHTML, "each subtitle has its own icon");
  doc.documentElement.setAttribute("data-view", "list");
  check([...group().querySelectorAll(".fam > .tiles")].length === 2, "in the list view each family is its own list");
  doc.documentElement.removeAttribute("data-view");
  const home = doc.querySelector('#groups section.group[data-type="iot"]');
  check(!home || [...home.querySelectorAll(".fam")].every((f) => ["printers", "printer3d"].indexOf(f.dataset.family) < 0), "the smart home group has no printer family");

  // the chips of the printer group
  const chips = () => doc.getElementById("fam-chips");
  const seg = doc.querySelector('#g-types .g-seg[data-k="printer"]');
  check(!!seg, "the ring has the printer group");
  seg.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await wait(80);
  const chipKeys = [...chips().querySelectorAll("[data-family]")].map((c) => c.dataset.family);
  check(!chips().hidden && chipKeys.join() === "printers,printer3d", "the printer group chosen: chips of its two families: " + chipKeys.join());
  chips().querySelector('[data-family="printer3d"]').click();
  await wait(80);
  check(shownTiles().sort().join() === "d32,d33", "the chip of the 3D printers narrows to them: " + shownTiles().join());
  seg.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await wait(80);
  check(chips().hidden && shownTiles().length === list.length, "the group let go: every card again");

  // the family of a printer card, chosen by hand
  doc.querySelector('#groups .tile[data-id="d32"]').click();
  await wait(150);
  const dlg = doc.getElementById("more");
  const famBtn = dlg.querySelector('[data-act="family-menu"]');
  check(!!famBtn && famBtn.closest(".attr").textContent.indexOf(LOCALE["js.ha.family.printer3d"]) >= 0, "a printer card has the family row, with its family");
  if (famBtn) {
    famBtn.click();
    await wait(40);
    const items = [...dlg.querySelectorAll(".type-menu [data-family]")].map((b) => b.dataset.family);
    check(items.join() === ",printers,printer3d", "the family picker: Auto and the two printer families, no smart home one: " + items.join());
    famBtn.click();
    await wait(40);
  }
  if (dlg.querySelector('[data-act="close"]')) dlg.querySelector('[data-act="close"]').click();
  await wait(60);
  await chooseFamily("d32", "printers");
  const last = posted[posted.length - 1];
  check(last && /\/api\/devices\/d32\/override$/.test(last.url) && JSON.stringify(last.body) === '{"family":"printers"}', "the choice is saved: " + JSON.stringify(last));
  check(tilesIn("printers").split(",").indexOf("d32") >= 0 && visibleFams().join() === "printers,printer3d", "and the card moves at once: " + tilesIn("printers"));

  // one family left with devices: no subtitle (the cards look as in any other group)
  await chooseFamily("d33", "printers");
  check(visibleFams().length === 0 && group().querySelectorAll(".tile").length === 4, "only printers left: no subtitle, every card still in the group: " + visibleFams().join());
  seg.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await wait(80);
  check(chips().hidden, "and no chips for a single family");
  seg.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await wait(80);

  const css = fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "frontend", "ha", "css", "50-tile.css"), "utf8");
  check(/\.fam-head\[hidden\][^{]*\{[^}]*display:\s*none/.test(css), "a hidden subtitle is really hidden (its display:flex does not win over hidden)");

  // the names of the two families in the five languages
  ["en", "it", "de", "cs", "fr"].forEach((l) => {
    const loc = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "locales", l, "ha.json"), "utf8"));
    check(!!loc["js.ha.family.printers"] && !!loc["js.ha.family.printer3d"] && loc["js.ha.family.printer3d"] !== loc["js.ha.family.printers"], l + ": the two printer families have a name");
  });
  check(errors.length === 0, "no error in the page: " + errors.join(" | "));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
