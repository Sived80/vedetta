// The network (VLAN) option of the export is there for anyone (no debug mode needed) while the server offers it, and only for the developer export. With the server not offering it
// the window is the one everybody knows: nothing of the option exists in it, and Home Assistant is never asked about it.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_export_vlan_off_ui.js [it|en]
const { openPage } = require("./_export_page.js");
const lang = process.argv[2] || "it";
const k = openPage(lang, false);
const { check, click, q, qa, wait } = k;
k.server.info.survey = false;        // the server does not offer the option (network_survey.ENABLED off)

(async () => {
  await wait(800);
  await k.openWindow();
  await click("[data-xp='dest:dev']");
  check(!!q(".xp-days") && !!q("[data-xp='go']"), "la finestra per lo sviluppatore e' quella di sempre (grafico dei giorni e tasto Esporta)");
  check(!q(".xv-adv") && !q(".xv-chk") && !q("[data-xp^='vlan']") && !q(".xv-guide") && !q(".xv-pop"), "con il server che non la offre: nessuna sezione, nessun pulsante, nessuna guida, nessun riquadro");
  check(!/VLAN/.test(k.dlg().textContent), "con il server che non la offre la parola VLAN non compare nella finestra");
  check(qa(".mi-actions button").length === 2, "i tasti sono due: Annulla ed Esporta");
  await click("[data-xp='go']");
  const body = k.reqs("/api/export/jobs").filter((c) => c.method === "POST")[0].body;
  check(body.dest === "dev" && !("survey" in body), "la richiesta di esportazione non porta «survey»");
  check(k.reqs("/api/export/survey/check").length === 0, "Home Assistant non viene mai interrogato per l'opzione");
  k.finish();
})().catch((e) => { console.log("ECCEZIONE:", e && e.stack || e); process.exit(1); });
