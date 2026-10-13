"""The front-end of the /ha page, kept in several files.

The script is a set of ES modules (app/frontend/ha/js): one file for each part of the page (the base, the export, the deep search, the network card, the tiles, the devices found, the log, the "More info"
sheet, the start), each one importing what it uses of the others and exporting what the others use. The page loads the entry module (app.js) and the browser follows the imports. The files are served one by one
(main.py) and always checked again (`Cache-Control: no-cache` with an ETag: a file that did not change costs a 304), so that after a deploy nobody keeps an old part; the entry is asked for with a version that
changes with the content. The style is kept in parts too (app/frontend/ha/css) and joined in the order of the names into the one file ha.css. No build step and nothing to install."""
import hashlib
from pathlib import Path

FRONTEND = Path(__file__).resolve().parent / "frontend"
MODULES = FRONTEND / "ha" / "js"
BUNDLES = {"ha/ha.css": ("ha/css", ".css")}
MEDIA = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
STATIC = Path(__file__).resolve().parent / "static"

_cache: dict = {}


def parts(name: str) -> list[Path]:
    """The files of a joined style, in the order they are joined."""
    folder, ext = BUNDLES[name]
    return sorted((FRONTEND / folder).glob("*" + ext))


def bundle(name: str) -> str:
    """The joined text of a style. Read again only when a part changes (name, size or date)."""
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


def module_files() -> list[Path]:
    return sorted(MODULES.glob("*.js"))


def js_source() -> str:
    """The text of all the modules, one after the other (for the checks and the tools that look for what the script uses: keys of translations, icons)."""
    return "".join(p.read_text(encoding="utf-8") for p in module_files())


def js_version() -> str:
    """For ?v= of the entry module: changes when any module changes (name, size or date)."""
    files = module_files()
    key = tuple((p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in files)
    hit = _cache.get("js")
    if hit and hit[0] == key:
        return hit[1]
    digest = hashlib.sha1(b"".join(p.read_bytes() for p in files)).hexdigest()[:12]
    _cache["js"] = (key, digest)
    return digest


def static_version(rel_path: str) -> str:
    """Modification date of the static file, to append as ?v= in the URL: the browser treats every different value as a different resource, so after a deploy
    it always downloads the new version instead of serving the old one from cache (no "do a hard refresh" after every change)."""
    if rel_path == "ha/js":
        return js_version()
    if rel_path in BUNDLES:
        return version(rel_path)
    try:
        return str(int((STATIC / rel_path).stat().st_mtime))
    except OSError:
        return "0"


def media_type(name: str) -> str:
    return MEDIA[BUNDLES[name][1]]
