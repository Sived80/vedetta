// Small inline SVG charts of the rotating tile of the Network card. Colours come from the CSS classes (40-network.css).

function fix(n) { return n.toFixed(1); }

// Sparkline with area. The last value, the lowest and the highest are marked with the same colours as the min / max chips.
export function spark(values, w, h) {
  if (values.length < 2) return "";
  const lo = Math.min.apply(null, values), hi = Math.max.apply(null, values);
  const pad = (hi - lo) * 0.12 || 1, min = lo - pad, max = hi + pad, px = 4, py = 4;
  const pts = values.map(function (v, i) { return [px + i * (w - 2 * px) / (values.length - 1), h - py - (v - min) / (max - min) * (h - 2 * py)]; });
  const line = pts.map(function (p) { return fix(p[0]) + "," + fix(p[1]); }).join(" ");
  const last = pts[pts.length - 1], iMin = values.indexOf(lo), iMax = values.indexOf(hi);
  function dot(p, cls, r) { return '<circle class="' + cls + '" cx="' + fix(p[0]) + '" cy="' + fix(p[1]) + '" r="' + r + '"></circle>'; }
  return '<svg class="sp-svg" viewBox="0 0 ' + w + " " + h + '" preserveAspectRatio="none" aria-hidden="true">' +
    '<polygon class="sp-area" points="' + fix(pts[0][0]) + "," + h + " " + line + " " + fix(last[0]) + "," + h + '"></polygon>' +
    '<polyline class="sp-line" points="' + line + '"></polyline>' +
    dot(pts[iMin], "sp-min", 2.4) + dot(pts[iMax], "sp-max", 2.4) + dot(last, "sp-last", 2.8) + "</svg>";
}

// Mini bars (the last one highlighted), scaled between the lowest and the highest value.
export function bars(values, w, h) {
  if (!values.length) return "";
  const lo = Math.min.apply(null, values), span = Math.max.apply(null, values) - lo, gap = 2, bw = (w - (values.length - 1) * gap) / values.length;
  return '<svg class="sp-svg" viewBox="0 0 ' + w + " " + h + '" aria-hidden="true">' + values.map(function (v, i) {
    const bh = span ? 5 + (v - lo) / span * (h - 5) : h * 0.6;
    return '<rect class="cb' + (i === values.length - 1 ? " now" : "") + '" x="' + fix(i * (bw + gap)) + '" y="' + fix(h - bh) + '" width="' + fix(bw) + '" height="' + fix(bh) + '" rx="2"></rect>';
  }).join("") + "</svg>";
}

// Donut: the share `part` of `total` (accent) and the rest (amber), with a small gap between the two arcs.
export function donut(part, total) {
  const r = 9, c = 2 * Math.PI * r, a = total ? c * part / total : 0, gap = 2.2;
  function arc(cls, len, off) { return '<circle class="' + cls + '" cx="12" cy="12" r="' + r + '" stroke-dasharray="' + len.toFixed(2) + " " + c.toFixed(2) + '" stroke-dashoffset="' + off.toFixed(2) + '"></circle>'; }
  const rest = c - a;
  return '<svg class="donut" viewBox="0 0 24 24" aria-hidden="true"><g transform="rotate(-90 12 12)" fill="none" stroke-width="4">' +
    '<circle class="dn-track" cx="12" cy="12" r="' + r + '"></circle>' +
    (a > gap ? arc("dn-ok", a - gap, 0) : "") + (rest > gap ? arc("dn-wait", rest - gap, -a) : "") + "</g></svg>";
}
