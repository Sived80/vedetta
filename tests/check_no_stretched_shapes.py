"""An SVG stretched to a width of its own (preserveAspectRatio="none") draws a circle as an ellipse. The only stretched drawing allowed is a chart made of lines and areas whose stroke does not scale (vector-effect: non-scaling-stroke);
anything that has round shapes must keep its proportions (a square viewBox, or plain elements)."""
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent.parent / "vedetta" / "app" / "frontend"
ALLOWED = {"more-graph.js"}                     # the latency chart: two paths, the line is non-scaling-stroke (80-more-info.css)

found = []
for path in sorted(FRONTEND.rglob("*.js")):
    text = path.read_text(encoding="utf-8")
    if 'preserveAspectRatio="none"' in text:
        found.append(path.name)
        assert path.name in ALLOWED, f"{path.name}: a stretched SVG would draw round shapes as ellipses; use plain elements or a square viewBox"
        assert "<circle" not in text[text.index('preserveAspectRatio="none"'):][:400], f"{path.name}: a circle inside a stretched SVG"
css = (FRONTEND / "ha" / "css" / "80-more-info.css").read_text(encoding="utf-8")
assert "vector-effect: non-scaling-stroke" in css, "the stretched latency chart needs a stroke that does not scale"
print("TUTTO OK" if found else "TUTTO OK (nothing stretched)")
