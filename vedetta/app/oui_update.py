"""Aggiornamento del database dei prefissi MAC dai registri pubblici dell'IEEE
(MA-L 24 bit, MA-M 28 bit, MA-S 36 bit e i vecchi IAB, 36 bit). La copia
scaricata sta in config/oui-ieee.txt (un deploy sostituisce app/, config/ no)
e ha la precedenza su quella inclusa nell'app. Usata dall'interfaccia, dalla
manutenzione notturna e da tools/update_oui.py."""
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
MIN_BLOCKS = 40000          # sotto questa soglia il file e' sospetto: si rifiuta
MAX_BYTES = 40 * 1024 * 1024  # per file: il piu' grande (MA-L) pesa circa 4 MB
TIMEOUT = 60
AUTO_UPDATE_DAYS = 30


class OuiUpdateError(Exception):
    """code: "network" (download non riuscito), "invalid" (non e' un registro IEEE),
    "too_small" (troppo pochi blocchi), "write" (scrittura non riuscita)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


_LEGAL = {"LTD": "Ltd", "INC": "Inc", "CO": "Co", "CORP": "Corp", "GMBH": "GmbH", "SRL": "Srl",
          "SPA": "SpA", "LLC": "LLC", "PTE": "Pte", "PTY": "Pty", "KG": "KG", "BV": "BV", "NV": "NV"}


def tidy_name(name: str) -> str:
    """Nome del registro IEEE pulito: entita' HTML (&amp;) risolte e, se e' tutto
    in maiuscolo, scritto con le iniziali maiuscole (le sigle di 3 lettere o meno,
    come NEC o TP, restano come sono; le forme legali diventano Ltd, Inc, GmbH...)."""
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
    """Righe "PREFISSO[/bit] Nome" (prefisso esadecimale maiuscolo, es. BC2411,
    00155D4/28) da un CSV dei registri IEEE (Registry, Assignment, Organization
    Name, ...). I bit dipendono dalla lunghezza dell'assegnazione: 6 cifre = 24,
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
    """(contenuto del file, numero di blocchi) da uno o piu' CSV IEEE.
    OuiUpdateError se non sono registri validi o hanno meno di min_blocks blocchi."""
    if isinstance(texts, str):
        texts = [texts]
    rows = [row for text in texts for row in convert_ieee(text)]
    if not rows:
        raise OuiUpdateError("invalid")
    if len(rows) < min_blocks:
        raise OuiUpdateError("too_small", str(len(rows)))
    return HEADER + "\n".join(rows) + "\n", len(rows)


def download(urls=None) -> list[str]:
    """Scarica i registri IEEE (uno per URL). Basta un errore per rifiutare tutto:
    un aggiornamento a meta' lascerebbe una tabella incompleta."""
    texts = []
    for url in urls or URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read(MAX_BYTES + 1)
        except Exception as exc:  # rete assente, DNS, HTTP, timeout
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
    """Converte, controlla e installa i registri IEEE in config/ (senza rete: e'
    la parte testabile). Non tocca nulla se i controlli falliscono."""
    from . import vendor_lookup  # import tardivo: tools/update_oui.py usa solo convert/build
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
    """Scarica e installa (bloccante: da chiamare in un thread)."""
    try:
        result = install(download())
    except OuiUpdateError as exc:
        logger.warning("Aggiornamento prefissi MAC non riuscito (%s)", exc)
        raise
    logger.info("Prefissi MAC aggiornati dall'IEEE: %d blocchi", result["blocks"])
    return result


def meta() -> dict:
    """{"updated": timestamp|None, "blocks": int|None} dal file utente."""
    data = brands._read(brands._USER_PATH).get("oui_meta")
    data = data if isinstance(data, dict) else {}
    updated = data.get("updated")
    return {"updated": updated if isinstance(updated, (int, float)) else None,
            "blocks": data.get("blocks") if isinstance(data.get("blocks"), int) else None}


def auto_update_enabled() -> bool:
    return brands._read(brands._USER_PATH).get("auto_update") is True


def is_due(days: int = AUTO_UPDATE_DAYS) -> bool:
    """Vero se l'ultimo aggiornamento scaricato ha piu' di `days` giorni (o non c'e')."""
    updated = meta()["updated"]
    return updated is None or time.time() - updated > days * 86400
