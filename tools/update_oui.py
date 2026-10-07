"""Regenerates app/data/oui-ieee.txt from the public IEEE registries (MA-L 24 bit,
MA-M 28 bit, MA-S 36 bit and IAB). The logic lives in app/recognition/oui_update.py (also used by
the update from the web, which however writes to config/).

Usage:  python tools/update_oui.py                 (downloads the updated registries)
      python tools/update_oui.py a.csv b.csv...  (uses already downloaded copies)

Output format, one line per block:  PREFIX[/bit] Registered name
with the prefix in uppercase hexadecimal without colons (e.g. BC2411,
00155D4/28)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "vedetta"
sys.path.insert(0, str(ROOT))
from app.recognition import oui_update  # noqa: E402

OUT = ROOT / "app" / "data" / "oui-ieee.txt"


def main() -> None:
    if len(sys.argv) > 1:
        texts = [Path(a).read_text(encoding="utf-8", errors="replace") for a in sys.argv[1:]]
    else:
        texts = oui_update.download()
    content, blocks = oui_update.build(texts)
    oui_update.write_atomic(OUT, content)
    print(f"{blocks} blocchi scritti in {OUT}")


if __name__ == "__main__":
    main()
