"""No scroll bar is drawn in the page (a vertical bar at the side of a card looks dated): the reset hides it for every element, and no later rule may bring one back (scrollbar-width other than none, a styled ::-webkit-scrollbar that is shown)."""
import re
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "vedetta" / "app" / "frontend" / "ha" / "css"
base = (CSS / "10-base.css").read_text(encoding="utf-8")
assert re.search(r"\*\s*\{\s*scrollbar-width:\s*none;\s*\}", base) and re.search(r"\*::-webkit-scrollbar\s*\{\s*display:\s*none;\s*\}", base), "the reset must hide the scroll bar of every element"
for path in sorted(CSS.glob("*.css")):
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        assert not re.search(r"scrollbar-width:\s*(auto|thin)", line), f"{path.name}:{n}: a scroll bar is brought back"
print("TUTTO OK")
