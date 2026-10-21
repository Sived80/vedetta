// The export window with the debug mode OFF is the one everybody knows: nothing of the network (VLAN) option exists in it, and Home Assistant is never asked about it.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_export_vlan_off_ui.js [it|en]
const { openPage } = require("./_export_page.js");
const lang = process.argv[2] || "it";
const k = openPage(lang, false);
const { check, click, q, qa, wait } = k;

(async () => {
  await wait(800);
  await k.openWindow();
  await click("[data-xp='dest:dev']");
  check(!!q(".xp-days") && !!q("[data-xp='go']"), "la finestra per lo sviluppatore e' quella di sempre (grafico dei giorni e tasto Esporta)");
  check(!q(".xv-adv") && !q(".xv-chk") && !q("[data-xp^='vlan']") && !q(".xv-guide") && !q(".xv-pop"), "senza debug: nessuna sezione, nessun pulsante, nessuna guida, nessun riquadro");
  check(!/VLAN/.test(k.dlg().textContent), "senza debug la parola VLAN non compare nella finestra");
  check(qa(".mi-actions button").length === 2, "i tasti sono due: Annulla ed Esporta");
  await click("[data-xp='go']");
  const body = k.reqs("/api/export/jobs").filter((c) => c.method === "POST")[0].body;
  check(body.dest === "dev" && !("survey" in body), "la richiesta di esportazione non porta «survey»");
  check(k.reqs("/api/export/survey/check").length === 0, "Home Assistant non viene mai interrogato per l'opzione");
  k.finish();
})().catch((e) => { console.log("ECCEZIONE:", e && e.stack || e); process.exit(1); });
