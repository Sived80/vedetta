"""Who does what on the network: gateway, DHCP server, DNS server, router, access point,
Wi-Fi repeater, and which clients go through a repeater.

Sources (standard protocols only, no vendor API):
  gateway   system default route (/proc/net/route)
  dhcp      test DHCP DISCOVER (offer never accepted) and option 54 (Server
            Identifier) read from passive DHCP listening (scan/dhcp.py)
  dns       LAN hosts that answer a standard DNS query (UDP 53)
  router/ap/repeater  device type declared via UPnP (deviceType:
            InternetGatewayDevice, WLANAccessPointDevice, WFADevice) or declared
            name/model ("Repeater", "Extender")
  via       same MAC on multiple IPs in the ARP table: a repeater that does not do WDS
            "lends" its own MAC to the clients connected to it (MAC translation). The
            owner of the MAC is the IP that declares itself repeater/AP; if nobody
            does, the repeater remains "unidentified".
Each role carries its source: no role is inferred without one of these proofs."""
import asyncio
import ipaddress
import re
import time

from ..scan import dhcp, discovery, touch_policy
from ..applog import logger
from .identity import default_gateway
from ..storage.newdevices import normalize_mac
from ..storage import devices_config, journal
import contextlib

REFRESH_S = 600
DHCP_SERVER_MAX_AGE_S = 7 * 86400
ROLE_ORDER = ("gateway", "dhcp", "dns", "router", "ap", "repeater")
_REPEATER = re.compile(r"repeater|extender|range\s*ext|ripetitore|mesh\s*(point|node|satellite)", re.IGNORECASE)
_AP_TYPES = ("WLANAccessPointDevice", "WFADevice")
_ROUTER_TYPES = ("InternetGatewayDevice", "WANDevice", "WANConnectionDevice")

DISCOVER_EVERY_S = 6 * 3600


class _Runtime:
    """What the module keeps between two refreshes, in one place (one object instead of loose globals)."""

    def __init__(self) -> None:
        self.roles: dict = {"by_ip": {}, "via": {}, "names": {}, "types": {}, "dhcp": [], "ts": 0}     # the last result
        self.offers: dict = {"list": [], "ts": 0.0}          # the answer of the last test DHCP DISCOVER
        self.internet: dict = {"data": None, "ts": 0.0}      # the last check of the way out to the internet
        # The active network checks are given by main when it starts roles (roles decides WHEN to run them; it does not import the scanner).
        self.dhcp_discover = None
        self.internet_check = None
        self.task: asyncio.Task | None = None
        self.on_change = None
        self.on_alert = None


_rt = _Runtime()


def compute(*, gateway: str | None, dhcp_servers, dns_servers, upnp: dict[str, dict], arp: dict[str, dict],
            offers: list[dict] | None = None) -> dict:
    """Pure: from the collected evidence to the roles per IP, with the source of each."""
    by_ip, add_, ip_ = _collect_gateway_and_dhcp_roles(dhcp_servers, gateway, offers)
    ip_, names, types = _collect_dns_and_upnp_roles(dns_servers, add_, ip_, upnp)
    via = _find_clients_behind_repeaters(arp, ip_, add_, by_ip, names)
    return _build_roles_result(via, names, types, offers, by_ip, upnp)


def _collect_gateway_and_dhcp_roles(dhcp_servers, gateway, offers):
    ip_ = None            # set below on some paths only
    by_ip: dict[str, dict[str, str]] = {}

    def add(ip, role, source):
        if ip:
            by_ip.setdefault(ip, {}).setdefault(role, source)
    add_ = add

    add_(gateway, "gateway", "route")
    for offer in offers or []:
        add_(offer.get("server"), "dhcp", "offer")
        for ip_ in offer.get("dns") or []:
            add_(ip_, "dns", "offer")
    for ip_ in dhcp_servers:
        add_(ip_, "dhcp", "dhcp")
    return by_ip, add_, ip_


def _collect_dns_and_upnp_roles(dns_servers, add_, ip_, upnp):
    types = None            # set below on some paths only
    for ip_ in dns_servers:
        add_(ip_, "dns", "dns")
    names: dict[str, str] = {}
    for ip_, info in upnp.items():
        types = set(info.get("types") or [])
        text = " ".join(filter(None, [info.get("name"), info.get("model")]))
        if types & set(_ROUTER_TYPES):
            add_(ip_, "router", "upnp")
        if types & set(_AP_TYPES):
            add_(ip_, "ap", "upnp")
        if _REPEATER.search(text):
            add_(ip_, "repeater", "upnp")
        label = info.get("name") or info.get("model")
        if label:
            names[ip_] = label
    return ip_, names, types


def _find_clients_behind_repeaters(arp, ip_, add_, by_ip, names):
    # Same MAC on multiple IPs: clients behind a repeater with MAC translation.
    groups = _group_ips_by_mac(arp)
    via: dict[str, dict] = {}
    for mac, ips in groups.items():
        if len(ips) < 2:
            continue
        owner = _repeater_owner(ips, by_ip)
        _add_clients_via(via, ips, owner, names, mac)
        if owner:
            add_(owner, "repeater", by_ip[owner].get("repeater") or by_ip[owner].get("ap") or "arp")
    return via


def _group_ips_by_mac(arp):
    """MAC -> addresses that answer with it, in the order of the ARP table (hosts without a usable MAC are left out)."""
    groups: dict[str, list[str]] = {}
    for ip_, host in arp.items():
        mac = normalize_mac(host.get("mac"))
        if mac:
            groups.setdefault(mac, []).append(ip_)
    return groups


def _repeater_owner(ips, by_ip):
    """The one address among `ips` that declares itself repeater or AP; None if there is none or more than one."""
    owners = [ip for ip in ips if {"repeater", "ap"} & set(by_ip.get(ip, {}))]
    return owners[0] if len(owners) == 1 else None


def _add_clients_via(via, ips, owner, names, mac):
    """Every address of the group but the owner goes through the owner (or through an unidentified repeater)."""
    for ip_ in ips:
        if ip_ != owner:
            via[ip_] = {"ip": owner, "name": names.get(owner) if owner else None, "mac": mac}


def _build_roles_result(via, names, types, offers, by_ip, upnp) -> dict:
    ordered = _ordered_roles(by_ip)
    types = _declared_upnp_types(upnp)
    dhcp_cfg = _dhcp_handout(offers)
    return {"by_ip": ordered, "via": via, "names": names, "types": types, "dhcp": dhcp_cfg}


def _ordered_roles(by_ip):
    """The roles of every address in the fixed ROLE_ORDER."""
    return {ip: {r: roles[r] for r in ROLE_ORDER if r in roles} for ip, roles in by_ip.items()}


def _declared_upnp_types(upnp):
    """UPnP device types declared by each address (only the addresses that declare some)."""
    return {ip: list(info.get("types") or []) for ip, info in upnp.items() if info.get("types")}


def _dhcp_handout(offers):
    """What the DHCP servers hand out to the clients (one entry per server, only the values that are set)."""
    return [{k: o[k] for k in ("server", "router", "dns", "domain", "lease", "netmask") if o.get(k)} for o in offers or []]


def snapshot() -> dict:
    return {"by_ip": _rt.roles["by_ip"], "via": _rt.roles["via"], "names": _rt.roles["names"], "dhcp": _rt.roles.get("dhcp") or [],
            "internet": _rt.internet["data"], "types": _rt.roles.get("types") or {}}


def event() -> dict:
    return {"type": "roles", **snapshot()}


def roles_for(ip: str | None) -> list[str]:
    return list((_rt.roles["by_ip"].get(ip or "") or {}).keys())


def upnp_types(ip: str | None) -> list[str]:
    """UPnP device types declared by that IP (e.g. MediaRenderer, dial)."""
    return list((_rt.roles.get("types") or {}).get(ip or "") or [])


class _DnsReply(asyncio.DatagramProtocol):
    def __init__(self, qid: int) -> None:
        self.qid = qid
        self.ok = asyncio.get_running_loop().create_future()

    def datagram_received(self, data: bytes, addr) -> None:
        # Any reply (even NXDOMAIN or REFUSED) with the same id and the QR bit
        # proves that a DNS server answers on that IP.
        if len(data) >= 12 and int.from_bytes(data[:2], "big") == self.qid and data[2] & 0x80 and not self.ok.done():
            self.ok.set_result(True)

    def error_received(self, exc) -> None:
        if not self.ok.done():
            self.ok.set_result(False)


async def answers_dns(ip: str, timeout: float = 1.0) -> bool:
    import random
    loop = asyncio.get_running_loop()
    qid = random.randint(1, 65535)
    try:
        transport, proto = await loop.create_datagram_endpoint(lambda: _DnsReply(qid), remote_addr=(ip, 53))
    except OSError:
        return False
    try:
        transport.sendto(_dns_query(qid))
        return await asyncio.wait_for(proto.ok, timeout)
    except (asyncio.TimeoutError, OSError):
        return False
    finally:
        transport.close()


# ------------------------------------------------------------------ collection
def _dns_query(qid: int) -> bytes:
    """Standard DNS query (RFC 1035): A for example.com, recursion desired."""
    import struct
    qname = b"".join(bytes([len(p)]) + p for p in (b"example", b"com")) + b"\x00"
    return struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + qname + struct.pack(">HH", 1, 1)


async def dns_servers(ips) -> list[str]:
    """The IPs that actually answer a DNS query (UDP 53)."""
    ips = sorted(set(ips))
    results = await asyncio.gather(*(answers_dns(ip) for ip in ips), return_exceptions=True)
    return [ip for ip, ok in zip(ips, results) if ok is True]


async def refresh(state) -> None:
    jobs, discover, own_ip = await _start_discovery_jobs(state)
    results = await _run_jobs_and_check_internet(jobs)
    upnp, arp = _record_dhcp_offers(discover, results)
    now, result, before, keys = await _compute_roles_snapshot(upnp, arp, own_ip)
    _store_roles_and_notify(result, now, keys, before)


def _untouchable_ips() -> frozenset:
    """The addresses of the cards that must not be touched (touch_policy): the search does not ask them anything."""
    return frozenset(d["ip"] for d in devices_config.load_devices() if not touch_policy.may_touch(d))


async def _start_discovery_jobs(state):
    own_ip = None            # set below on some paths only
    from ..netutil import get_local_network  # late import: avoids cycles at import time
    try:
        _, own_ip = await get_local_network()
    except Exception:
        own_ip = None
    upnp_job = discovery.ssdp_devices(own_ip, skip=_untouchable_ips())
    arp_job = state.arp_snapshot()
    jobs = [upnp_job, arp_job]
    discover = _rt.dhcp_discover is not None and time.time() - _rt.offers["ts"] > DISCOVER_EVERY_S
    if discover:
        jobs.append(_rt.dhcp_discover())
    return jobs, discover, own_ip


async def _run_jobs_and_check_internet(jobs):
    check_net = _rt.internet_check is not None and time.time() - _rt.internet["ts"] > DISCOVER_EVERY_S
    if check_net:
        jobs.append(_rt.internet_check())
    results = await asyncio.gather(*jobs, return_exceptions=True)
    if check_net:
        _record_internet(results.pop())
    return results


def _record_internet(net):
    if isinstance(net, Exception):
        logger.warning("Controllo dell'uscita verso internet fallito (%r)", net)
        return
    changed_net = _rt.internet["data"] != net
    if (net.get("checks") or {}).get("path", True):      # without the path check, "direct" would be a guess: nothing is written
        journal.add("detail", "journal.internet_" + ("cgnat" if net.get("cgnat") else "double" if net.get("double_nat") else "direct"),
                    icon="router-wireless")
    _rt.internet.update(data=net, ts=time.time())
    if changed_net and _rt.on_change:
        _rt.on_change(event())


def _record_dhcp_offers(discover, results):
    upnp, arp = results[0], results[1]
    if discover:
        _remember_dhcp_discover(results[2])
    return upnp, arp


def _remember_dhcp_discover(offers):
    """The answer of the test DHCP DISCOVER is kept; several DHCP servers raise an alert."""
    if isinstance(offers, Exception):
        logger.warning("DHCP DISCOVER di prova fallito (%r)", offers)
        return
    _rt.offers.update(list=offers, ts=time.time())
    servers_seen = sorted({o["server"] for o in offers})
    _journal_dhcp_offers(offers)
    _log_dhcp_offers(offers)
    if len(servers_seen) > 1 and _rt.on_alert:
        _rt.on_alert(f"Piu' server DHCP in rete: {', '.join(servers_seen)}", "alert.dhcp_multiple",
                  servers=", ".join(servers_seen))


def _journal_dhcp_offers(offers):
    for o in offers:
        journal.add("detail", "journal.dhcp", icon="lan", server=o["server"],
                    router=",".join(o.get("router") or ["-"]), dns=",".join(o.get("dns") or ["-"]))


def _log_dhcp_offers(offers):
    logger.info("DHCP DISCOVER: %s", "; ".join(
        f"server {o['server']} -> gateway {','.join(o.get('router') or ['-'])}, DNS {','.join(o.get('dns') or ['-'])}"
        for o in offers) or "nessuna offerta")


async def _compute_roles_snapshot(upnp, arp, own_ip):
    if isinstance(upnp, Exception):
        logger.warning("Ruoli: UPnP non disponibile (%r)", upnp)
        upnp = {}
    if isinstance(arp, Exception):
        arp = {}
    now = time.time()
    servers = [ip for ip, ts in dhcp.servers.items() if now - ts <= DHCP_SERVER_MAX_AGE_S]
    gateway = default_gateway()
    candidates = [ip for ip in arp if ip != own_ip] + ([gateway] if gateway else [])
    dns = await dns_servers(c for c in candidates if _is_ipv4(c))
    result = compute(gateway=gateway, dhcp_servers=servers, dns_servers=dns, upnp=upnp, arp=arp, offers=_rt.offers["list"])
    before, keys = snapshot(), ("by_ip", "via", "names", "dhcp", "types")
    return now, result, before, keys


def _is_ipv4(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).version == 4
    except ValueError:
        return False


def _store_roles_and_notify(result, now, keys, before):
    changed = {k: result[k] for k in keys} != {k: before[k] for k in keys}
    _rt.roles.update(result, ts=now)
    if changed:
        _announce_roles_change(result)


def _announce_roles_change(result):
    logger.info("Ruoli di rete: %s; tramite ripetitore: %s", _roles_summary(result["by_ip"], "="), _via_summary(result["via"]))
    journal.add("detail", "journal.roles", icon="router-wireless",
                roles=_roles_summary(result["by_ip"], " "), via=_via_summary(result["via"]))
    if _rt.on_change:
        _rt.on_change(event())


def _roles_summary(by_ip, sep):
    return ", ".join(f"{ip}{sep}{'/'.join(r)}" for ip, r in by_ip.items()) or "-"


def _via_summary(via):
    return ", ".join(sorted(via)) or "-"


def start(state, on_change=None, on_alert=None, dhcp_discover=None, internet_check=None) -> None:
    _rt.on_change = on_change
    _rt.on_alert = on_alert
    _rt.dhcp_discover = dhcp_discover
    _rt.internet_check = internet_check
    if _rt.task is None or _rt.task.done():
        _rt.task = asyncio.create_task(_loop(state))


async def _loop(state) -> None:
    await asyncio.sleep(20)  # after the first check cycle (ARP table ready)
    while True:
        try:
            await refresh(state)
        except Exception:
            logger.exception("Calcolo dei ruoli di rete fallito")
        await asyncio.sleep(REFRESH_S)


async def stop() -> None:
    if _rt.task:
        _rt.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _rt.task
        _rt.task = None
