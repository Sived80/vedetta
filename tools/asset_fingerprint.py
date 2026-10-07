"""Fingerprint of the front-end the page receives (/static/ha/ha.js and ha.css): the same FNV-1a 32-bit over UTF-16 code units
that a browser computes with charCodeAt, so the files served by an installed Vedetta can be compared with the working copy.

    python tools/asset_fingerprint.py            # prints length and fingerprint of ha.js and ha.css as the app would serve them

In the browser console of a Vedetta page:
    function fnv(t){let h=0x811c9dc5;for(let i=0;i<t.length;i++){h^=t.charCodeAt(i);h=Math.imul(h,0x01000193)>>>0}return h.toString(16)}"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "vedetta"
sys.path.insert(0, str(ROOT))


def fnv(text: str) -> str:
    h = 0x811C9DC5
    data = text.encode("utf-16-le")
    for i in range(0, len(data), 2):
        h ^= data[i] | (data[i + 1] << 8)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return format(h, "x")


def served(name: str) -> str:
    try:
        from app import assets          # the bundler, once the front-end is split
        if name in assets.BUNDLES:
            return assets.bundle(name)
    except ImportError:
        pass
    return (ROOT / "app" / "static" / name).read_text(encoding="utf-8")


if __name__ == "__main__":
    for name in ("ha/ha.js", "ha/ha.css"):
        text = served(name)
        print("%-10s length %7d  fnv %s" % (name, len(text.encode("utf-16-le")) // 2, fnv(text)))
