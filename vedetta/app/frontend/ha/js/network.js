import { $, api, esc, t } from "./core.js";
import { S, fmtLeft, pauseLeft, snack } from "./core-ui.js";
import { closePopups, menuGroup, pill } from "./core-menu.js";
import { onPoll } from "./live.js";
import { pausePlacement } from "./pause-place.js";

// ------------------------------------------------------------- pause
export var pauseEl = $("pause-menu"), liveEl = $("live");
function buildPause() {
  let html;
  if (S.poll.paused) {
    var left = pauseLeft();
    html = menuGroup(t("js.ha.pause.paused"), pill("lg", "resume", "1", false, t("js.ha.pause.resume"))) +
      '<div class="menu-hint">' + esc(left === Infinity ? t("js.ha.pause.idle") : t("js.ha.pause.idle_left", { left: fmtLeft(left) })) + "</div>";
  } else {
    html = menuGroup(t("js.ha.pause.title"), [15, 60, 480].map(function (n) {
      return pill("md", "pause", n, false, t("js.ha.pause.opt_" + n));
    }).join("") + pill("lg full", "pause", 0, false, t("js.ha.pause.opt_0"))) +
      '<div class="menu-hint">' + esc(t("js.ha.pause.hint")) + "</div>";
  }
  pauseEl.innerHTML = html;
}
export function togglePause(open) {
  if (open === undefined) open = pauseEl.hidden;
  if (open) {
    closePopups("pause");
    buildPause();
    var r = liveEl.getBoundingClientRect(), place = pausePlacement(r, $("card-network").getBoundingClientRect(), window.innerWidth);
    pauseEl.style.top = Math.round(r.bottom + 4) + "px";
    pauseEl.style.right = "auto";
    pauseEl.style.maxHeight = Math.max(160, window.innerHeight - r.bottom - 16) + "px";
    pauseEl.style.width = place.width + "px";                // centred on the button and inside the card (see pause-place.js)
    pauseEl.style.left = place.left + "px";
    pauseEl.style.transformOrigin = place.originX + "px top";
  }
  pauseEl.hidden = !open;
  liveEl.setAttribute("aria-expanded", String(open));
  if (open) { var f = pauseEl.querySelector(".menu-item"); if (f) f.focus(); }
}
liveEl.addEventListener("click", function (e) { e.stopPropagation(); togglePause(); });
pauseEl.addEventListener("click", function (e) {
  const item = e.target.closest(".menu-item");
  if (!item) return;
  const req = item.dataset.resume
    ? api("/api/pause", { method: "DELETE" })
    : api("/api/pause", { method: "POST", json: { minutes: +item.dataset.pause } });
  togglePause(false);
  req.then(function (ev) {
    onPoll(ev);
  }).catch(function () { snack(t("js.ha.toast.error"), { kind: "error" }); });
});
document.addEventListener("click", function (e) {
  if (!pauseEl.hidden && !e.target.closest("#pause-menu")) togglePause(false);
});
document.addEventListener("keydown", function (e) {
  if (e.key === "Escape" && !pauseEl.hidden) { togglePause(false); liveEl.focus(); }
});
window.addEventListener("resize", function () { if (!pauseEl.hidden) togglePause(false); });

