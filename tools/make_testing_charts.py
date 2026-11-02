"""Draws the pictures of docs/TESTING.md as SVG, a light and a dark one each (the page picks the one of the reader's theme): the way a change goes, the findings of the network
doctor on real exports before and after 0.11.0, and how soon a fault added to real history is raised. The numbers are written here; where they come from is said next to each.
    python tools/make_testing_charts.py          Output: docs/images/testing-*.svg"""
from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
# Colours validated with the dataviz palette checker (colour-blind separation, contrast) on both surfaces.
THEMES = {
    "light": {"bg": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "grid": "#e4e3df", "before": "#eb6834", "after": "#2a78d6", "box": "#f1f0ec"},
    "dark": {"bg": "#1a1a19", "ink": "#f0efec", "ink2": "#c3c2b7", "grid": "#33332f", "before": "#d95926", "after": "#3987e5", "box": "#262624"},
}
FONT = "font-family='-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif'"

# Exports with at least one finding, of the 28 different exports with two days of history or more (4 home networks): the judge of 0.10.0 against the one of 0.11.0 on the same
# exports, one judgment every two minutes (tools/replay_health_engine.py; the 0.10.0 judge from git archive v0.10.0).
EXPORTS = 28
BEFORE_AFTER = [("H05", "Restarts that repeat", 27, 1), ("H06", "Devices that drop together", 5, 0), ("H07", "A slower gateway", 0, 0)]
# A fault added to the real history of 3 networks: minutes until the finding is raised (the slowest of the three) - tools/replay_health_engine.py --inject.
DETECTION = [("H06", "6 devices drop together", 2, "1-2 min"), ("H07", "Gateway answers 3 ms slower", 13, "10-13 min"), ("H05", "A device restarts every 10 min", 44, "43-44 min")]
STEPS = ["Test written first", "326 automatic tests", "Real exports replayed", "Virtual LAN", "CI on Linux", "Debug app at home", "Release"]


def svg(w: int, h: int, t: dict, body: str, title: str) -> str:
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}' role='img' aria-label='{escape(title)}' {FONT}>"
            f"<title>{escape(title)}</title><rect width='{w}' height='{h}' rx='12' fill='{t['bg']}'/>{body}</svg>\n")


def text(x, y, s, fill, size=14, anchor="start", weight=400) -> str:
    return f"<text x='{x}' y='{y}' fill='{fill}' font-size='{size}' text-anchor='{anchor}' font-weight='{weight}'>{escape(str(s))}</text>"


def bar(x, y, w, h, fill) -> str:
    """A horizontal bar with its far end rounded and its start square on the baseline; nothing for a zero."""
    if w <= 0:
        return ""
    r = min(4, w / 2, h / 2)
    return f"<path d='M{x},{y} h{w - r} a{r},{r} 0 0 1 {r},{r} v{h - 2 * r} a{r},{r} 0 0 1 -{r},{r} h-{w - r} z' fill='{fill}'/>"


def before_after(t: dict) -> str:
    w, left, right, top, row = 760, 250, 60, 92, 74
    scale = (w - left - right) / EXPORTS
    body = text(24, 34, "Findings of the network doctor on real home networks", t["ink"], 18, weight=600)
    body += text(24, 58, f"Exports with at least one finding, of {EXPORTS} (4 networks)", t["ink2"], 13)
    for i, (key, colour) in enumerate((("0.10.0 (before)", "before"), ("0.11.0 (after)", "after"))):
        x = left + i * 150
        body += f"<rect x='{x}' y='68' width='12' height='12' rx='2' fill='{t[colour]}'/>" + text(x + 18, 79, key, t["ink2"], 13)
    for g in range(0, EXPORTS + 1, 7):
        x = left + g * scale
        body += f"<line x1='{x:.1f}' y1='{top}' x2='{x:.1f}' y2='{top + row * len(BEFORE_AFTER)}' stroke='{t['grid']}'/>" + text(f"{x:.1f}", top + row * len(BEFORE_AFTER) + 18, g, t["ink2"], 12, "middle")
    for i, (rule, name, before, after) in enumerate(BEFORE_AFTER):
        y = top + i * row + 14
        body += text(24, y + 14, name, t["ink"], 14, weight=600) + text(24, y + 32, rule, t["ink2"], 12)
        for j, (value, colour) in enumerate(((before, "before"), (after, "after"))):
            yy = y + j * 24
            body += bar(left, yy, value * scale, 20, t[colour]) + text(left + value * scale + 8, yy + 15, value, t["ink"], 13)
    return svg(w, top + row * len(BEFORE_AFTER) + 34, t, body, "Findings of the network doctor on 28 real exports: before and after 0.11.0")


def detection(t: dict) -> str:
    w, left, right, top, row = 760, 270, 110, 76, 46
    longest = max(m for _r, _n, m, _l in DETECTION)
    scale = (w - left - right) / longest
    body = text(24, 34, "How soon a fault is noticed", t["ink"], 18, weight=600)
    body += text(24, 58, "A fault added to the real history of 3 home networks, slowest of the three", t["ink2"], 13)
    for i, (rule, name, minutes, label) in enumerate(DETECTION):
        y = top + i * row
        body += text(24, y + 15, name, t["ink"], 14) + text(24, y + 32, rule, t["ink2"], 12)
        body += bar(left, y + 4, minutes * scale, 20, t["after"]) + text(left + minutes * scale + 8, y + 19, label, t["ink"], 13)
    y = top + len(DETECTION) * row + 12
    body += text(24, y, "Not raised: a phone whose Wi-Fi sleeps, a gateway 2 ms slower.", t["ink2"], 13)
    return svg(w, y + 22, t, body, "How soon the network doctor raises a fault added to real history")


def pipeline(t: dict) -> str:
    w, box_w, gap, top = 980, 120, 18, 64
    body = text(24, 34, "The way of a change", t["ink"], 18, weight=600)
    x = 24
    for i, step in enumerate(STEPS):
        words = step.split(" ")
        half = (len(words) + 1) // 2
        lines = [" ".join(words[:half]), " ".join(words[half:])] if len(step) > 14 else [step]
        body += f"<rect x='{x}' y='{top}' width='{box_w}' height='64' rx='10' fill='{t['box']}' stroke='{t['after'] if i == len(STEPS) - 1 else t['grid']}'/>"
        for k, line in enumerate(lines):
            body += text(x + box_w / 2, top + 37 - 9 * (len(lines) - 1) + 18 * k, line, t["ink"], 13, "middle")
        if i < len(STEPS) - 1:
            ax = x + box_w + 3
            body += f"<path d='M{ax},{top + 32} h{gap - 8} m-5,-5 l5,5 l-5,5' fill='none' stroke='{t['ink2']}' stroke-width='2'/>"
        x += box_w + gap
    body += text(24, top + 96, "A step that fails sends the change back to the start.", t["ink2"], 13)
    return svg(x - gap + 24, top + 112, t, body, "The way of a change: from the test written first to the release")


def main() -> None:
    for name, draw in (("testing-before-after", before_after), ("testing-detection", detection), ("testing-pipeline", pipeline)):
        for theme, colours in THEMES.items():
            (OUT / f"{name}-{theme}.svg").write_text(draw(colours), encoding="utf-8")
            print("written", f"docs/images/{name}-{theme}.svg")


if __name__ == "__main__":
    main()
