// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
// The narrow layout (the network card on top, one column): the side column is opened (display: contents) and every card of it takes its place
// with `order`. A card without a place has order 0 and goes on top of everything (the last 12 hours did, 17/11). Here: every card of the side
// column of the page has an order in both narrow rules (the host's class and the media query), in the same sequence as the wide layout, and
// the devices come after all of them. No browser needed.   from the vedetta/ folder:  node ../tests/ui/check_narrow_order_ui.js
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..", "..", "vedetta", "app");
const html = fs.readFileSync(path.join(root, "templates", "ha.html"), "utf8");
const css = fs.readFileSync(path.join(root, "frontend", "ha", "css", "10-base.css"), "utf8");
let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FAILED:", msg); } }

// the cards of the side column, in the order of the page (the wide layout)
const side = html.slice(html.indexOf('class="col-side"'), html.indexOf('class="col-main"'));
const cards = [...side.matchAll(/<(?:section|div)[^>]*\bid="(card-[a-z-]+)"/g)].map((m) => m[1]);
check(cards.length >= 3 && cards[0] === "card-network", "le schede della colonna laterale: " + cards.join(", "));

for (const [name, prefix] of [["la classe dell'host", "html.is-narrow "], ["la media query", "html:not([data-narrow-host]) "]]) {
  const order = (sel) => {
    const m = new RegExp(prefix.replace(/[[\]().*+?^$|\\]/g, "\\$&") + sel.replace(/[.#]/g, "\\$&") + " \\{[^}]*order: (\\d+)").exec(css);
    return m ? +m[1] : null;
  };
  const got = cards.map((c) => order("#" + c));
  check(got.every((o) => o !== null && o > 0), name + ": ogni scheda ha il suo posto (" + cards.map((c, i) => c + "=" + got[i]).join(", ") + ")");
  check(got.every((o, i) => i === 0 || o > got[i - 1]), name + ": nello stesso ordine della vista larga");
  const main = order(".col-main");
  check(main !== null && got.every((o) => o < main), name + ": i dispositivi dopo tutte le schede (" + main + ")");
}

console.log(failed ? "FAILED: " + failed : "ALL OK");
process.exit(failed ? 1 : 0);
