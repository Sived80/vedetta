// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The page's plural forms (core.js, between «plural:start» and «plural:end»; 19/11 review): Czech says «3 zprávy» but «5 zpráv»; every language of the app picks
// «key_one», «key_few», «key_other» or «key» as Intl.PluralRules says. The language argument is ignored: the four tables are checked.
//   node tests/ui/check_plural_ui.js
const fs = require("fs");
const path = require("path");
const root = path.join(__dirname, "..", "..", "vedetta", "app");
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }
function table(lang) {
  const out = {};
  for (const f of fs.readdirSync(path.join(root, "locales", lang))) Object.assign(out, JSON.parse(fs.readFileSync(path.join(root, "locales", lang, f), "utf8")));
  return out;
}
(async () => {
  // the two functions of core.js between its markers, run here as they are written (core.js itself needs the page)
  const core = fs.readFileSync(path.join(root, "frontend", "ha", "js", "core.js"), "utf8");
  const between = core.split("// plural:start")[1].split("// plural:end")[0];
  const part = between.slice(between.indexOf("\n") + 1).replace(/export function/g, "function");     // without the rest of the marker's line
  const { pluralOf, pluralText } = new Function(part + "; return { pluralOf, pluralText };")();
  const fill = (s, n) => s.replace("{n}", String(n));
  const cs = table("cs");
  check([1, 3, 5].map((n) => fill(pluralText(cs, "js.ha.alerts.waiting", { n }, "cs"), n)).join(" | ") === "Ve frontě: 1 zpráva | Ve frontě: 3 zprávy | Ve frontě: 5 zpráv", "Czech: 1 / 2-4 / 5+");
  check(fill(pluralText(cs, "js.networks.snmp.ok", { n: 4 }, "cs"), 4) === "Router vrátil 4 adresy", "Czech: four addresses");
  check(pluralText(cs, "js.ha.more.outages", { n: 2 }, "cs") === "výpadky" && pluralText(cs, "js.ha.more.outages", { n: 7 }, "cs") === "výpadků", "Czech: a key with only _one/_few/_other");
  // the counts the page shows with {n} (19/11 review): the export's days (2 to 20) and the recipients of a test message
  const fillAll = (s, v) => s.replace(/\{(\w+)\}/g, (m, k) => (k in v ? String(v[k]) : m));
  const say = (key, v) => fillAll(pluralText(cs, key, v, "cs"), v);
  check([2, 3, 7].map((n) => say("js.ha.export.days", { n })).join(" | ") === "2 dny | 3 dny | 7 dní", "Czech: the export's days, 2 / 3 / 7");
  check(say("js.ha.export.sum_size", { n: 3, size: "2 MB" }) === "3 dny · přibližně 2 MB" && say("js.ha.export.sum_size", { n: 5, size: "2 MB" }) === "5 dní · přibližně 2 MB", "Czech: the export's summary, 3 / 5 days");
  check([1, 2, 3, 6].map((n) => say("js.ha.alerts.queued", { n })).join(" | ") === "Zpráva ve frontě pro 1 příjemce. | Zpráva ve frontě pro 2 příjemce. | Zpráva ve frontě pro 3 příjemce. | Zpráva ve frontě pro 6 příjemců.", "Czech: the recipients of a test message, 1 / 2 / 3 / 6");
  check(pluralOf(3, "cs") === "few" && pluralOf(3, "en") === "other" && pluralOf(1, "it") === "one", "the categories of the languages");
  for (const lang of ["en", "it", "de"]) {
    const tb = table(lang);
    check(pluralText(tb, "js.ha.alerts.waiting", { n: 1 }, lang) === tb["js.ha.alerts.waiting_one"] && pluralText(tb, "js.ha.alerts.waiting", { n: 3 }, lang) === tb["js.ha.alerts.waiting"], lang + ": one and the rest, as before");
  }
  check(pluralText({ k: "x" }, "k", { n: 2 }, "xx-bad") === "x", "an unknown language falls back to the plain key");
  console.log(failed ? "FAILED: " + failed : "ALL OK");
  process.exit(failed ? 1 : 0);
})();
