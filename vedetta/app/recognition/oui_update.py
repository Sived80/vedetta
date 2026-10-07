"""Update of the MAC prefix database from the public IEEE registries
(MA-L 24 bit, MA-M 28 bit, MA-S 36 bit and the old IABs, 36 bit). The downloaded
copy lives in config/oui-ieee.txt (a deploy replaces app/, not config/)
and takes precedence over the one included in the app. Used by the interface, by
the nightly maintenance and by tools/update_oui.py."""
import csv
import html
import io
import logging
import os
import re
import tempfile
import time
import urllib.request

from . import brands

logger = logging.getLogger("dashboard")

BASE_URL = "https://standards-oui.ieee.org/"
URLS = [BASE_URL + "oui/oui.csv", BASE_URL + "oui28/mam.csv",
        BASE_URL + "oui36/oui36.csv", BASE_URL + "iab/iab.csv"]
USER_AGENT = "Vedetta (+https://github.com/Sived80/vedetta)"
HEADER = "# generato da tools/update_oui.py (registri IEEE MA-L/MA-M/MA-S/IAB, https://standards-oui.ieee.org/)\n"
MIN_BLOCKS = 40000          # below this threshold the file is suspect: it is rejected
MAX_BYTES = 40 * 1024 * 1024  # per file: the largest (MA-L) weighs about 4 MB
TIMEOUT = 60
AUTO_UPDATE_DAYS = 30


class OuiUpdateError(Exception):
    """code: "network" (download failed), "invalid" (not an IEEE registry),
    "too_small" (too few blocks), "write" (write failed)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


_LEGAL = {"LTD": "Ltd", "INC": "Inc", "CO": "Co", "CORP": "Corp", "GMBH": "GmbH", "SRL": "Srl",
          "SPA": "SpA", "LLC": "LLC", "PTE": "Pte", "PTY": "Pty", "KG": "KG", "BV": "BV", "NV": "NV"}


def tidy_name(name: str) -> str:
    """Cleaned-up IEEE registry name: HTML entities (&amp;) resolved and, if it is all
    uppercase, written with initial capitals (acronyms of 3 letters or fewer,
    like NEC or TP, stay as they are; legal forms become Ltd, Inc, GmbH...)."""
    name = html.unescape(" ".join(name.split()))
    if not name.isupper():
        return name

    def fix(match: re.Match) -> str:
        word = match.group(0)
        if word in _LEGAL:
            return _LEGAL[word]
        return word.capitalize() if len(word) > 3 else word
    return re.sub(r"[A-Za-z]+", fix, name)


def convert_ieee(text: str) -> list[str]:
    """Rows "PREFIX[/bit] Name" (uppercase hexadecimal prefix, e.g. BC2411,
    00155D4/28) from a CSV of the IEEE registries (Registry, Assignment, Organization
    Name, ...). The bits depend on the length of the assignment: 6 digits = 24,
    7 = 28, 9 = 36."""
    rows = []
    for rec in csv.reader(io.StringIO(text.lstrip("\ufeff"))):
        if len(rec) < 3 or rec[0].strip() in ("Registry", ""):
            continue
        assignment, name = rec[1].strip().upper(), tidy_name(rec[2])
        if not name or not re.fullmatch(r"[0-9A-F]+", assignment) or len(assignment) not in (6, 7, 9):
            continue
        bits = len(assignment) * 4
        rows.append(f"{assignment}{'' if bits == 24 else '/' + str(bits)} {name}")
    return rows


def build(texts, min_blocks: int = MIN_BLOCKS) -> tuple[str, int]:
    """(file content, number of blocks) from one or more IEEE CSVs.
    OuiUpdateError if they are not valid registries or have fewer than min_blocks blocks."""
    if isinstance(texts, str):
        texts = [texts]
    rows = [row for text in texts for row in convert_ieee(text)]
    if not rows:
        raise OuiUpdateError("invalid")
    if len(rows) < min_blocks:
        raise OuiUpdateError("too_small", str(len(rows)))
    return HEADER + "\n".join(rows) + "\n", len(rows)


def download(urls=None) -> list[str]:
    """Downloads the IEEE registries (one per URL). A single error is enough to reject everything:
    a half update would leave an incomplete table."""
    texts = []
    for url in urls or URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read(MAX_BYTES + 1)
        except Exception as exc:  # network down, DNS, HTTP, timeout
            raise OuiUpdateError("network", f"{url}: {exc}") from exc
        if len(raw) > MAX_BYTES:
            raise OuiUpdateError("invalid", "file troppo grande")
        texts.append(raw.decode("utf-8", errors="replace"))
    return texts


def write_atomic(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".oui-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def install(texts, min_blocks: int = MIN_BLOCKS) -> dict:
    """Converts, checks and installs the IEEE registries in config/ (no network: it is
    the testable part). Touches nothing if the checks fail."""
    from . import vendor_lookup  # late import: tools/update_oui.py only uses convert/build
    content, blocks = build(texts, min_blocks)
    try:
        write_atomic(vendor_lookup.USER_OUI_PATH, content)
    except OSError as exc:
        raise OuiUpdateError("write", str(exc)) from exc
    vendor_lookup._load_tables.cache_clear()
    now = time.time()
    try:
        brands.update_user({"oui_meta": {"updated": now, "blocks": blocks}})
    except OSError as exc:
        logger.warning("Metadati aggiornamento prefissi MAC non salvati: %s", exc)
    return {"blocks": blocks, "updated": now}


def update() -> dict:
    """Downloads and installs (blocking: to be called in a thread)."""
    try:
        result = install(download())
    except OuiUpdateError as exc:
        logger.warning("Aggiornamento prefissi MAC non riuscito (%s)", exc)
        raise
    logger.info("Prefissi MAC aggiornati dall'IEEE: %d blocchi", result["blocks"])
    return result


def meta() -> dict:
    """{"updated": timestamp|None, "blocks": int|None} from the user file."""
    data = brands._read(brands._USER_PATH).get("oui_meta")
    data = data if isinstance(data, dict) else {}
    updated = data.get("updated")
    return {"updated": updated if isinstance(updated, (int, float)) else None,
            "blocks": data.get("blocks") if isinstance(data.get("blocks"), int) else None}


def auto_update_enabled() -> bool:
    return brands._read(brands._USER_PATH).get("auto_update") is True


def is_due(days: int = AUTO_UPDATE_DAYS) -> bool:
    """True if the last downloaded update is more than `days` days old (or there is none)."""
    updated = meta()["updated"]
    return updated is None or time.time() - updated > days * 86400
