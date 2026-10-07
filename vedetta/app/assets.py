"""The front-end of the /ha page, kept in several files and served as one.

The source of ha.js and ha.css lives in app/frontend/ha/js/ and app/frontend/ha/css/, one file per part of the page (core,
export, deep search, network card, tiles, devices found, log, the "More info" dialog, start). The files are joined in the order of
their names (10-core.js, 20-export.js, ...) and the page receives a single /static/ha/ha.js and /static/ha/ha.css, exactly as
before the split: the same scope for the script, the same order for the style. No build step and nothing to install.

The JS parts are pieces of ONE function: the first part opens it, the last one closes it, so a part is not valid JavaScript on
its own (node --check is run on the joined file, see tests/check_frontend_bundle.py)."""
import hashlib
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent / "frontend"
BUNDLES = {"ha/ha.js": ("ha/js", ".js"), "ha/ha.css": ("ha/css", ".css")}
MEDIA = {".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}

_cache: dict = {}


def parts(name: str) -> list[Path]:
    """The files of a bundle, in the order they are joined."""
    folder, ext = BUNDLES[name]
    return sorted((FRONTEND / folder).glob("*" + ext))


def bundle(name: str) -> str:
    """The joined text. Read again only when a part changes (name, size or date)."""
    files = parts(name)
    key = tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in files)
    hit = _cache.get(name)
    if hit and hit[0] == key:
        return hit[1]
    text = "".join(p.read_text(encoding="utf-8") for p in files)
    _cache[name] = (key, text, hashlib.sha1(text.encode("utf-8")).hexdigest()[:12])
    return text


def version(name: str) -> str:
    """For ?v= in the page: changes when the content changes."""
    bundle(name)
    return _cache[name][2]


def media_type(name: str) -> str:
    return MEDIA[BUNDLES[name][1]]
