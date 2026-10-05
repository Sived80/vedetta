from functools import lru_cache
from pathlib import Path

from . import dhcp
from .brands import normalize_brand, resolve

OUI_PATH = Path(__file__).resolve().parent / "data" / "oui-ieee.txt"
# Copy downloaded from the web (oui_update.py): it lives in config/ because a deploy
# replaces app/. If it exists it takes precedence over the one bundled with the app.
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
    """Current tables; they reload by themselves when the file changes (mtime)."""
    path = _active_path()
    return _load_tables(str(path), _stamp(path))


@lru_cache(maxsize=1)
def _load_tables(path_str: str | None = None, stamp: float | None = None) -> dict[int, dict[str, str]]:
    """{bit: {hex prefix: registered name}} for the three IEEE registries:
    MA-L (24 bit), MA-M (28 bit), MA-S (36 bit). The arguments only serve as
    cache key (file used and its modification date)."""
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
    """Number of blocks loaded, origin ("downloaded" = copy in config/) and
    modification date of the file in use."""
    path = _active_path()
    return {"blocks": sum(len(t) for t in _tables().values()),
            "source": "downloaded" if path == USER_OUI_PATH else "bundled",
            "mtime": _stamp(path)}


def is_private_mac(mac: str | None) -> bool:
    """U/L bit of the first byte: locally assigned address ("private" or
    random MAC of phones and laptops, but also of virtual machines)."""
    try:
        return bool(int(mac.replace("-", ":").split(":")[0], 16) & 0x02)
    except (AttributeError, ValueError):
        return False


def lookup_registrant(mac: str | None) -> str | None:
    """Name registered with the IEEE (legal, e.g. "Hong Kong Bouffalo Lab Limited"),
    with longest match: 36-bit blocks first, then 28, then 24."""
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
    """Brand deduced from the MAC prefix: the cleaned-up registered name (without
    "Inc.", "Co., Ltd." etc.) and mapped to the known brand when there is one.
    None for random MACs and for unregistered prefixes."""
    registrant = lookup_registrant(mac)
    return normalize_brand(registrant) if registrant else None


def resolve_brand(mac: str | None, raw_vendor: str | None = None, names: list[str] | tuple = ()) -> str | None:
    """PRODUCT brand for scans (None if not known: an Espressif chip or
    a virtual board is not a brand, see brands.resolve): MAC prefix
    (full database), otherwise the raw name given by nmap/arp-scan, cleaned up;
    then device name and DHCP fingerprint, as the device card does."""
    return resolve_vendor_info(mac, raw_vendor, names)["brand"]


def resolve_vendor_info(mac: str | None, raw_vendor: str | None = None, names: list[str] | tuple = ()) -> dict:
    """{"vendor": MAC prefix manufacturer, "vendor_role", "brand"} for host
    lists (new devices, search): the manufacturer can always be shown, the
    brand only when it is truly the product's."""
    oui = lookup_vendor(mac)
    if oui is None and raw_vendor and not is_private_mac(mac):
        oui = normalize_brand(raw_vendor)
    found = resolve(oui, names=list(names), os_family=dhcp.os_family(mac))
    return {"vendor": oui, "vendor_role": found["role"] or ("private" if is_private_mac(mac) else None),
            "brand": found["brand"]}
