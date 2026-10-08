"""New devices on the network: compares the MACs seen via ARP (and DHCP) with the
already known ones, stored in the known_macs table of the SQLite history.

States: 'known' (configured or already seen), 'new' (never seen after the baseline,
to be reported), 'ignored' (discarded by the user). On the very first cycle (meta
key 'newdev_baseline' missing) all the MACs present become 'known' without
alerts: otherwise the whole LAN would appear "new". The evaluate function is
synchronous and has no dependencies on the app state, so it can be tested on its own."""
import ipaddress
import logging
import re
import time
from pathlib import Path

from .history import History, history
from ..recognition.vendor_lookup import lookup_vendor, resolve_vendor_info

logger = logging.getLogger("dashboard")

BASELINE_KEY = "newdev_baseline"

# MACs seen in the last cycle. A "new device" that is no longer on the network is
# not something the user can act on (the scan does not find it): it stays
# recorded but disappears from the counter and the list until it reappears.
_present: set[str] | None = None
_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def normalize_mac(mac: str | None) -> str | None:
    """MAC in uppercase with colons, None if invalid or unusable
    (all zeros, all F, multicast)."""
    if not mac:
        return None
    mac = mac.strip().upper().replace("-", ":")
    if not _MAC_RE.match(mac) or mac in ("00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"):
        return None
    if int(mac[:2], 16) & 0x01:
        return None
    return mac


def own_macs() -> set[str]:
    """MACs of the container's interfaces (not a "new" device)."""
    macs = set()
    try:
        for p in Path("/sys/class/net").iterdir():
            m = normalize_mac((p / "address").read_text().strip())
            if m:
                macs.add(m)
    except OSError:
        pass
    return macs


def observed_macs(arp_by_ip: dict[str, dict], dhcp_seen: dict[str, dict], skip_ips: set[str] = frozenset()) -> dict[str, dict]:
    """{MAC: {"ip", "hostname", "vendor"}} from ARP and DHCP. ARP gives the IP; the
    name comes from DHCP (also for MACs not seen in ARP)."""
    result: dict[str, dict] = {}
    for ip, host in arp_by_ip.items():
        mac = normalize_mac(host.get("mac"))
        if not mac or ip in skip_ips:
            continue
        result[mac] = {"ip": ip, "hostname": None, "vendor": resolve_vendor_info(mac, host.get("vendor"))["vendor"]}
    # DHCP is only used to give the name to the MACs currently seen on the network: a DHCP
    # request stays in the file forever, but the device may have been gone for
    # a while, and a MAC "present" only because of that cannot be found by the search.
    for raw, info in dhcp_seen.items():
        mac = normalize_mac(raw)
        if mac in result:
            result[mac]["hostname"] = info.get("hostname") or None
    return result


def _brand_fields(mac: str, hostname: str | None) -> dict:
    """Product brand (None if unknown) and role of the MAC manufacturer: the
    "vendor" of a new device is the board manufacturer, not the brand."""
    info = resolve_vendor_info(mac, None, [hostname] if hostname else [])
    return {"brand": info["brand"], "vendor_role": info["vendor_role"]}


def readable_label(row: dict) -> str:
    return row.get("hostname") or row.get("brand") or row.get("vendor") or row.get("ip") or row["mac"]


def _in_blocks(ip: str | None, blocks: tuple[str, ...]) -> bool:
    try:
        return bool(ip) and any(ipaddress.ip_address(ip) in ipaddress.ip_network(b) for b in blocks)
    except ValueError:
        return False


def evaluate(observed: dict[str, dict], configured_ips: set[str], configured_macs: set[str],
             ignore_macs: set[str] = frozenset(), hist: History = history, now: float | None = None,
             baseline_blocks: tuple[str, ...] = ()) -> tuple[list[dict], list[dict]]:
    """Updates known_macs with the observed MACs. Returns (new_to_alert,
    full_list_of_the_new). A MAC that is already 'new' is not alerted again.
    baseline_blocks: blocks of a large network asked for the first time (scan/arpplan.py): what lives there now is the starting
    point, like the first search of the network, not a flood of new devices."""
    global _present
    now = time.time() if now is None else now
    observed = {m: o for m, o in observed.items() if m not in ignore_macs}
    _present = set(observed)
    rows = hist.known_all()

    if hist.meta_get(BASELINE_KEY) is None:
        if not observed:
            return [], []  # empty ARP (error or network off): the baseline waits
        for mac, obs in observed.items():
            hist.known_set(mac, now, obs["ip"], obs["vendor"] or lookup_vendor(mac), obs["hostname"], "known")
        hist.meta_set(BASELINE_KEY, str(int(now)))
        logger.info("Nuovi dispositivi: baseline di %d MAC, nessun avviso", len(observed))
        return [], []

    fresh: list[dict] = []
    for mac, obs in observed.items():
        configured = (obs["ip"] in configured_ips) or (mac in configured_macs)
        row = rows.get(mac)
        vendor = obs["vendor"] or lookup_vendor(mac)
        if row is None:
            status = "known" if (configured or _in_blocks(obs["ip"], baseline_blocks)) else "new"
            hist.known_set(mac, now, obs["ip"], vendor, obs["hostname"], status)
            if status == "new":
                fresh.append({"mac": mac, "ip": obs["ip"], "vendor": vendor, "hostname": obs["hostname"],
                              "first_seen": now, **_brand_fields(mac, obs["hostname"])})
            continue
        status = "known" if (row["status"] == "new" and configured) else row["status"]
        ip = obs["ip"] or row["ip"]
        hostname = obs["hostname"] or row["hostname"]
        vendor = vendor or row["vendor"]
        if (status, ip, hostname, vendor) != (row["status"], row["ip"], row["hostname"], row["vendor"]):
            hist.known_set(mac, row["first_seen"], ip, vendor, hostname, status)
    return fresh, list_new(hist)


def sync_present(macs: set[str]) -> None:
    """After a search: the only MACs present are those the search actually found
    (so the counter does not report what the button then does not find)."""
    global _present
    _present = {m for m in (normalize_mac(x) for x in macs) if m}


def list_new(hist: History = history) -> list[dict]:
    """The 'new' devices, in the API format."""
    out = []
    for r in hist.known_all().values():
        if r["status"] == "new" and (_present is None or r["mac"] in _present):
            out.append({
                "mac": r["mac"], "ip": r["ip"], "vendor": lookup_vendor(r["mac"]) or r["vendor"],
                "hostname": r["hostname"], "first_seen": r["first_seen"], **_brand_fields(r["mac"], r["hostname"]),
            })
    return sorted(out, key=lambda d: d["first_seen"])


def ignore(macs: list[str] | None, hist: History = history) -> list[dict]:
    """Marks the given MACs as 'ignored' (empty/missing list = all the 'new');
    returns the updated list of the 'new'."""
    wanted = {normalize_mac(m) for m in macs or []} - {None}
    if macs and not wanted:
        return list_new(hist)  # only invalid MACs: nothing to do (not "all")
    hist.known_ignore(sorted(wanted) if wanted else None)
    return list_new(hist)


def list_ignored(hist: History = history) -> list[dict]:
    """The MACs detected on the network that the user has ignored."""
    out = [{"mac": r["mac"], "ip": r["ip"], "vendor": lookup_vendor(r["mac"]) or r["vendor"], "hostname": r["hostname"],
            "first_seen": r["first_seen"]}
           for r in hist.known_all().values() if r["status"] == "ignored"]
    return sorted(out, key=lambda d: d["first_seen"])


def unignore(mac: str, hist: History = history) -> bool:
    """Moves an ignored MAC back among the new ones (it reappears if it is on the network)."""
    mac = normalize_mac(mac)
    row = next((r for k, r in hist.known_all().items() if mac and k.upper() == mac), None)
    if not row or row["status"] != "ignored":
        return False
    hist.known_set(row["mac"], row["first_seen"], row["ip"], row["vendor"], row["hostname"], "new")
    return True


def event(devices: list[dict]) -> dict:
    return {"type": "new_devices", "count": len(devices), "devices": devices}
