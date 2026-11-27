// SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
import { $, esc, icon, t } from "./core.js";

// ------------------------------------------------- the notice of the first hours
// In the first 48 hours after the first start the recognition is still gathering clues and some brands and types can change (people saw brands they do
// not own in the first hours). The summary says until when (learning_until, seconds; null after): a small notice that can be closed. Closed, it does not
// come back in this browser (a convenience: localStorage, the time it was meant for, so a new installation shows it again); at that time it goes by itself.
var LEARNING_KEY = "vedetta-ha-learning-closed";
var learningEl = $("learning"), learningTimer = 0, learningFor = null;
function learningClosed(until) { try { return localStorage.getItem(LEARNING_KEY) === String(until); } catch (err) { return false; } }
function hideLearning() { if (learningEl) { learningEl.hidden = true; learningEl.innerHTML = ""; } learningFor = null; }
export function renderLearning(until) {
  if (!learningEl) return;
  clearTimeout(learningTimer);
  const left = typeof until === "number" ? until * 1000 - Date.now() : 0;
  if (left <= 0 || learningClosed(until)) { hideLearning(); return; }
  learningTimer = setTimeout(hideLearning, Math.min(left, 2147483647));
  if (learningFor === until) return;                 // already shown: nothing redrawn
  learningFor = until;
  const close = t("js.ha.more.close");
  learningEl.innerHTML = icon("information-outline") + '<span class="banner-text">' + esc(t("js.ha.learning.text")) + "</span>" +
    '<button type="button" class="icon-btn rp" data-learning-close title="' + esc(close) + '" aria-label="' + esc(close) + '">' + icon("close") + "</button>";
  learningEl.hidden = false;
}
if (learningEl) learningEl.addEventListener("click", function (e) {
  if (!e.target.closest("[data-learning-close]")) return;
  try { localStorage.setItem(LEARNING_KEY, String(learningFor)); } catch (err) { /* not remembered: closed for this page only */ }
  clearTimeout(learningTimer);
  hideLearning();
});
