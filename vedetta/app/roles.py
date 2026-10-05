"""Chi fa cosa nella rete: gateway, server DHCP, server DNS, router, access point,
ripetitore Wi-Fi, e quali client passano da un ripetitore.

Fonti (solo protocolli standard, nessuna API di produttore):
  gateway   percorso predefinito del sistema (/proc/net/route)
  dhcp      DHCP DISCOVER di prova (offerta mai accettata) e opzione 54 (Server
            Identifier) letta dall'ascolto DHCP passivo (dhcp.py)
  dns       host della LAN che rispondono a una query DNS standard (UDP 53)
  router/ap/repeater  tipo di dispositivo dichiarato via UPnP (deviceType:
            InternetGatewayDevice, WLANAccessPointDevice, WFADevice) o nome/modello
            dichiarato ("Repeater", "Extender")
  via       stesso MAC su piu' IP nella tabella ARP: un ripetitore che non fa WDS
            "presta" il proprio MAC ai client collegati a lui (MAC translation). Il
            proprietario del MAC e' l'IP che si dichiara ripetitore/AP; se nessuno lo
            fa, il ripetitore resta "non identificato".
Ogni ruolo porta la sua fonte: nessun ruolo viene dedotto senza una di queste prove."""
import asyncio
import ipaddress
import re
import time

from . import dhcp, discovery
from .applog import logger
from .identity import default_gateway
from .newdevices import normalize_mac

REFRESH_S = 600
DHCP_SERVER_MAX_AGE_S = 7 * 86400
ROLE_ORDER = ("gateway", "dhcp", "dns", "router", "ap", "repeater")
_REPEATER = re.compile(r"repeater|extender|range\s*ext|ripetitore|mesh\s*(point|node|satellite)", re.I)
_AP_TYPES = ("WLANAccessPointDevice", "WFADevice")
_ROUTER_TYPES = ("InternetGatewayDevice", "WANDevice", "WANConnectionDevice")

_state: dict = {"by_ip": {}, "via": {}, "names": {}, "types": {}, "dhcp": [], "ts": 0}
DISCOVER_EVERY_S = 6 * 3600
_offers: dict = {"list": [], "ts": 0.0}
_internet: dict = {"data": None, "ts": 0.0}
_task: asyncio.Task | None = None
_on_change = None
_on_alert = None


def compute(*, gateway: str | None, dhcp_servers, dns_servers, upnp: dict[str, dict], arp: dict[str, dict],
            offers: list[dict] | None = None) -> dict:
    """Pura: dalle prove raccolte ai ruoli per IP, con la fonte di ciascuno."""
    by_ip: dict[str, dict[str, str]] = {}

    def add(ip, role, source):
        if ip:
            by_ip.setdefault(ip, {}).setdefault(role, source)

    add(gateway, "gateway", "route")
    for offer in offers or []:
        add(offer.get("server"), "dhcp", "offer")
        for ip in offer.get("dns") or []:
            add(ip, "dns", "offer")
    for ip in dhcp_servers:
        add(ip, "dhcp", "dhcp")
    for ip in dns_servers:
        add(ip, "dns", "dns")
    names: dict[str, str] = {}
    for ip, info in upnp.items():
        types = set(info.get("types") or [])
        text = " ".join(filter(None, [info.get("name"), info.get("model")]))
        if types & set(_ROUTER_TYPES):
            add(ip, "router", "upnp")
        if types & set(_AP_TYPES):
            add(ip, "ap", "upnp")
        if _REPEATER.search(text):
            add(ip, "repeater", "upnp")
        label = info.get("name") or info.get("model")
        if label:
            names[ip] = label
    # Stesso MAC su piu' IP: client dietro un ripetitore con MAC translation.
    groups: dict[str, list[str]] = {}
    for ip, host in arp.items():
        mac = normalize_mac(host.get("mac"))
        if mac:
            groups.setdefault(mac, []).append(ip)
    via: dict[str, dict] = {}
    for mac, ips in groups.items():
        if len(ips) < 2:
            continue
        owners = [ip for ip in ips if {"repeater", "ap"} & set(by_ip.get(ip, {}))]
        owner = owners[0] if len(owners) == 1 else None
        for ip in ips:
            if ip != owner:
                via[ip] = {"ip": owner, "name": names.get(owner) if owner else None, "mac": mac}
        if owner:
            add(owner, "repeater", by_ip[owner].get("repeater") or by_ip[owner].get("ap") or "arp")
    ordered = {ip: {r: roles[r] for r in ROLE_ORDER if r in roles} for ip, roles in by_ip.items()}
    types = {ip: list(info.get("types") or []) for ip, info in upnp.items() if info.get("types")}
    # Cio' che i server DHCP distribuiscono ai client (una voce per server).
    dhcp_cfg = [{k: o[k] for k in ("server", "router", "dns", "domain", "lease", "netmask") if o.get(k)} for o in offers or []]
    return {"by_ip": ordered, "via": via, "names": names, "types": types, "dhcp": dhcp_cfg}


def snapshot() -> dict:
    return {"by_ip": _state["by_ip"], "via": _state["via"], "names": _state["names"], "dhcp": _state.get("dhcp") or [],
            "internet": _internet["data"], "types": _state.get("types") or {}}


def event() -> dict:
    return {"type": "roles", **snapshot()}


def roles_for(ip: str | None) -> list[str]:
    return list((_state["by_ip"].get(ip or "") or {}).keys())


def upnp_types(ip: str | None) -> list[str]:
    """Tipi di dispositivo UPnP dichiarati da quell'IP (es. MediaRenderer, dial)."""
    return list((_state.get("types") or {}).get(ip or "") or [])


# ------------------------------------------------------------------ raccolta
def _dns_query(qid: int) -> bytes:
    """Query DNS standard (RFC 1035): A per example.com, ricorsione richiesta."""
    import struct
    qname = b"".join(bytes([len(p)]) + p for p in (b"example", b"com")) + b"\x00"
    return struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + qname + struct.pack(">HH", 1, 1)


class _DnsReply(asyncio.DatagramProtocol):
    def __init__(self, qid: int) -> None:
        self.qid = qid
        self.ok = asyncio.get_running_loop().create_future()

    def datagram_received(self, data: bytes, addr) -> None:
        # Qualunque risposta (anche NXDOMAIN o REFUSED) con lo stesso id e il bit QR
        # prova che su quell'IP risponde un server DNS.
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


async def dns_servers(ips) -> list[str]:
    """Gli IP che rispondono davvero a una query DNS (UDP 53)."""
    ips = sorted(set(ips))
    results = await asyncio.gather(*(answers_dns(ip) for ip in ips), return_exceptions=True)
    return [ip for ip, ok in zip(ips, results) if ok is True]


async def refresh(state) -> None:
    from .netutil import get_local_network  # tardivo: evita cicli all'import
    try:
        _, own_ip = await get_local_network()
    except Exception:
        own_ip = None
    upnp_job = discovery.ssdp_devices(own_ip)
    arp_job = state.arp_snapshot()
    jobs = [upnp_job, arp_job]
    discover = time.time() - _offers["ts"] > DISCOVER_EVERY_S
    if discover:
        from . import scanner
        jobs.append(scanner.dhcp_discover())
    check_net = time.time() - _internet["ts"] > DISCOVER_EVERY_S
    if check_net:
        from . import internet
        jobs.append(internet.check())
    results = await asyncio.gather(*jobs, return_exceptions=True)
    if check_net:
        net = results.pop()
        if isinstance(net, Exception):
            logger.warning("Controllo dell'uscita verso internet fallito (%r)", net)
        else:
            changed_net = _internet["data"] != net
            from . import journal
            journal.add("detail", "journal.internet_" + ("cgnat" if net.get("cgnat") else "double" if net.get("double_nat") else "direct"),
                        icon="router-wireless")
            _internet.update(data=net, ts=time.time())
            if changed_net and _on_change:
                _on_change(event())
    upnp, arp = results[0], results[1]
    if discover:
        if isinstance(results[2], Exception):
            logger.warning("DHCP DISCOVER di prova fallito (%r)", results[2])
        else:
            _offers.update(list=results[2], ts=time.time())
            servers_seen = sorted({o["server"] for o in results[2]})
            from . import journal
            for o in results[2]:
                journal.add("detail", "journal.dhcp", icon="lan", server=o["server"],
                            router=",".join(o.get("router") or ["-"]), dns=",".join(o.get("dns") or ["-"]))
            logger.info("DHCP DISCOVER: %s", "; ".join(
                f"server {o['server']} -> gateway {','.join(o.get('router') or ['-'])}, DNS {','.join(o.get('dns') or ['-'])}"
                for o in results[2]) or "nessuna offerta")
            if len(servers_seen) > 1 and _on_alert:
                _on_alert(f"Piu' server DHCP in rete: {', '.join(servers_seen)}", "alert.dhcp_multiple",
                          servers=", ".join(servers_seen))
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
    result = compute(gateway=gateway, dhcp_servers=servers, dns_servers=dns, upnp=upnp, arp=arp, offers=_offers["list"])
    changed = {k: result[k] for k in ("by_ip", "via", "names", "dhcp")} != snapshot() or result["types"] != _state.get("types")
    _state.update(result, ts=now)
    if changed:
        logger.info("Ruoli di rete: %s; tramite ripetitore: %s",
                    ", ".join(f"{ip}={'/'.join(r)}" for ip, r in result["by_ip"].items()) or "-",
                    ", ".join(sorted(result["via"])) or "-")
        from . import journal
        journal.add("detail", "journal.roles", icon="router-wireless",
                    roles=", ".join(f"{ip} {'/'.join(r)}" for ip, r in result["by_ip"].items()) or "-",
                    via=", ".join(sorted(result["via"])) or "-")
        if _on_change:
            _on_change(event())


def _is_ipv4(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).version == 4
    except ValueError:
        return False


async def _loop(state) -> None:
    await asyncio.sleep(20)  # dopo il primo ciclo di controllo (tabella ARP pronta)
    while True:
        try:
            await refresh(state)
        except Exception:
            logger.exception("Calcolo dei ruoli di rete fallito")
        await asyncio.sleep(REFRESH_S)


def start(state, on_change=None, on_alert=None) -> None:
    global _task, _on_change, _on_alert
    _on_change = on_change
    _on_alert = on_alert
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(state))


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
