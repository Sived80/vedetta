import { S } from "./core-ui.js";

// Folding of the device groups (routers, servers...): the heading is the button, all groups start open and the closed ones are
// remembered by type in this browser (localStorage; a convenience: without it every group simply starts open).
const GROUPS_KEY = "vedetta-ha-groups";
function readClosedGroups() {
  try {
    const v = JSON.parse(localStorage.getItem(GROUPS_KEY));
    return v && Array.isArray(v.closed) ? v.closed : [];
  } catch (err) { return []; }
}
const closedGroups = readClosedGroups();

export function isClosed(type) { return closedGroups.indexOf(type) >= 0; }

function rememberGroup(type, shut) {
  const at = closedGroups.indexOf(type);
  if (shut && at < 0) closedGroups.push(type);
  if (!shut && at >= 0) closedGroups.splice(at, 1);
  try { localStorage.setItem(GROUPS_KEY, JSON.stringify({ closed: closedGroups })); } catch (err) { /* ignore */ }
}

// Draws a group as open or closed (heading and tiles, no other state).
export function paintFold(group, type) {
  const shut = isClosed(type);
  group.el.classList.toggle("is-closed", shut);
  group.el.querySelector(".heading").setAttribute("aria-expanded", String(!shut));
  group.grid.hidden = shut;
}

export function bindFold(container) {
  function foldToggle(e) {
    const head = e.target.closest(".heading");
    const sec = head && head.closest(".group");
    if (!sec || !S.groups[sec.dataset.type]) return false;
    rememberGroup(sec.dataset.type, !isClosed(sec.dataset.type));
    paintFold(S.groups[sec.dataset.type], sec.dataset.type);
    return true;
  }
  container.addEventListener("click", foldToggle);
  container.addEventListener("keydown", function (e) {
    if ((e.key === "Enter" || e.key === " ") && e.target.classList && e.target.classList.contains("heading") && foldToggle(e)) e.preventDefault();
  });
}
