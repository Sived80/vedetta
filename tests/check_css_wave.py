"""A rule that positions the direct <span> children of a button must leave the ripple alone. The click ripple is a <span class="wave"> appended inside every .rp element with
position: absolute and a size of twice the button; a rule like `#btn-scan > span { position: relative }` makes it part of the flow and the button grows to about 290 px for the 0.6 s
of the wave (it happened on the scan button: the circle moved aside and the tile shrank at every click). Such a rule must say :not(.wave)."""
import re
import sys
from pathlib import Path

CSS_DIR = Path(__file__).resolve().parents[1] / "vedetta" / "app" / "frontend" / "ha" / "css"
DIRECT_SPAN = re.compile(r">\s*span\b(?![\w-])")


def offenders(css: str) -> list[str]:
    """The selectors that position a direct span child without excluding the ripple."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = []
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector, body = m.group(1), m.group(2)
        if not re.search(r"(^|;|\s)position\s*:", body):
            continue
        for part in selector.split(","):
            if DIRECT_SPAN.search(part) and ".wave" not in part:
                out.append(" ".join(part.split()))
    return out


# the rule as it was: it must be caught; the fixed ones must not
assert offenders(".split #btn-scan > span { position: relative; top: 1px; }") == [".split #btn-scan > span"]
assert offenders(".a > span:not(.wave) { position: relative; }") == []
assert offenders(".a > span:not(.fill):not(.wave), .a > .mdi { position: relative; z-index: 1; }") == []
assert offenders(".a > span { color: red; }") == []                          # no position: nothing to say
assert offenders(".a > .mdi { position: relative; }") == []                  # an icon, not a span
assert offenders("@media (max-width: 440px) { .a > span { position: absolute; } }") == [".a > span"]

bad = {f.name: offenders(f.read_text(encoding="utf-8")) for f in sorted(CSS_DIR.glob("*.css"))}
bad = {k: v for k, v in bad.items() if v}
if bad:
    for name, sels in bad.items():
        print("FALLITO:", name, sels)
    sys.exit(1)
print("TUTTO OK")
