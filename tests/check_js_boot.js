// Boot check of the /ha page as ES modules: node tests/check_js_boot.js [--write]
// The entry module (frontend/ha/js/app.js) is imported by Node itself, so the whole graph of imports is linked for real (a name that is imported and not exported, a missing file, a cycle that reads a name before it
// exists: all of them stop the load with an error). The page is a fake (every property and call answers with another fake object). What is recorded must not change when the code is only rewritten:
// no error at load, how many listeners and timers are registered, which requests are made, how many DOM nodes are touched.
const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
const dir = path.join(process.env.VROOT || path.join(__dirname, ".."), "vedetta", "app", "frontend", "ha", "js");
const golden = path.join(__dirname, "golden", "js_boot.json");

const seen = { listeners: 0, timers: 0, intervals: 0, requests: [], created: 0, errors: [] };
const fake = () => {
  const target = function () {};
  const store = {};
  return new Proxy(target, {
    get(_, k) {
      if (k === Symbol.toPrimitive) return () => "";
      if (k === "then") return undefined;
      if (k === "length") return 0;
      if (k === "addEventListener") return () => { seen.listeners++; };
      if (k === "querySelectorAll" || k === "getElementsByClassName" || k === "children") return () => [];
      if (k === "classList") return { add() {}, remove() {}, toggle() {}, contains: () => false };
      if (k === "style" || k === "dataset") return store[k] || (store[k] = {});
      if (k === "createElement") return () => { seen.created++; return fake(); };
      return store[k] !== undefined ? store[k] : fake();
    },
    set(_, k, v) { store[k] = v; return true; },
    apply() { return fake(); },
    has() { return true; },
  });
};
const define = (name, value) => Object.defineProperty(globalThis, name, { value, writable: true, configurable: true });
define("document", fake());
define("window", globalThis);
define("navigator", { language: "en", languages: ["en"] });
define("location", { href: "http://x/ha", search: "", hash: "", pathname: "/ha", origin: "http://x" });
define("localStorage", { getItem: () => null, setItem() {}, removeItem() {} });
define("sessionStorage", { getItem: () => null, setItem() {}, removeItem() {} });
define("matchMedia", () => ({ matches: false, addEventListener() { seen.listeners++; } }));
define("addEventListener", () => { seen.listeners++; });
define("setTimeout", () => { seen.timers++; return 1; });
define("setInterval", () => { seen.intervals++; return 1; });
define("clearTimeout", () => {});
define("clearInterval", () => {});
define("fetch", (u) => { seen.requests.push(String(u).split("?")[0]); return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}), text: () => Promise.resolve("") }); });
define("requestAnimationFrame", () => 1);
define("getComputedStyle", () => fake());
define("EventSource", function () { return fake(); });
define("WebSocket", function () { return fake(); });
define("VedettaIcons", fake());
define("VEDETTA_LANG", "en");
define("VEDETTA_BASE", "");
define("Vedetta", fake());

(async () => {
  try { await import(pathToFileURL(path.join(dir, "app.js")).href); } catch (e) { seen.errors.push(String((e && e.message) || e)); }
  await new Promise((resolve) => process.nextTick(resolve));
  seen.requests.sort();
  const out = JSON.stringify(seen, null, 1);
  if (process.argv.includes("--write")) { fs.mkdirSync(path.dirname(golden), { recursive: true }); fs.writeFileSync(golden, out + "\n"); console.log("written " + golden); process.exit(0); }
  const want = fs.existsSync(golden) ? fs.readFileSync(golden, "utf8").trim() : null;
  if (want !== out) { console.log("ERRORE: the boot of the page changed\n" + out + "\nwanted:\n" + want); process.exit(1); }
  console.log("TUTTO OK");
  process.exit(0);
})();
