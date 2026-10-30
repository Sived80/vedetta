// The network (VLAN) option of the export for the developer, in the debug mode: its own advanced section, a check button (default -> checking -> green with the number, or back to default with the
// guide open and a first line that says the normal export works without it), the small panel, the guide, Escape, and the request of the export. The words are read from the translation files.
// Needs jsdom (see check_evidence_ui.js).   from the vedetta/ folder:  node ../tests/ui/check_export_vlan_ui.js [it|en]
const { openPage } = require("./_export_page.js");
const lang = process.argv[2] || "it";
const k = openPage(lang, false);      // the debug mode is not needed any more: the option is there for anyone while the server offers it
const { check, click, q, qa, wait, text } = k;

(async () => {
  await wait(800);
  await k.openWindow();
  check(!q(".xv-adv"), "scelta di «per chi» ancora aperta: l'opzione non c'e'");
  await click("[data-xp='dest:dev']");
  check(!!q(".xv-adv") && q(".xv-advh").textContent.includes(text("adv_title")) && q(".xv-advh").textContent.includes(text("adv_text")), "per lo sviluppatore, senza bisogno del debug: sezione «opzione avanzata» con la frase che dice per chi e'");
  const btn = () => q(".xv-chk");
  check(btn().tagName === "BUTTON" && btn().getAttribute("data-state") === "idle" && btn().getAttribute("aria-pressed") === "false" && btn().textContent.includes(text("btn_idle")) && btn().textContent.includes(text("btn_idle_sub")), "pulsante di partenza: predefinito, non premuto, con la scritta e la riga che dice cosa fa");
  check(!!btn().closest(".mi-body") && !q(".mi-actions .xv-chk"), "il pulsante sta sotto le scelte normali, non tra Annulla ed Esporta");
  check(/VLAN/.test(btn().textContent) && /VLAN/.test(q(".xv-advh").textContent), "il pulsante e la sezione nominano le VLAN");
  check(k.reqs("/api/export/survey/check").length === 0, "aprire la finestra non legge Home Assistant: il controllo parte solo al tocco");

  // --- per me: nothing
  await click("[data-xp='cancel']");
  await click("[data-xp='dest:me']");
  check(!q(".xv-adv") && !q("[data-xp^='vlan']"), "per me: nessuna opzione");
  await click("[data-xp='cancel']");
  await click("[data-xp='dest:dev']");

  // --- data found: busy, then green with the number
  k.server.check = { state: "ok", clients: 12 };
  btn().click();
  check(btn().getAttribute("data-state") === "busy" && !!q(".xv-spin") && btn().getAttribute("aria-busy") === "true" && btn().textContent.includes(text("btn_busy")), "al tocco: «controllo in corso», cerchio che gira");
  await wait(60);
  check(btn().getAttribute("data-state") === "ok" && btn().getAttribute("aria-pressed") === "true" && btn().textContent.includes(text("btn_ok", 12)) && btn().textContent.includes(text("btn_ok_sub")), "dati trovati: VERDE con il numero e «tocca per togliere»");
  check(!q(".xv-guide"), "con i dati la guida resta chiusa");
  check(k.reqs("/api/export/survey/check").length === 1 && k.reqs("/api/export/survey/check")[0].method === "POST", "una sola richiesta, in POST");
  btn().click(); await wait(20);
  check(btn().getAttribute("data-state") === "idle" && k.reqs("/api/export/survey/check").length === 1, "un tocco sul verde lo toglie, senza nuove richieste");
  k.server.check = { state: "ok", clients: 1 };
  btn().click(); await wait(60);
  check(btn().textContent.includes(text("btn_ok", 1)), "con un solo dispositivo la scritta e' al singolare");
  btn().click(); await wait(20);

  // --- nothing found: back to default, guide open, calm banner first
  k.server.check = { state: "none", clients: 0 };
  btn().click(); await wait(60);
  check(btn().getAttribute("data-state") === "idle" && !!q(".xv-guide"), "nessun dato: il pulsante torna predefinito e si apre la guida");
  const banner = () => q(".xv-banner");
  check(!!banner() && banner().textContent.includes(text("why_none")) && banner().textContent.includes(text("notneeded")) && banner().textContent.includes(text("why_none_sub")), "la prima cosa che si legge: non ho trovato dati, l'opzione serve solo a chi ha piu' reti, l'export funziona lo stesso");
  check(qa(".xv-gs").length === 5 && qa(".xv-gs .xv-row").length === 15, "guida: 5 passi, ognuno con dove / cosa fai / devi vedere");
  const mistakes = Object.keys(k.L).filter((key) => /^js\.ha\.export\.vlan\.s\d_b\d_s$/.test(key)).length;
  check(mistakes >= 8 && qa(".xv-bad li").length === mistakes, "guida: tutti gli errori comuni dei testi sono elencati (" + mistakes + ")");
  const words = q(".xv-guide").textContent;
  check(["s1_b2_s", "s3_b2_s", "s3_b3_s", "s1_b1_s"].every((key) => words.includes(text(key))), "guida: nomina le schermate vere di Home Assistant (entita' disattivate, configurazione non riuscita...)");
  check(!!q("[data-xp='vlandone']") && q("[data-xp='vlandone']").textContent.includes(text("g_done")), "in fondo: «chiudi, esporto senza questi dati»");
  await click("[data-xp='vlandone']");
  check(!q(".xv-guide") && btn().getAttribute("data-state") === "idle", "il pulsante in fondo chiude la guida e lascia il pulsante predefinito");

  // --- Home Assistant cannot be read, and a failing request
  k.server.check = { state: "noha", clients: 0 };
  btn().click(); await wait(60);
  check(!!q(".xv-guide") && banner().textContent.includes(text("why_noha")) && banner().textContent.includes(text("notneeded")), "HA non leggibile: guida con un altro avviso e la stessa rassicurazione");
  await click("[data-xp='vlanclose']");
  k.server.check = "fail";
  btn().click(); await wait(60);
  check(!!q(".xv-guide") && banner().textContent.includes(text("why_noha")) && btn().getAttribute("data-state") === "idle", "se la richiesta stessa fallisce vale come «non leggibile», senza errori");
  await click("[data-xp='vlanclose']");

  // --- the small panel, the way to the guide, Escape
  await click("[data-xp='vlaninfo']");
  check(!!q(".xv-pop") && qa(".xv-pop .xv-stp").length === 3 && q(".xv-pop").textContent.includes(text("pop_masked")), "la «i»: riquadro con i 3 passi da fare prima in Home Assistant e «tutto e' mascherato e cifrato»");
  check(q(".xv-pop").lastElementChild.classList.contains("xv-pf") && !!q(".xv-pf [data-xp='vlanguide']"), "il pulsante della guida e' l'ultima cosa del riquadro, in basso a destra");
  const esc = () => { const ev = new k.win.Event("cancel", { cancelable: true }); k.dlg().dispatchEvent(ev); return ev.defaultPrevented; };
  check(esc() && !q(".xv-pop") && k.dlg().hasAttribute("open"), "Escape chiude prima il riquadro, non la finestra");
  await click("[data-xp='vlaninfo']");
  await click("[data-xp='vlanguide']");
  check(!!q(".xv-guide") && !q(".xv-pop") && !q(".xv-banner"), "la guida si apre anche dal riquadro (senza avviso) e il riquadro si chiude");
  check(esc() && !q(".xv-guide") && k.dlg().hasAttribute("open"), "Escape chiude la guida, non la finestra");
  check(!esc(), "senza guida ne' riquadro Escape non e' intercettato: chiude la finestra come sempre");

  // --- the request of the export
  await click("[data-xp='go']");
  const first = k.reqs("/api/export/jobs").filter((c) => c.method === "POST")[0];
  check(first && first.body && !("survey" in first.body), "pulsante non verde: l'export parte come sempre, senza «survey»");
  await click("[data-xp='stop']");
  k.server.check = { state: "ok", clients: 12 };
  btn().click(); await wait(60);
  await click("[data-xp='go']");
  const second = k.reqs("/api/export/jobs").filter((c) => c.method === "POST")[1];
  check(second && second.body && second.body.survey === true && second.body.dest === "dev", "pulsante verde: l'export parte con survey: true");
  await click("[data-xp='stop']");

  // --- the server says the survey is off: nothing
  await click("[data-xp='cancel']"); await click("[data-xp='cancel']");
  k.server.info.survey = false;
  await k.openWindow(); await click("[data-xp='dest:dev']");
  check(!q(".xv-adv"), "l'interruttore del progetto e' spento: l'opzione non c'e'");
  k.finish();
})().catch((e) => { console.log("ECCEZIONE:", e && e.stack || e); process.exit(1); });
