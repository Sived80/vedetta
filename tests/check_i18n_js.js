// Verifica i18n dei file JS: node tests/check_i18n_js.js
const fs = require("fs");
const path = require("path");
const root = path.join(__dirname, "..", "vedetta", "app");
const en = JSON.parse(fs.readFileSync(path.join(root, "locales", "en", "js.json"), "utf8"));
const it = JSON.parse(fs.readFileSync(path.join(root, "locales", "it", "js.json"), "utf8"));
let errors = 0;
const fail = (m) => { console.log("ERRORE: " + m); errors++; };

const ek = Object.keys(en).sort(), ik = Object.keys(it).sort();
ek.filter((k) => !(k in it)).forEach((k) => fail("manca in it: " + k));
ik.filter((k) => !(k in en)).forEach((k) => fail("manca in en: " + k));
// segnaposto identici tra le lingue
ek.forEach((k) => {
  if (!(k in it)) return;
  const ph = (s) => (s.match(/\{\w+\}/g) || []).sort().join(",");
  if (ph(en[k]) !== ph(it[k])) fail("segnaposto diversi: " + k);
});

const jsDir = path.join(root, "static", "js");
const used = new Set();
for (const f of fs.readdirSync(jsDir).filter((x) => x.endsWith(".js"))) {
  const src = fs.readFileSync(path.join(jsDir, f), "utf8");
  const re = /(?:\bT|\bV\.t|Vedetta\.t)\(\s*["']([a-z0-9_.]+)["']/g;
  let m;
  while ((m = re.exec(src))) used.add(m[1]);
  // chiavi passate con ternario (es. T(cond ? "a" : "b"))
  const re2 = /["'](js\.[a-z0-9_.]+)["']/g;
  while ((m = re2.exec(src))) used.add(m[1]);
  const bad = /Chiudi|Annulla|non riuscit|Salva|Elimina|Scansion|Dispositivo|Riprova|Aggiorn|Nessun|Impossibile|"it-IT"|"it"/;
  src.split(/\r?\n/).forEach((line, i) => {
    if (/^\s*\/\//.test(line)) return;
    if (bad.test(line.replace(/\/\/.*$/, ""))) fail(`${f}:${i + 1} possibile stringa italiana: ${line.trim()}`);
  });
}
for (const k of used) {
  const ok = (k in en && k in it) || (`${k}_one` in en && `${k}_other` in en && `${k}_one` in it && `${k}_other` in it);
  if (!ok) fail("chiave usata ma mancante: " + k);
}
// chiavi definite ma non usate (avviso)
const base = (k) => k.replace(/_(one|other)$/, "");
ek.filter((k) => !used.has(k) && !used.has(base(k))).forEach((k) => console.log("avviso: chiave non usata: " + k));
console.log(`chiavi en=${ek.length} it=${ik.length}, usate nei js=${used.size}, errori=${errors}`);
process.exit(errors ? 1 : 0);
