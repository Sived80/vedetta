import { I } from "./core.js";

// Icons of the Network card that have a part of their own to animate (the CSS turns the marked group around the centre of the 24 px box).

// The Vedetta radar logo, in its own colours (it does not follow the theme).
export function logoHTML() {
  return '<svg class="net-logo" viewBox="0 0 1024 1024" role="img" aria-label="Vedetta"><circle cx="512" cy="512" r="480" fill="#12283a"/>' +
    '<g fill="none" stroke="#40d89f" stroke-width="14"><circle cx="512" cy="512" r="459"/><circle cx="512" cy="512" r="295"/><circle cx="512" cy="512" r="144"/></g>' +
    '<line x1="516" y1="508" x2="845" y2="176" stroke="#7effc5" stroke-width="22" stroke-linecap="round"/>' +
    '<circle cx="681" cy="441" r="37" fill="#ffc850"/><circle cx="317" cy="653" r="37" fill="#ffc850"/></svg>';
}

// A library icon whose single path sits in a group with the given class.
export function movingIcon(name, groupClass) {
  return '<svg class="mdi" viewBox="0 0 24 24" aria-hidden="true"><g class="' + groupClass + '"><path d="' + I.paths[name] + '"/></g></svg>';
}

// Radar with a sweeping line (the "all devices" deep search).
export function radarIcon() {
  return '<svg class="mdi radar" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true">' +
    '<circle cx="12" cy="12" r="9.2"/><circle cx="12" cy="12" r="4.8"/><g class="sweep"><line x1="12" y1="12" x2="18.4" y2="5.6" stroke-width="2.2"/></g>' +
    '<circle cx="16" cy="15" r="1.5" fill="currentColor" stroke="none"/></svg>';
}
