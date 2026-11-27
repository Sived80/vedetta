// The smart home group and its families (1.0.4): the page has the ten groups Home Assistant sees; inside «Smart home» the devices are shown
// under the subtitles of their families (lights, climate, security, energy as in the Home dashboard of Home Assistant, appliances, other), only the families that have devices, in a fixed order. When the smart home
// group is chosen in the ring, chips of its families narrow the list further. The ring shows only the groups present: beyond seven, the
// smallest after the sixth become one grey «Others» arc, shown last; a group keeps its colour and no group is red (red is offline). The
// type of a card is chosen among Auto + the ten groups; a smart home card has a «Family» picker too.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_families_ui.js [it|en]
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

// invented devices: two climate cards and one light in the smart home group, and one device in each of seven other groups
const base = data.devices.devices[0];
const list = data.devices.devices;
const light = list.find((d) => d.type === "iot");
Object.assign(light, { family: "lights" });
let n = 20;
function add(type, extra) {
  n++;
  list.push(Object.assign({}, base, { id: "d" + n, name: "Dev " + n, ip: "192.0.2." + n, mac: "02:00:00:00:00:" + n, type: type, family: null, family_user: null,
    type_user: null, icon: null, brand: null, vendor: null, logo: null }, extra || {}));
}
add("iot", { name: "Caldaia", family: "climate", icon: "water-boiler" });
add("iot", { name: "Termostato", family: "climate", icon: "thermostat" });
add("iot", { name: "Altra luce", family: "lights", icon: "lightbulb" });
["server", "pc", "media", "audio", "printer", "camera", "generic"].forEach((g) => add(g));
add("server");
add("server");

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
      else if (url.includes("/evidence")) b = { name: { basis: "unknown", certainty: 0, rejected: [] }, brand: { basis: "none", certainty: 0, rejected: [] }, group: { basis: "none", certainty: 0, rejected: [], clues: [], value: "iot" } };
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

(async () => {
  await wait(900);
  // ---- the smart home group and its families
  const home = doc.querySelector('#groups section.group[data-type="iot"]');
  check(!!home && home.querySelector(".hd-title").textContent === LOCALE["js.ha.type.iot"], "the smart home group has its name: " + (home && home.querySelector(".hd-title").textContent));
  check(!doc.querySelector('#groups section.group[data-type="climate"]'), "climate is not a group of its own");
  const fams = home ? [...home.querySelectorAll(".fam")].map((f) => f.dataset.family) : [];
  check(fams.join() === "lights,climate", "only the families with devices, in the fixed order: " + fams.join());
  const titles = home ? [...home.querySelectorAll(".fam .fam-title")].map((h) => h.textContent) : [];
  check(titles.join("|") === [LOCALE["js.ha.family.lights"], LOCALE["js.ha.family.climate"]].join("|"), "each family has its subtitle: " + titles.join("|"));
  const climate = home && home.querySelector('.fam[data-family="climate"]');
  check(!!climate && [...climate.querySelectorAll(".tile")].map((t) => t.dataset.id).sort().join() === "d21,d22", "the climate cards are under their subtitle");
  check(!!climate && climate.querySelector(".fam-count") && climate.querySelector(".fam-count").textContent === "2", "a family says how many devices it has");
  const otherGroups = [...doc.querySelectorAll('#groups section.group:not([data-type="iot"]) .fam')];
  check(otherGroups.length === 0, "the other groups have no subtitles");
  // the list view keeps the subtitles (a card per family)
  doc.documentElement.setAttribute("data-view", "list");
  check(home && [...home.querySelectorAll(".fam > .tiles")].length === 2, "in the list view each family is its own list");
  doc.documentElement.removeAttribute("data-view");

  // ---- the ring
  const segs = [...doc.querySelectorAll("#g-types .g-seg")];
  const keys = segs.map((s) => s.dataset.k);
  check(segs.length === 7 && keys[6] === "_other", "ten groups present: six arcs and «Others» last: " + keys.join());
  check(keys.slice(0, 2).join() === "iot,server", "the biggest groups first: " + keys.slice(0, 2).join());
  const other = segs[6];
  check(other && other.classList.contains("gc-other") && other.textContent.indexOf(LOCALE["js.ha.gauge.others"]) === 0 && /: 4$/.test(other.textContent), "«Others» is grey and counts the groups it holds: " + (other && other.textContent));
  check(segs.slice(0, 6).every((s) => s.classList.contains("gc-" + s.dataset.k)), "each group keeps its own colour class");
  const css = fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "frontend", "ha", "css", "40-network.css"), "utf8");
  const rules = (css.match(/\.gc-[a-z_]+\s*\{[^}]*\}/g) || []);
  check(rules.length >= 11, "the ring has a colour for each of the ten groups and for «Others»: " + rules.length);
  check(rules.every((r) => !/red|#e53935|#f44336|#d32f2f|#db4437/i.test(r)), "no group is red (red says offline)");
  other.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await wait(60);
  check(shownTiles().length === list.length, "«Others» is not a filter");

  // ---- the chips of the families
  const chips = () => doc.getElementById("fam-chips");
  check(!chips() || chips().hidden, "no family chips while no group is chosen");
  doc.querySelector('#g-types .g-seg[data-k="iot"]').dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await wait(80);
  const chipKeys = chips() ? [...chips().querySelectorAll("[data-family]")].map((c) => c.dataset.family) : [];
  check(chips() && !chips().hidden && chipKeys.join() === "lights,climate", "the smart home group chosen: chips of its families present: " + chipKeys.join());
  check(chips() && [...chips().querySelectorAll("[data-family]")].every((c) => c.tagName === "BUTTON" && c.getAttribute("aria-pressed") === "false"), "the chips are buttons, none pressed");
  check(shownTiles().sort().join() === [light.id, "d21", "d22", "d23"].sort().join(), "only the smart home cards are shown: " + shownTiles().join());
  chips().querySelector('[data-family="climate"]').click();
  await wait(80);
  check(shownTiles().sort().join() === "d21,d22", "a chip narrows to its family: " + shownTiles().join());
  check(chips().querySelector('[data-family="climate"]').getAttribute("aria-pressed") === "true", "and is pressed");
  chips().querySelector('[data-family="climate"]').click();
  await wait(80);
  check(shownTiles().length === 4, "pressed again, the whole group is back");
  chips().querySelector('[data-family="lights"]').click();
  await wait(80);
  doc.querySelector('#g-types .g-seg[data-k="iot"]').dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
  await wait(80);
  check(chips().hidden && shownTiles().length === list.length, "the group let go: no chips and every card, the family forgotten");

  // ---- the type and the family of a card
  doc.querySelector('#groups .tile[data-id="d21"]').click();
  await wait(150);
  const dlg = doc.getElementById("more");
  const typeBtn = dlg && dlg.querySelector('[data-act="type-menu"]');
  check(!!typeBtn, "the card has the type picker");
  if (typeBtn) {
    typeBtn.click();
    await wait(40);
    const items = [...dlg.querySelectorAll(".type-menu [data-type]")].map((b) => b.dataset.type);
    check(items.length === 11 && items[0] === "" && items.indexOf("climate") < 0 && items.indexOf("iot") >= 0, "the type picker: Auto and the ten groups: " + items.join());
    typeBtn.click();
    await wait(20);
  }
  const famBtn = dlg && dlg.querySelector('[data-act="family-menu"]');
  check(!!famBtn, "a smart home card has the family picker");
  const famRow = famBtn && famBtn.closest(".attr");
  check(famRow && famRow.textContent.indexOf(LOCALE["js.ha.family.climate"]) >= 0, "the family row says the family of the card");
  if (famBtn) {
    famBtn.click();
    await wait(40);
    const items = [...dlg.querySelectorAll(".type-menu [data-family]")].map((b) => b.dataset.family);
    check(items.join() === ",lights,climate,security,energy,appliance,other", "the family picker: Auto and the six families of the Home dashboard: " + items.join());
    const labels = [...dlg.querySelectorAll(".type-menu [data-family]")].slice(1).map((b) => b.textContent.trim());
    check(labels.every((l, i) => l === LOCALE["js.ha.family." + items[i + 1]]), "each family of the picker has its name: " + labels.join("|"));
    dlg.querySelector('.type-menu [data-family="security"]').click();
    await wait(80);
    const last = posted[posted.length - 1];
    check(last && /\/api\/devices\/d21\/override$/.test(last.url) && JSON.stringify(last.body) === '{"family":"security"}', "the family chosen is saved: " + JSON.stringify(last));
  }
  dlg.querySelector('[data-act="close"]') && dlg.querySelector('[data-act="close"]').click();
  await wait(60);
  const router = doc.querySelector('#groups .tile[data-id="' + list.find((d) => d.type === "router").id + '"]');
  router.click();
  await wait(150);
  check(!dlg.querySelector('[data-act="family-menu"]'), "a card outside the smart home group has no family picker");

  // every family has its name in the five languages, and a family the page does not know (saved before 1.0.4) is shown as «other»
  const FAMS = ["lights", "climate", "security", "energy", "appliance", "other"];
  ["en", "it", "de", "cs", "fr"].forEach((l) => {
    const loc = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "locales", l, "ha.json"), "utf8"));
    const fams = Object.keys(loc).filter((k) => k.indexOf("js.ha.family.") === 0).map((k) => k.slice(13));
    check(fams.join() === FAMS.join() && fams.every((f) => loc["js.ha.family." + f]), l + ": the six families have a name, none more: " + fams.join());
  });
  const core = fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "frontend", "ha", "js", "core.js"), "utf8");
  check(core.indexOf('export const FAMILIES = ["lights", "climate", "security", "energy", "appliance", "other"];') >= 0 && core.indexOf('d.family : "other"') >= 0, "the page knows the six families; an unknown one is «other»");

  check(errors.length === 0, "no error in the page: " + errors.join(" | "));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
