// Where the pause menu goes (pausePlacement, a pure function): centred on the button, as wide as the room inside the card allows (never past the right edge of the card
// when the button is at its usual place), not wider than the window, never narrower than the minimum, and always inside the window. Needs only Node (no jsdom).
// from the vedetta/ folder:  node ../tests/ui/check_pause_place.js
const path = require("path");
const { pathToFileURL } = require("url");

let failed = 0;
function check(cond, msg) { if (cond) console.log("ok:", msg); else { failed++; console.log("FALLITO:", msg); } }

(async () => {
  let mod;
  try {
    mod = await import(pathToFileURL(path.join(__dirname, "..", "..", "vedetta", "app", "frontend", "ha", "js", "pause-place.js")).href);
  } catch (e) {
    console.log("FALLITO: il modulo pause-place.js non si carica: " + e.message);
    process.exit(1);
  }
  const { pausePlacement, PAUSE_MAX_W, PAUSE_MIN_W, PAUSE_EDGE } = mod;
  check(PAUSE_MAX_W === 232 && PAUSE_MIN_W === 184 && PAUSE_EDGE === 8, "le misure: al massimo 232 px, almeno 184, 8 px dai bordi");

  // the wide layout: a card of 380 px, the button (28 px) whose centre is 118 px from the right edge of the card
  const card = { left: 100, right: 480 }, btn = { left: 348, width: 28 };
  let p = mod.pausePlacement(btn, card, 1286);
  check(p.width === 220, "nel layout largo il menu e' largo 220 px (il posto che c'e' da qui al bordo della scheda)");
  check(p.left + p.width / 2 === btn.left + btn.width / 2, "ed e' centrato sul pulsante");
  check(p.left + p.width <= card.right - PAUSE_EDGE, "e non esce dal bordo destro della scheda (resta a 8 px)");
  check(p.originX === 110, "l'animazione parte dal centro del pulsante (110 px dal bordo sinistro del menu)");

  // a phone: the card nearly as wide as the window
  p = pausePlacement({ left: 252, width: 28 }, { left: 8, right: 368 }, 376);
  check(p.width === 188 && p.left + p.width / 2 === 266, "su un telefono resta centrato sul pulsante, largo 188 px");
  check(p.left >= PAUSE_EDGE && p.left + p.width <= 376 - PAUSE_EDGE, "e dentro la finestra");

  // the button very near the edge of the card: the minimum width, centred if the window allows it
  p = pausePlacement({ left: 106, width: 28 }, { left: 0, right: 200 }, 1000);
  check(p.width === PAUSE_MIN_W, "con poco posto il menu non scende sotto il minimo (184 px)");
  check(p.left + p.width / 2 === 120, "e resta centrato sul pulsante");

  // the button at the left edge of the window: it cannot be centred, it stays inside
  p = pausePlacement({ left: 6, width: 28 }, { left: 0, right: 380 }, 1000);
  check(p.left === PAUSE_EDGE && p.originX === 12, "vicino al bordo sinistro della finestra il menu sta a 8 px e l'animazione parte ancora dal pulsante");

  // a window narrower than the maximum
  p = pausePlacement({ left: 100, width: 28 }, { left: 0, right: 300 }, 200);
  check(p.width === 184 && p.left === PAUSE_EDGE, "in una finestra stretta il menu e' largo come la finestra meno i bordi");

  // never wider than the maximum even with a huge card
  p = pausePlacement({ left: 700, width: 28 }, { left: 0, right: 1500 }, 1600);
  check(p.width === PAUSE_MAX_W, "mai piu' largo di 232 px, anche con molto posto");

  console.log(failed ? "FALLITI: " + failed : "TUTTO OK");
  process.exit(failed ? 1 : 0);
})();
