// The panel «Networks» v10 (js/netpanel.js) in a simulated browser: it opens from the menu, the list has the 8 columns and one row per network
// (name, network, VLAN, state, devices, the 7 bars, the quick action, the gear), the management panel shows what Vedetta sees with switches
// only where the server gives one (never in the main network), the switch sends the touch it names and keeps the focus, «How to turn it on»
// is a screen of the panel with one card per way and an «OR» between them, «Back» comes back to the same place, the quick action pauses and
// the focus goes to «Resume», «Add network» checks the address before asking, a refusal of the server shows its message, Escape goes back one
// step at a time. Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_netpanel_ui.js [it|en]
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
const TX = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "vedetta", "app", "locales", lang, "netpanel.json"), "utf8"));
const tx = (k, vars) => TX["js.networks." + k].replace(/\{(\w+)\}/g, (m, n) => (vars && n in vars ? String(vars[n]) : m));

// ---- what the server says (invented addresses only)
const on = (source, by, sw) => Object.assign({ state: "on", source, by }, sw ? { switch: sw } : {});
const way = (id, by, best, params) => ({ id, by, best: !!best, soon: false, where: by === "ha" ? ["ha.settings", "ha.system", "ha.network"] : ["router.network", "net", "router.mdns"], params: params || {} });
const how = (...ways) => ({ state: "how", need: ways.length === 1 ? "this" : "one", ways });
let blocked = false;          // the router blocks the probes: the ports are asked (switch on) but nothing answers
let snmpHow = false;          // the MACs not given yet: the way through SNMP is offered
function routedCaps(touch) {
  const sw = { on: touch !== "presence", touch_on: "ports", touch_off: "presence" };
  const port = sw.on ? (blocked ? Object.assign(how(way("firewall_rule", "router", true, { from: "192.168.50.2", to: "192.168.60.0/24" })), { switch: sw }) : on("ved", "through_router", sw))
    : { state: "off", source: "ved", by: "through_router", switch: sw };
  return { pres: on("ved", "ping"), name: on("router", "router_dns"), mac: snmpHow ? how(way("snmp", "router", true, {})) : on("ha", "router_integration"),
    port,
    deep: how(way("mdns_reflector", "router", true, { cidr: "192.168.60.0/24", vlan: 60 }), way("ha_inside", "ha", false, { cidr: "192.168.60.0/24", vlan: 60, example: "ha network vlan eth0 60 --ipv4-method static --ipv4-address 192.168.60.100/24" })),
    quiet: on("ha", "router_integration"), stray: how(way("ha_inside", "ha", true, { cidr: "192.168.60.0/24", vlan: 60 })) };
}
const MAIN = { id: "main", cidr: "192.168.50.0/24", via: ["direct"], touch: "full", state: "confirmed", cards: 9, fits: true, name: "Home", vlan: null, on: 7, mute: false,
  caps: { pres: on("ved", "arp"), name: on("ved", "mdns_netbios"), mac: on("ved", "arp"), port: on("ved", "port_probe"), deep: on("ved", "upnp_mdns"), quiet: on("ved", "arp"), stray: { state: "soon" } } };
const server = { main: MAIN, left_out: [], limits: {}, networks: [
  { id: "iot", cidr: "192.168.60.0/24", via: ["routed"], touch: "presence", state: "confirmed", cards: 4, fits: true, name: "IoT", vlan: 60, on: 3, mute: false, caps: routedCaps("presence") },
  { id: "p192-168-70", cidr: "192.168.70.0/24", via: ["routed"], touch: "presence", state: "proposed", cards: 2, fits: true, name: null, vlan: null, on: 2, mute: false, caps: routedCaps("presence") },
] };
function apply(n, body) {
  if (body.state) n.state = body.state;
  if (body.touch) { n.touch = body.touch; n.caps = routedCaps(body.touch); }
  if ("name" in body) n.name = body.name;
  if ("vlan" in body) n.vlan = body.vlan;
}

const errors = [];
const vc = new VirtualConsole();
vc.on("jsdomError", (e) => errors.push("jsdomError: " + ((e.detail && e.detail.stack) || e.message)));
vc.on("error", (e) => errors.push("console.error: " + e));
const calls = [];
let refuse = null;
let hold = null;              // a promise: the next changes of the networks wait for it (a slow server)
const dom = new JSDOM(html, {
  runScripts: "dangerously", pretendToBeVisual: true, virtualConsole: vc, url: "http://localhost/ha?lang=" + lang,
  beforeParse(win) {
    win.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    win.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
    win.matchMedia = () => ({ matches: false, addListener() {}, addEventListener() {} });
    win.HTMLElement.prototype.scrollIntoView = function () {};
    win.fetch = (url, opts) => {
      const method = (opts && opts.method) || "GET", body = opts && opts.body ? JSON.parse(opts.body) : null;
      if (hold && method === "POST" && url.startsWith("/api/networks")) { const h = hold; return h.then(() => win.fetch(url, opts)); }
      url = url.split("?")[0];
      calls.push({ url, method, body });
      const reply = (status, b) => Promise.resolve({ ok: status === 200, status, headers: { get: () => null }, json: () => Promise.resolve(JSON.parse(JSON.stringify(b))), text: () => Promise.resolve(JSON.stringify(b)) });
      if (url.startsWith("/api/networks")) {
        if (refuse) { const r = refuse; refuse = null; return reply(400, { detail: r }); }
        const id = url.split("/")[3], purge = url.split("/")[4] === "purge";
        if (id === "test") return reply(200, { cidr: body.cidr, asked: 254, answer: 3, sample: ["192.168.80.5", "192.168.80.9", "192.168.80.40"], vlan: body.vlan, caps: routedCaps("presence") });
        if (purge && method === "GET") return reply(200, { cards: 4, devices: 6, rows: 1234, ignored: 2 });
        if (purge && id === "main") { MAIN.cards = 0; MAIN.on = 0; return reply(200, server); }
        if (purge) { server.networks = server.networks.filter((n) => n.id !== id); return reply(200, server); }
        if (method === "POST" && !id) server.networks.push(Object.assign({ touch: "presence", cards: 0, fits: true, on: 0, mute: false, caps: routedCaps("presence") }, body));
        else if (method === "POST" && id === "main") MAIN.name = body.name || "Home";
        else if (method === "POST") apply(server.networks.find((n) => n.id === id), body);
        else if (method === "DELETE") server.networks = server.networks.filter((n) => n.id !== id);
        return reply(200, server);
      }
      if (url.startsWith("/api/new-devices")) return reply(200, []);
      if (url.startsWith("/api/snmp")) {                // the server refuses a public address of the router (19/11)
        if (method === "POST" && body && /^8\./.test(body.snmp_router || "")) return reply(400, { detail: "Valore non valido: snmp_router" });
        return reply(200, { snmp_router: (body && body.snmp_router) || "", snmp_community_set: false });
      }
      let b = {};
      if (url.startsWith("/api/ha/devices") && !url.includes("/debug")) b = data.devices;
      else if (url.startsWith("/api/ha/summary")) b = data.summary;
      else if (url.startsWith("/api/ha/logbook")) b = data.logbook;
      else if (url.startsWith("/api/ha/history?")) b = data.history_all;
      return reply(200, b);
    };
    win.EventSource = class { constructor() { this.l = {}; } addEventListener(n, f) { this.l[n] = f; } close() {} };
    win.requestAnimationFrame = (f) => setTimeout(() => f(win.performance.now()), 0);
  },
});
const win = dom.window, doc = win.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const q = (s) => doc.querySelector(s), qa = (s) => Array.from(doc.querySelectorAll(s));
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }
const click = async (sel) => { const el = typeof sel === "string" ? q(sel) : sel; if (!el) throw new Error("manca " + sel); el.click(); await wait(40); };
const key = (k) => { const ev = new win.Event("cancel", { cancelable: true }); q("#netview").dispatchEvent(ev); return wait(40); };
const posts = (u) => calls.filter((c) => c.url === u && c.method !== "GET");
const rowOf = (name) => qa("#netview .np-rw").find((r) => r.querySelector(".np-nm").textContent === name);

(async () => {
  await wait(800);
  check(!!q("#netview") && !q("#netview").hasAttribute("open"), "the view exists and is closed at the start");
  await click("#btn-menu");
  const entry = q("[data-netpanel]");
  check(!!entry && entry.textContent.includes(tx("ui.title")), "the menu has the entry «" + tx("ui.title") + "»");
  await click(entry);
  await wait(80);
  check(q("#netview").hasAttribute("open") && doc.activeElement === q("#np-x"), "the entry opens the view, the focus on its close button");
  const head = qa("#netview .np-hd > div").map((d) => d.textContent);
  check(head.length === 8 && head[0] === tx("ui.col_name") && head[5] === tx("ui.col_sees"), "eight columns with their names: " + head.join(" · "));
  check(qa("#netview .np-legend h3").map((h) => h.textContent).join("|") === tx("ui.sources") + "|" + tx("ui.missing"), "the legend: «Sources» and «If missing»");
  const rows = qa("#netview .np-rw");
  check(rows.length === 3, "one row per network, the main one first");
  const cells = (r) => Array.from(r.children).map((c) => c.textContent.trim());
  const m = cells(rows[0]);
  check(m[0] === "Home" && m[1] === "192.168.50.0/24" && m[2] === "—" && m[3] === tx("ui.state_on") && m[4] === tx("ui.of", { n: 7, all: 9 }), "the main network: name, address, no VLAN, active, 7 of 9: " + m.slice(0, 5).join(" · "));
  check(rows[0].querySelectorAll(".np-bars i.on").length === 6 && m[5].includes(tx("ui.of", { n: 6, all: 7 })) && !rows[0].querySelector("[data-np-act]"), "6 bars of 7 full, no quick action on the main network");
  const iotRow = rowOf("IoT");
  check(cells(iotRow)[2] === "60" && iotRow.querySelectorAll(".np-bars i.how").length === 2 && !!iotRow.querySelector('[data-np-act="iot|pause"]'), "IoT: VLAN 60, two bars that can be turned on, «Pause»");
  const newRow = rowOf("192.168.70.0/24");
  check(!!newRow && newRow.classList.contains("need") && cells(newRow)[3] === tx("ui.state_new") && !!newRow.querySelector('[data-np-act="p192-168-70|adopt"]'), "a proposed network without a name: its address, «New», «Adopt»");

  // the main network: no switch; its name is written apart; its danger zone deletes its devices only
  await click('[data-np-open="main"]');
  check(!!q(".np-panel") && doc.activeElement === q('.np-ptop [data-np-close="1"]'), "the gear opens the panel, the focus on its close button");
  check(qa(".np-cap").length === 7 && qa(".np-sw").length === 0, "the main network: 7 functions, no switch (ports and model always on)");
  check(!q(".np-routed"), "the main network: no note on the ping sweep");
  check(q(".np-danger").textContent.includes(tx("ui.danger_main_text")) && q("[data-np-pact='askdel']").textContent === tx("ui.delete_main"), "the main network: «" + tx("ui.delete_main") + "», the network stays");
  check(q(".np-cap:nth-child(7)").textContent.includes(tx("ui.soon")), "the strays: coming soon");
  const nameIn = q("#np-name");
  nameIn.value = " Casa mia "; nameIn.dispatchEvent(new win.Event("change", { bubbles: true }));
  await wait(80);
  check(posts("/api/networks/main").some((c) => c.body.name === "Casa mia") && q("#np-ptitle").textContent === "Casa mia", "the name of the main network: trimmed, saved apart, the title follows");
  await click('[data-np-pact="askdel"]');
  await wait(40);
  const mc = q(".np-confirm").textContent;
  check(mc.includes(tx("ui.confirm_main_title", { name: "Casa mia" })) && mc.includes(tx("ui.confirm_counts", { cards: 4, devices: 6, rows: (1234).toLocaleString(lang) })) && mc.includes(tx("ui.confirm_main_text")),
    "the confirmation of the main network: its title, the numbers, Vedetta starts over");
  await click('[data-np-pact="del"]');
  await wait(60);
  check(posts("/api/networks/main/purge").length === 1 && !!rowOf("Casa mia") && cells(rowOf("Casa mia"))[4] === tx("ui.of", { n: 0, all: 0 }), "the devices go, the main network stays in the list");
  await click('[data-np-open="main"]');
  await key("Escape");
  check(!q(".np-panel") && doc.activeElement === q('[data-np-open="main"]'), "Escape closes the panel, the focus back on its gear");

  // a network behind the router: the switch of the ports, «How to turn it on» for the model
  await click('[data-np-open="iot"]');
  check(!!q(".np-routed") && q(".np-routed").textContent === tx("ui.routed_note"), "behind the router: the note on the ping sweep and on the address that changes");
  // the side panel is modal: Tab from its last control comes back to its first, Shift+Tab from the first goes to the last (19/11 review)
  const inPanel = () => Array.from(q(".np-panel").querySelectorAll("button:not([disabled]), input:not([disabled]), select, textarea, a[href], [tabindex]:not([tabindex='-1'])"));
  const tab = (shift) => { const ev = new win.KeyboardEvent("keydown", { key: "Tab", shiftKey: !!shift, bubbles: true, cancelable: true }); doc.activeElement.dispatchEvent(ev); return ev; };
  inPanel().pop().focus();
  const evTab = tab(false);
  check(evTab.defaultPrevented && doc.activeElement === inPanel()[0], "Tab from the last control of the panel goes back to its first");
  tab(true);
  check(doc.activeElement === inPanel().pop(), "Shift+Tab from the first goes to the last");
  q("#np-x").focus();
  tab(false);
  check(q(".np-panel").contains(doc.activeElement), "focus outside the panel (behind the shade) is brought back in");
  const sw = q('[data-np-tog="port"]');
  check(!!sw && sw.getAttribute("aria-checked") === "false" && !q('[data-np-tog="deep"]'), "ports: a switch, off; model: no switch behind the router");
  q(".np-pbody").scrollTop = 120;
  sw.focus();
  await click(sw);
  await wait(60);
  check(posts("/api/networks/iot").some((c) => c.body.touch === "ports"), "the switch sends the touch it names (ports)");
  check(q('[data-np-tog="port"]').getAttribute("aria-checked") === "true" && doc.activeElement === q('[data-np-tog="port"]'), "it is on, and the focus stays on it after the redraw");
  // a name written and, at once, a click on «Pause» while the name is still being saved: the click waits for the save, it is not lost (19/11 review)
  let release;
  hold = new Promise((r) => { release = r; });
  const nmIn = q("#np-name");
  nmIn.value = "Lab";
  nmIn.dispatchEvent(new win.Event("change", { bubbles: true }));
  await wait(10);
  q('[data-np-pact="pause"]').click();
  await wait(30);
  hold = null;
  release();
  await wait(150);
  const iotPosts = posts("/api/networks/iot");
  check(iotPosts.some((c) => c.body.name === "Lab") && iotPosts.some((c) => c.body.state === "paused") && !!q('[data-np-pact="resume"]'),
    "the click during the save is done after it: renamed and paused");
  await click('[data-np-pact="resume"]');
  await wait(60);
  // the close button works while a change is on its way (it only closes; the answer is drawn when it comes)
  hold = new Promise((r) => { release = r; });
  q('[data-np-pact="pause"]').click();
  await wait(20);
  q('.np-ptop [data-np-close="1"]').click();
  await wait(30);
  check(!q(".np-panel"), "the X of the panel closes it while a change is on its way");
  hold = null;
  release();
  await wait(150);
  check(!q(".np-panel") && posts("/api/networks/iot").some((c) => c.body.state === "paused"), "the change is still saved, the panel stays closed");
  await click('[data-np-open="iot"]');
  await click('[data-np-pact="resume"]');
  await wait(60);
  q("#np-name").value = "IoT";                            // its name back, as the rest of this check expects
  q("#np-name").dispatchEvent(new win.Event("change", { bubbles: true }));
  await wait(60);
  q('[data-np-tog="port"]').focus();
  // the same, with the router blocking the probes: «How to turn it on» beside the switch (18/11 review: only the switch, no way to the guide)
  blocked = true;
  await click('[data-np-tog="port"]');
  await wait(60);
  await click('[data-np-tog="port"]');
  await wait(60);
  check(!!q('[data-np-how="port"]') && q('[data-np-tog="port"]').getAttribute("aria-checked") === "true", "blocked ports: «How to turn it on» and the switch, both");
  check(q('[data-np-tog="port"]').closest(".np-cap").children.length === 3, "and the row keeps its three cells (icon, text, the pair): the switch never wraps");
  blocked = false;
  await click('[data-np-tog="port"]');
  await wait(60);
  await click('[data-np-tog="port"]');
  await wait(60);
  // SNMP with an address the server refuses: the page says it in its own language, not the server's Italian line (19/11)
  snmpHow = true;
  await click('[data-np-tog="port"]');
  await wait(60);
  await click('[data-np-tog="port"]');
  await wait(60);
  await click('[data-np-how="mac"]');
  await wait(60);
  q("#np-snmp-router").value = "8.8.8.8";
  await click('[data-np-snmp="save"]');
  await wait(80);
  check(!!q(".np-snmp-msg.fail") && q(".np-snmp-msg.fail").textContent === tx("snmp.bad_router"), "a public router address: the page's own message (" + (q(".np-snmp-msg") && q(".np-snmp-msg").textContent) + ")");
  q("#np-snmp-router").value = "192.168.1.1";
  await click('[data-np-snmp="save"]');
  await wait(80);
  check(qa(".snack").some((s) => s.textContent.includes(tx("snmp.saved"))) && !qa(".snack").some((s) => s.textContent.trim() === tx("snmp.save")),
    "a saved SNMP setting says «Saved», not the label of the button (19/11)");
  await key("Escape");
  snmpHow = false;
  await click('[data-np-tog="port"]');
  await wait(60);
  await click('[data-np-tog="port"]');
  await wait(60);
  check(!!q(".np-pbody") && q(".np-panel") && !q(".np-panel").classList.contains("enter"), "the panel did not come in again (no jump)");
  await click('[data-np-how="deep"]');
  const ways = qa(".np-way");
  check(ways.length === 2 && qa(".np-or").length === 1 && q(".np-or").textContent === tx("ui.or"), "«How to turn it on»: one card per way, one «OR» between them");
  check(ways[0].querySelector(".np-pill.best") && ways[0].querySelector(".np-crumbs").textContent.includes(tx("ui.net_vlan", { n: 60 })), "the recommended way first; «this network» is its VLAN in the crumbs");
  check(ways[1].querySelector(".np-exc") && ways[1].textContent.includes("ha network vlan eth0 60"), "the VLAN command only as an example");
  check(!/altri router|other routers|Basta una|just one/i.test(q(".np-pbody").textContent) && q(".np-foot").textContent.includes(tx("ui.foot_done")), "no «on other routers», no «just one of», the foot says it turns on by itself");
  check(doc.activeElement === q('[data-np-back="1"]'), "the focus on «Back»");
  await key("Escape");
  check(!q(".np-way") && doc.activeElement === q('[data-np-how="deep"]'), "Escape comes back to the panel, the focus on «How to turn it on»");
  await click('.np-ptop [data-np-close="1"]');

  // the quick action: pause, the focus goes to «Resume»
  const pause = q('[data-np-act="iot|pause"]');
  pause.focus();
  await click(pause);
  await wait(60);
  check(posts("/api/networks/iot").some((c) => c.body.state === "paused") && rowOf("IoT").classList.contains("paused"), "«Pause» pauses the network");
  check(doc.activeElement === q('[data-np-act="iot|resume"]'), "the focus goes to «Resume», in the same place");
  await click('[data-np-act="p192-168-70|adopt"]');
  check(posts("/api/networks/p192-168-70").some((c) => c.body.state === "confirmed"), "«Adopt» confirms the proposed network");

  // add a network
  await click("#np-add");
  check(doc.activeElement === q("#np-a-name"), "«Add network» opens the same panel, the focus on the name");
  const typeIn = (sel, v) => { const el = q(sel); el.value = v; el.dispatchEvent(new win.Event("input", { bubbles: true })); };
  typeIn("#np-a-name", "Cameras"); typeIn("#np-a-cidr", "192.168.80.5/33"); typeIn("#np-a-vlan", "80");
  const before = calls.length;
  check(!q('[data-np-pact="try"]') && !!q('[data-np-pact="test"]'), "«" + tx("ui.add") + "» starts with «" + tx("ui.test_do") + "», not with «" + tx("ui.add_do") + "»");
  await click('[data-np-pact="test"]');
  check(calls.length === before && q("#np-a-cidr").classList.contains("bad") && doc.activeElement === q("#np-a-cidr"), "a wrong address is said at once, nothing is asked");
  typeIn("#np-a-cidr", "192.168.80.0/24");
  refuse = { code: "E_OVERLAP", message: "Overlaps another network (from the server)" };
  await click('[data-np-pact="test"]');
  await wait(60);
  check(qa(".snack").some((s) => s.textContent.includes("from the server")) && !!q(".np-panel") && !q(".np-trial"), "a refusal of the server shows its message, the panel stays open");
  await click('[data-np-pact="test"]');
  await wait(60);
  const tried = posts("/api/networks/test").pop();
  check(tried && tried.body.cidr === "192.168.80.0/24" && tried.body.vlan === 80 && !posts("/api/networks").length, "«" + tx("ui.test_do") + "» sends the network to try, nothing is added");
  check(!!q(".np-trial") && q(".np-trial").textContent.includes(tx("ui.test_answer", { n: 3, all: 254 })) && q(".np-trial").textContent.includes("192.168.80.9") &&
    q(".np-trial").querySelectorAll(".np-cap").length === 7 && !q(".np-trial .np-sw") && !q(".np-trial [data-np-how]"), "the outcome: who answers, a few addresses, the 7 functions without switches");
  check(q(".np-trial").textContent.includes(tx("ui.later_off")) && doc.activeElement === q('[data-np-pact="try"]'), "then «" + tx("ui.add_do") + "», with the focus on it");
  typeIn("#np-a-name", "Cameras ");                       // a space typed after a try stays in the field (19/11 review: it was lost on the redraw)
  check(q("#np-a-name").value === "Cameras ", "the space typed after a try is still there (" + JSON.stringify(q("#np-a-name").value) + ")");
  typeIn("#np-a-name", "Cameras");
  typeIn("#np-a-cidr", "192.168.81.0/24");
  check(!q(".np-trial") && !q('[data-np-pact="try"]'), "a changed address must be tried again");
  typeIn("#np-a-cidr", "192.168.80.0/24");
  await click('[data-np-pact="test"]');
  await wait(60);
  await click('[data-np-pact="try"]');
  await wait(60);
  const add = posts("/api/networks").pop();
  check(add && add.body.id === posts("/api/networks/test").pop().body.id, "the network added is the one tried (same id)");
  check(add && add.body.cidr === "192.168.80.0/24" && add.body.name === "Cameras" && add.body.vlan === 80 && add.body.via[0] === "routed" && /^[a-z0-9]{1,16}$/.test(add.body.id), "it adds the network behind the router, with name and VLAN");
  check(!q(".np-panel") && !!rowOf("Cameras"), "the panel closes, the new network is in the list");

  // a try on its way, the panel closed, then a click in the list: the click waits for the try and is done, not lost
  await click("#np-add");
  typeIn("#np-a-cidr", "192.168.82.0/24");
  let letGo;
  hold = new Promise((r) => { letGo = r; });
  q('[data-np-pact="test"]').click();
  await wait(20);
  q('.np-ptop [data-np-close="1"]').click();
  await wait(20);
  const resumes = () => posts("/api/networks/iot").filter((c) => c.body.state === "confirmed").length;
  const resumedBefore = resumes();
  q('[data-np-act="iot|resume"]').click();
  await wait(20);
  hold = null;
  letGo();
  await wait(150);
  check(!q(".np-panel") && resumes() === resumedBefore + 1 && !rowOf("IoT").classList.contains("paused"),
    "the click made in the list while a closed panel's try was on its way is done after the try (resumed)");

  // delete
  const id = add.body.id;
  await click('[data-np-open="' + id + '"]');
  // the count fails: the notice, and the panel goes back to its «Delete» button, never stuck on «Counting…» (19/11 review)
  refuse = { code: "E_X", message: "count failed on the server" };
  await click('[data-np-pact="askdel"]');
  await wait(60);
  check(!q(".np-confirm") && !!q('[data-np-pact="askdel"]') && qa(".snack").some((s) => s.textContent.includes("count failed")), "a failed count: the notice, and «Delete» again");
  q('[data-np-pact="askdel"]').focus();
  await click('[data-np-pact="askdel"]');
  check(!!q(".np-confirm") && doc.activeElement === q('[data-np-pact="nodel"]'), "«" + tx("ui.delete") + "» asks inside the panel, the focus on «Cancel»");
  await wait(40);
  check(calls.some((c) => c.method === "GET" && c.url === "/api/networks/" + id + "/purge") && q(".np-confirm").textContent.includes(tx("ui.confirm_counts", { cards: 4, devices: 6, rows: (1234).toLocaleString(lang) })) &&
    q(".np-confirm").textContent.includes(tx("ui.confirm_ignored", { ignored: 2 })) &&
    !q('[data-np-pact="del"]').disabled, "the confirmation shows the numbers counted by the server");
  await click('[data-np-pact="del"]');
  await wait(60);
  check(posts("/api/networks/" + id + "/purge").length === 1 && !calls.some((c) => c.method === "DELETE") && !rowOf("Cameras") && !q(".np-panel"), "«" + tx("ui.delete_do") + "» deletes it all");

  await key("Escape");
  check(!q("#netview").hasAttribute("open"), "Escape with no panel closes the view");
  check(errors.length === 0, "no error in the page" + (errors.length ? ": " + errors[0] : ""));
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.log("FAILED: " + (e && e.stack || e)); process.exit(1); });
