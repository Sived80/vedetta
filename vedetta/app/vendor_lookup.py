from functools import lru_cache
from pathlib import Path

from . import dhcp
from .brands import normalize_brand, resolve

OUI_PATH = Path(__file__).resolve().parent / "data" / "oui-ieee.txt"
# Copia scaricata dal web (oui_update.py): sta in config/ perche' un deploy
# sostituisce app/. Se esiste ha la precedenza su quella inclusa nell'app.
from .paths import data_path
USER_OUI_PATH = data_path("oui-ieee.txt")


def _active_path() -> Path:
    return USER_OUI_PATH if USER_OUI_PATH.exists() else OUI_PATH


def _stamp(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _tables() -> dict[int, dict[str, str]]:
    """Tabelle correnti; si ricaricano da sole quando il file cambia (mtime)."""
    path = _active_path()
    return _load_tables(str(path), _stamp(path))


@lru_cache(maxsize=1)
def _load_tables(path_str: str | None = None, stamp: float | None = None) -> dict[int, dict[str, str]]:
    """{bit: {prefisso esadecimale: nome registrato}} per i tre registri IEEE:
    MA-L (24 bit), MA-M (28 bit), MA-S (36 bit). Gli argomenti servono solo da
    chiave di cache (file usato e sua data di modifica)."""
    tables: dict[int, dict[str, str]] = {24: {}, 28: {}, 36: {}}
    path = Path(path_str) if path_str else _active_path()
    if not path.exists():
        return tables
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("#"):
            continue
        prefix, _, name = line.partition(" ")
        prefix, _, bits = prefix.partition("/")
        tables.setdefault(int(bits or 24), {})[prefix.upper()] = name.strip()
    return tables


def oui_stats() -> dict:
    """Numero di blocchi caricati, origine ("downloaded" = copia in config/) e
    data di modifica del file in uso."""
    path = _active_path()
    return {"blocks": sum(len(t) for t in _tables().values()),
            "source": "downloaded" if path == USER_OUI_PATH else "bundled",
            "mtime": _stamp(path)}


def is_private_mac(mac: str | None) -> bool:
    """Bit U/L del primo byte: indirizzo assegnato localmente (MAC "privato" o
    casuale di telefoni e portatili, ma anche di macchine virtuali)."""
    try:
        return bool(int(mac.replace("-", ":").split(":")[0], 16) & 0x02)
    except (AttributeError, ValueError):
        return False


def lookup_registrant(mac: str | None) -> str | None:
    """Nome registrato all'IEEE (legale, es. "Hong Kong Bouffalo Lab Limited"),
    con corrispondenza piu' lunga: prima i blocchi da 36 bit, poi 28, poi 24."""
    if not mac:
        return None
    digits = mac.replace(":", "").replace("-", "").upper()
    if len(digits) != 12 or is_private_mac(mac):
        return None
    tables = _tables()
    for bits in (36, 28, 24):
        found = tables.get(bits, {}).get(digits[: bits // 4])
        if found:
            return found
    return None


def lookup_vendor(mac: str | None) -> str | None:
    """Marca dedotta dal prefisso del MAC: il nome registrato ripulito (senza
    "Inc.", "Co., Ltd." ecc.) e ricondotto alla marca nota quando c'e'.
    None per i MAC casuali e per i prefissi non registrati."""
    registrant = lookup_registrant(mac)
    return normalize_brand(registrant) if registrant else None


def resolve_brand(mac: str | None, raw_vendor: str | None = None, names: list[str] | tuple = ()) -> str | None:
    """Marca del PRODOTTO per le scansioni (None se non nota: un chip Espressif o
    una scheda virtuale non sono una marca, vedi brands.resolve): prefisso del MAC
    (database completo), altrimenti il nome grezzo dato da nmap/arp-scan ripulito;
    poi nome del dispositivo e impronta DHCP, come fa la scheda del dispositivo."""
    return resolve_vendor_info(mac, raw_vendor, names)["brand"]


def resolve_vendor_info(mac: str | None, raw_vendor: str | None = None, names: list[str] | tuple = ()) -> dict:
    """{"vendor": produttore del prefisso MAC, "vendor_role", "brand"} per gli elenchi
    di host (nuovi dispositivi, ricerca): il produttore e' sempre mostrabile, la
    marca solo quando e' davvero quella del prodotto."""
    oui = lookup_vendor(mac)
    if oui is None and raw_vendor and not is_private_mac(mac):
        oui = normalize_brand(raw_vendor)
    found = resolve(oui, names=list(names), os_family=dhcp.os_family(mac))
    return {"vendor": oui, "vendor_role": found["role"] or ("private" if is_private_mac(mac) else None),
            "brand": found["brand"]}
