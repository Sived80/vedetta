import asyncio
import ssl
import ipaddress
import re
import struct
import time
import xml.etree.ElementTree as ET

from ..applog import logger
from ..formatters import is_useless_title, truncate_name
from ..iface import lan_iface
from .arpplan import parse_neighbors
from ..recognition.vendor_lookup import resolve_vendor_info

# The container runs on a shared, limited CPU: scanning -p- -sV -O on
# several weak IoT devices in true parallel makes them contend for the same CPU,
# slowing each one down until even the safety timeout (150s) can
# trigger and lose data (verified: 3 Shelly together, one cut off at 150s
# with 0 ports found instead of the real ports). Limiting concurrent heavy
# nmaps makes the total time longer with many slow devices
# together, but guarantees that each one actually finishes instead of being
# interrupted halfway.
_NMAP_SEMAPHORE = asyncio.Semaphore(2)

# protocol_scan (SNMP/NetBIOS, 2 UDP ports, host-timeout 12s) is a separate
# nmap launched IN PARALLEL with the heavy nmap inside full_scan (see below):
# sharing the same semaphore of 2, a single deep scan of
# ONE device already took both slots, queuing every other
# device chosen in the same rescan until the first one had completely finished
# - verified: with several devices selected together, some stayed in the
# queue for minutes despite having a host-timeout of 150s. A separate,
# more permissive semaphore is justified because these nmaps are light (2 ports,
# no -sV/-O/-p-) and do not compete for the same resources as the heavy nmaps.
_LIGHT_NMAP_SEMAPHORE = asyncio.Semaphore(4)


def _describe_nmap(args: list[str]) -> str:
    """Readable label for the log: what this nmap does, not the raw flags."""
    if "broadcast-upnp-info" in args:
        return "ricerca SSDP/UPnP (tutta la LAN)"
    if "broadcast-dhcp-discover" in args:
        return "DHCP DISCOVER di prova (tutta la LAN)"
    if "--top-ports" in args:
        return f"prova pilota (1000 porte) su {args[-1]}"
    if "broadcast-igmp-discovery" in args:
        return "ricerca IGMP (tutta la LAN)"
    if "ssl-cert,ssh-hostkey" in args:
        return f"certificato TLS e chiave SSH su {args[-1]}"
    if "--traceroute" in args:
        return f"percorso verso internet ({args[-1]})"
    if "-sU" in args:
        return f"SNMP/NetBIOS su {args[-1]}"
    if "-sV" in args:
        return f"scansione completa (servizi, titolo) su {args[-1]}"
    return f"scansione porte su {args[-1]}"


def _configured_host_timeout(args: list[str]) -> float | None:
    try:
        return float(args[args.index("--host-timeout") + 1].rstrip("s"))
    except (ValueError, IndexError):
        return None


# IPs whose last nmap scan hit the time limit: on a slow device
# (ESP, plugs, low-CPU devices) the scan of all ports does not finish and nmap
# discards the ones already found. Whoever uses it (pipeline) runs a targeted fallback scan.
timed_out: set[str] = set()

# Typical home and homelab ports: web, remote access, files, databases, home automation, media,
# video surveillance, printing, VPN, mail. They are scanned instead of -p- on slow devices.
FAST_PORTS = ("21,22,23,25,53,67,80,81,82,88,110,111,123,135,139,143,161,389,443,445,465,500,514,515,554,587,631,"
              "636,873,993,995,1080,1194,1400,1433,1521,1723,1883,1900,1935,2049,2323,2375,3000,3306,3389,3478,"
              "4343,4443,4567,5000,5001,5060,5222,5353,5357,5432,5555,5683,5900,5984,6053,6379,6466,6467,6668,7000,"
              "7001,7676,8000,8001,8006,8008,8009,8080,8081,8083,8086,8088,8090,8096,8123,8200,8443,8554,8581,8883,"
              "8888,8899,9000,9090,9100,9200,9999,10000,32400,34567,37777,49152,51820,55443")


# Pilot test: 1000 ports. A healthy device scans them in ~1 s (so all 65535
# in under 2 minutes); above PILOT_MAX_S the full scan would not finish in time.
PILOT_MAX_S = 3.0
PILOT_TIMEOUT_S = 15


async def pilot(ip: str) -> dict:
    """First measures whether the device can handle a scan of all ports. Returns
    {"slow": bool, "elapsed": seconds, "ports": open ports found}. nmap measures its own
    time (so waiting in the queue does not count)."""
    xml_text = await _run_nmap(["-T4", "--top-ports", "1000", "--host-timeout", f"{PILOT_TIMEOUT_S}s", ip],
                               semaphore=_LIGHT_NMAP_SEMAPHORE)
    elapsed = PILOT_TIMEOUT_S
    try:
        root = ET.fromstring(xml_text)
        fin = root.find("runstats/finished")
        if fin is not None and fin.get("elapsed"):
            elapsed = float(fin.get("elapsed"))
    except (ET.ParseError, ValueError):
        pass
    timed = ip in timed_out
    timed_out.discard(ip)  # the pilot test does not decide: pipeline.scan_host does
    hosts = _parse_hosts(xml_text)
    return {"slow": timed or elapsed > PILOT_MAX_S, "elapsed": elapsed, "ports": hosts[0]["ports"] if hosts else []}


async def fast_ports(ip: str, timeout: int = 45) -> dict | None:
    """Targeted scan (FAST_PORTS + light service detection), for devices on which
    the scan of all ports timed out. Returns the host read by nmap or None."""
    xml_text = await _run_nmap(["-T4", "-sV", "--version-light", "-p", FAST_PORTS, "--host-timeout", f"{timeout}s", ip],
                               semaphore=_LIGHT_NMAP_SEMAPHORE)
    hosts = _parse_hosts(xml_text)
    return hosts[0] if hosts else None


async def _run_nmap(args: list[str], semaphore: asyncio.Semaphore | None = None) -> str:
    sem = semaphore or _NMAP_SEMAPHORE
    label = _describe_nmap(args)
    if sem.locked():
        logger.info("In coda (nmap occupato): %s", label)
    async with sem:
        logger.info("Avviata: %s", label)
        t0 = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            "nmap", *args, "-oX", "-",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            out, _ = await proc.communicate()
        except asyncio.CancelledError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            logger.info("Annullata: %s", label)
            raise
        elapsed = time.monotonic() - t0
        # If the elapsed time is close to the configured --host-timeout, nmap
        # almost certainly truncated the scan on that host instead of
        # really finishing it: the collected data is probably partial,
        # so it deserves a different level than a normally successful scan.
        configured = _configured_host_timeout(args)
        target = args[-1] if args else ""
        if configured is not None and elapsed >= configured - 1.5:
            if is_valid_ipv4(target):
                timed_out.add(target)
            logger.warning("Host-timeout quasi raggiunto (%.1fs su %.0fs configurati), dati probabilmente incompleti: %s", elapsed, configured, label)
        else:
            timed_out.discard(target)
            logger.info("Completata (%.1fs): %s", elapsed, label)
        return out.decode(errors="replace")


def _parse_hosts(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    hosts = []
    for host_el in root.findall("host"):
        status = host_el.find("status")
        if status is None or status.get("state") != "up":
            continue
        ip = mac = vendor = None
        for addr in host_el.findall("address"):
            if addr.get("addrtype") == "ipv4":
                ip = addr.get("addr")
            elif addr.get("addrtype") == "mac":
                mac = addr.get("addr")
                vendor = addr.get("vendor") or None
        hostname_el = host_el.find("hostnames/hostname")
        hostname = hostname_el.get("name") if hostname_el is not None else None
        ports = []
        http_title = None
        tls_subject = tls_issuer = ssh_hostkey = None
        for port_el in host_el.findall("ports/port"):
            state = port_el.find("state")
            if state is None or state.get("state") != "open":
                continue
            service = port_el.find("service")
            title_el = port_el.find("script[@id='http-title']")
            has_title = title_el is not None and bool(title_el.get("output"))
            ports.append({
                "port": int(port_el.get("portid")),
                "service": service.get("name") if service is not None else None,
                "product": service.get("product") if service is not None else None,
                "version": service.get("version") if service is not None else None,
                # "probed" = nmap really queried the service, "table" = it only
                # guessed from the conventional port number (less reliable).
                "confirmed": service is not None and service.get("method") == "probed",
                # Direct proof (not a guess from the service name) that a web interface
                # really runs on this port: http-title obtained a real HTML
                # page with a title. Used by _guess_port().
                "has_http_title": has_title,
            })
            if has_title and not http_title:
                http_title = title_el.get("output")
            cert = port_el.find("script[@id='ssl-cert']")
            if cert is not None and cert.get("output") and not tls_subject:
                tls_subject, tls_issuer = parse_ssl_cert(cert.get("output"))
            key = port_el.find("script[@id='ssh-hostkey']")
            if key is not None and key.get("output") and not ssh_hostkey:
                ssh_hostkey = parse_ssh_hostkey(key.get("output"))

        if ip:
            hosts.append({
                "ip": ip, "mac": mac, **resolve_vendor_info(mac, vendor),
                "hostname": hostname, "ports": ports,
                "http_title": http_title,
                **{k: v for k, v in (("tls_subject", tls_subject), ("tls_issuer", tls_issuer),
                                     ("ssh_hostkey", ssh_hostkey)) if v},
            })
    return hosts


_TLS_PORTS = {443, 8443, 4443, 9443, 10443, 5001, 5986, 8006, 8883, 993, 995, 636, 465, 7443, 9090}


async def tls_ssh_scan(ip: str, ports: list[dict], timeout: int = 20) -> dict:
    """ssl-cert and ssh-hostkey only on the open ports that can speak TLS or SSH."""
    chosen = sorted({p["port"] for p in ports
                     if p["port"] in _TLS_PORTS or p["port"] == 22
                     or any(s in (p.get("service") or "") for s in ("https", "ssl", "ssh"))})
    if not chosen:
        return {}
    xml_text = await _run_nmap(["-Pn", "-p", ",".join(map(str, chosen[:12])), "--script", "ssl-cert,ssh-hostkey",
                                "--host-timeout", f"{timeout}s", ip], semaphore=_LIGHT_NMAP_SEMAPHORE)
    hosts = _parse_hosts(xml_text)
    if not hosts:
        return {}
    return {k: hosts[0][k] for k in ("tls_subject", "tls_issuer", "ssh_hostkey") if hosts[0].get(k)}


def parse_ssl_cert(output: str) -> tuple[str | None, str | None]:
    """Subject and issuer of the certificate (ssl-cert text)."""
    subject = issuer = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Subject:") and subject is None:
            subject = line[8:].strip()[:160] or None
        elif line.startswith("Issuer:") and issuer is None:
            issuer = line[7:].strip()[:160] or None
    return subject, issuer


def parse_ssh_hostkey(output: str) -> str | None:
    """First fingerprint of the host key (ssh-hostkey text): it stays the same even
    if the device changes IP."""
    for line in output.splitlines():
        line = line.strip()
        if line and line[0].isdigit():
            return line[:120]
    return None


# IPs to which different MACs responded in the last arp-scan (address conflict).
arp_conflicts: dict[str, list[str]] = {}


ARP_TIMEOUT_S = 120.0   # arp-scan that does not finish is closed: the cycle goes on with the last result


async def arp_scan(targets: list[str] | None = None, timeout: float = ARP_TIMEOUT_S) -> list[dict]:
    """Host discovery via ARP: layer 2 only, no ICMP/TCP fallback like nmap
    -sn. On a typical /24 it runs in 1-2 seconds instead of 3-5.
    targets None: the whole network of the interface (--localnet). Otherwise only those (addresses and CIDR blocks, see
    scan/arpplan.py), given on the standard input. A scan that does not end within `timeout` seconds is killed and TimeoutError raised.

    No logging in here: it is also called on every page refresh (behind
    a 15s cache, see get_cached_arp_by_ip in main.py), not only when
    the user launches a search - logging it anyway would have filled the buffer
    with routine events invisible to the user, burying in a few minutes
    the useful ones (real scans, errors). Whoever calls it for an
    explicit action (quick_scan) logs at that level."""
    args = ["arp-scan", f"--interface={lan_iface()}", "-x"] + (["--file=-"] if targets else ["--localnet"])
    proc = await asyncio.create_subprocess_exec(
        *args, stdin=asyncio.subprocess.PIPE if targets else None,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate("\n".join(targets).encode() if targets else None), timeout)
    except BaseException:       # timeout, or the cycle was cancelled: never leave the process running
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        raise
    hosts = parse_arp_scan(out.decode(errors="replace"))
    if not hosts and proc.returncode not in (0, None):
        raise RuntimeError("arp-scan ended with code %s" % proc.returncode)   # not an empty network: the check keeps the last result
    return hosts


async def neighbors(net: str | None = None) -> list[dict]:
    """The neighbours the system has just seen answer (`ip neigh`): they cost no packet. [] if it cannot be read."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ip", "-4", "-o", "neigh", "show", "dev", lan_iface(),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), 10)
    except Exception:
        return []
    return parse_neighbors(out.decode(errors="replace"), net)


def own_host(own_ip: str | None, arp_hosts: list[dict]) -> dict | None:
    """The computer the app runs on: ARP never lists it (nobody asks itself
    "who has this IP?"), so it is added by hand with the MAC of its network interface."""
    if not own_ip or any(h["ip"] == own_ip for h in arp_hosts):
        return None
    try:
        with open(f"/sys/class/net/{lan_iface()}/address", encoding="ascii") as fh:
            mac = fh.read().strip().upper()
    except OSError:
        return None
    if len(mac) != 17 or mac == "00:00:00:00:00:00":
        return None
    return {"ip": own_ip, "mac": mac, "vendor": None}


def parse_arp_scan(text: str) -> list[dict]:
    """arp-scan lines -> hosts. An address that replies more than once ("DUP" lines,
    typical of repeaters and routers with proxy ARP) appears only once: the
    first reply is kept."""
    hosts, seen = [], set()
    macs_by_ip: dict[str, set[str]] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and is_valid_ipv4(parts[0]):
            macs_by_ip.setdefault(parts[0], set()).add(parts[1].upper())
        if len(parts) >= 2 and is_valid_ipv4(parts[0]) and parts[0] not in seen:
            seen.add(parts[0])
            vendor = parts[2].strip() if len(parts) >= 3 and not parts[2].startswith("(Unknown") else None
            hosts.append({"ip": parts[0], "mac": parts[1].upper(), "vendor": vendor})
    # Real conflict: several MACs on the same IP, and none of those MACs also answers for
    # other IPs (that would be an ARP proxy or a repeater, not a duplicate address).
    mac_ips: dict[str, set[str]] = {}
    for ip, macs in macs_by_ip.items():
        for mac in macs:
            mac_ips.setdefault(mac, set()).add(ip)
    arp_conflicts.clear()
    for ip, macs in macs_by_ip.items():
        if len(macs) > 1 and all(len(mac_ips[m]) == 1 for m in macs):
            arp_conflicts[ip] = sorted(macs)
    return hosts


_MDNS_NAME_KEYS = (("friendly_name", 3), ("fn", 3), ("location_name", 2))
# Services whose instance name is the name the user gave to the device
# (Apple, Sonos, HomeKit): better than the generic instance of any other service.
_MDNS_USER_NAMED = {"_airplay._tcp", "_companion-link._tcp", "_hap._tcp", "_sonos._tcp", "_googlecast._tcp"}
_MDNS_SLUG_RE = re.compile(r"^[0-9a-f]{6,10}-", re.IGNORECASE)


# Model and manufacturer announced in the mDNS TXT records, per IP: {"model", "manufacturer"}.
# Keys by priority: "model" (_device-info: MacBookPro18,1, iPhone15,2), "am" (AirPlay:
# AppleTV6,2), "md" (Chromecast/HomeKit). It is filled at every mdns_scan; a device that stays silent keeps
# its last known value (the network is a home LAN: a few dozen entries).
mdns_meta: dict[str, dict] = {}
_MDNS_MODEL_KEYS = ("model", "am", "md")
_MDNS_MANUFACTURER_KEYS = ("manufacturer", "mf")


def parse_mdns_txt(txt: str) -> dict:
    """{"model", "manufacturer"} from the TXT string (`"k=v" "k2=v2"`) built by _props_to_txt (`"k=v" "k2=v2"`)."""
    pairs = dict(m.groups() for m in re.finditer(r'"([A-Za-z]+)=([^"]*)"', txt))
    out = {}
    for field, keys in (("model", _MDNS_MODEL_KEYS), ("manufacturer", _MDNS_MANUFACTURER_KEYS)):
        for key in keys:
            if pairs.get(key):
                out[field] = pairs[key][:60]
                break
    return out


_MDNS_META_TYPE = "_services._dns-sd._udp.local."
_MDNS_BUDGET = 6.0     # total seconds for the whole LAN (as with avahi-browse)
_MDNS_TYPES_WINDOW = 3.5  # after this time no new service types are searched for
_MDNS_INFO_TIMEOUT = 3000  # ms for the SRV/TXT/A request of a single instance


def _props_to_txt(props: dict) -> str:
    """zeroconf TXT record -> string `"k=v" "k2=v2"`, the format that
    parse_mdns_txt and the name choice already knew how to read."""
    parts = []
    for key, val in (props or {}).items():
        k = key.decode("utf-8", "replace") if isinstance(key, bytes) else str(key)
        if val is None:
            continue
        v = val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)
        parts.append('"%s=%s"' % (k.replace('"', ""), v.replace('"', "")))
    return " ".join(parts)


async def _mdns_browse(found: list[tuple[str, str, str, str]]) -> None:
    """DNS-SD browsing with zeroconf: the _services._dns-sd._udp meta-query discovers the
    service TYPES present on the LAN, then each type is browsed and each instance
    resolved (SRV+TXT+A). Fills `found` with (type, instance, ip, txt) as it goes:
    if the budget runs out the results already collected remain."""
    from zeroconf import IPVersion, ServiceStateChange
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

    azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    browsers: list = []
    tasks: set[asyncio.Task] = set()
    types_seen: set[str] = set()
    t_start = time.monotonic()

    async def read_instance(stype: str, name: str) -> None:
        info = AsyncServiceInfo(stype, name)
        try:
            if not await info.async_request(azc.zeroconf, _MDNS_INFO_TIMEOUT):
                return
        except Exception:
            return
        suffix = "." + stype
        instance = name[: -len(suffix)] if name.endswith(suffix) else name
        txt = _props_to_txt(info.properties)
        short = stype[: -len(".local.")] if stype.endswith(".local.") else stype
        for address in info.parsed_addresses(IPVersion.V4Only):
            found.append((short, instance, address, txt))

    def on_instance(zeroconf, service_type, name, state_change) -> None:
        if state_change is ServiceStateChange.Removed:
            return
        task = asyncio.ensure_future(read_instance(service_type, name))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def on_type(zeroconf, service_type, name, state_change) -> None:
        # for the meta-query `name` is the announced service type (e.g. _hap._tcp.local.)
        if state_change is ServiceStateChange.Removed or name in types_seen:
            return
        if time.monotonic() - t_start > _MDNS_TYPES_WINDOW:
            return
        types_seen.add(name)
        browsers.append(AsyncServiceBrowser(azc.zeroconf, name, handlers=[on_instance]))

    try:
        browsers.append(AsyncServiceBrowser(azc.zeroconf, _MDNS_META_TYPE, handlers=[on_type]))
        # Full window: exiting early on "quiet" made us lose slow devices
        # (tested on a LAN: 9 names out of 9 with the full window, 6-8 with early exit).
        await asyncio.sleep(_MDNS_BUDGET - 0.5)
        if tasks:
            await asyncio.wait(set(tasks), timeout=0.4)
    finally:
        for browser in browsers:
            try:
                await browser.async_cancel()
            except Exception:
                pass
        for task in list(tasks):
            task.cancel()
        try:
            await azc.async_close()
        except Exception:
            pass


async def mdns_scan() -> dict[str, str]:
    """Real names via mDNS (Shelly, ESPHome, Home Assistant, Chromecast,
    Apple devices...) with the zeroconf library: no avahi daemon, so it
    also runs where there is none (Home Assistant add-on). A single passive
    browse covers the whole LAN."""
    found: list[tuple[str, str, str, str]] = []
    try:
        await asyncio.wait_for(_mdns_browse(found), timeout=_MDNS_BUDGET)
    except asyncio.TimeoutError:
        pass
    except ImportError:
        logger.warning("Libreria zeroconf non installata: scansione mDNS saltata")
        return {}
    except Exception as exc:
        logger.warning("Scansione mDNS fallita: %r", exc)
        if not found:
            return {}

    best: dict[str, tuple[int, str]] = {}
    seen_meta: dict[str, dict] = {}
    for stype, name, address, txt in found:
        if not is_valid_ipv4(address):
            continue
        score, value = (2 if stype in _MDNS_USER_NAMED else 1), name
        seen_meta.setdefault(address, {}).setdefault("services", set()).add(stype)
        for field, got in parse_mdns_txt(txt).items():
            seen_meta.setdefault(address, {}).setdefault(field, got)
        for key, key_score in _MDNS_NAME_KEYS:
            m = re.search(key + r'=([^"]*)', txt)
            # A value like "5c53de3b-esphome" is an automatically generated id
            # (e.g. from a technical add-on), not a user-chosen name: it must be ignored
            # even if it appears under the "friendly_name" key.
            if m and m.group(1) and not _MDNS_SLUG_RE.match(m.group(1)):
                score, value = key_score, m.group(1)
                break
        if address not in best or score > best[address][0]:
            best[address] = (score, value)
    for ip, meta in seen_meta.items():
        if "services" in meta:
            meta["services"] = sorted(meta["services"])
        mdns_meta.setdefault(ip, {}).update(meta)
    try:   # the names seen are remembered per MAC (a sleeping phone does not lose them)
        from . import mdns_listener
        mdns_listener.remember_scan(found)
    except Exception:
        logger.exception("Memoria mDNS: salvataggio dalla scansione fallito")
    return {ip: truncate_name(v[1]) for ip, v in best.items()}


def _build_ptr_query(ip: str) -> bytes:
    """DNS packet: a PTR question for d.c.b.a.in-addr.arpa (class IN, QU/
    unicast-response bit set as in direct 'legacy' mDNS queries)."""
    qname = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    labels = b"".join(bytes([len(p)]) + p.encode("ascii") for p in qname.split("."))
    return header + labels + b"\x00" + struct.pack(">HH", 12, 0x8001)


def _read_dns_name(data: bytes, pos: int) -> tuple[str, int]:
    """DNS name (with compression pointers) at `pos`: (name, position after)."""
    labels, end, jumped, hops = [], pos, False, 0
    while True:
        if pos >= len(data) or hops > 20:
            raise ValueError("nome DNS non valido")
        length = data[pos]
        if length == 0:
            pos += 1
            break
        if length & 0xC0 == 0xC0:
            ptr = ((length & 0x3F) << 8) | data[pos + 1]
            if not jumped:
                end = pos + 2
            pos, jumped, hops = ptr, True, hops + 1
            continue
        labels.append(data[pos + 1: pos + 1 + length].decode("utf-8", "replace"))
        pos += 1 + length
    return ".".join(labels), (end if jumped else pos)


def _parse_ptr_answer(data: bytes) -> str | None:
    """First PTR record in the answer (or additional) section of a DNS response."""
    if len(data) < 12:
        return None
    _, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    pos = 12
    try:
        for _ in range(qd):
            _, pos = _read_dns_name(data, pos)
            pos += 4
        for _ in range(an + ns + ar):
            _, pos = _read_dns_name(data, pos)
            rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", data[pos: pos + 10])
            pos += 10
            if rtype == 12:
                name, _ = _read_dns_name(data, pos)
                return name
            pos += rdlen
    except (ValueError, struct.error):
        return None
    return None


class _PtrProtocol(asyncio.DatagramProtocol):
    def __init__(self, future: asyncio.Future) -> None:
        self.future = future

    def datagram_received(self, data, addr) -> None:
        if not self.future.done():
            self.future.set_result(data)


async def resolve_mdns_name(ip: str) -> str | None:
    """Active, direct mDNS query on a single address ("who has this IP?"),
    unlike mdns_scan() which is passive and only listens to whoever announces
    Bonjour/DNS-SD services. An Android/iOS phone or a Windows PC often
    publishes only its own .local hostname without announcing any service:
    the passive scan misses them entirely, this one finds them. Verified that
    this is exactly how Advanced IP Scanner finds names like "MSI", "Android",
    "iPhone-di-Caio" that we were completely missing before.

    Unicast PTR query sent to ip:5353 (hand-built packet, no
    daemon needed); the device replies to the source address."""
    if not is_valid_ipv4(ip):
        return None
    loop = asyncio.get_running_loop()
    future: asyncio.Future = loop.create_future()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _PtrProtocol(future), remote_addr=(ip, 5353),
        )
    except OSError:
        return None
    try:
        transport.sendto(_build_ptr_query(ip))
        data = await asyncio.wait_for(future, timeout=1.5)
    except (asyncio.TimeoutError, OSError):
        return None
    finally:
        transport.close()
    name = _parse_ptr_answer(data)
    if not name:
        return None
    name = name.rstrip(".")
    if name.endswith(".local"):
        name = name[:-6]
    return truncate_name(name) or None


async def resolve_names(ips: list[str], passive_names: dict[str, str] | None = None) -> dict[str, str]:
    """mDNS names for a list of addresses: starts from the passive scan (a
    single call for the whole network, better names for devices that publish them as
    friendly_name/location_name) and completes with a targeted active query only
    on the addresses left without a name - in parallel, they cost as much as the
    slowest of the individual timeouts, not the sum."""
    names = dict(passive_names) if passive_names is not None else await mdns_scan()
    missing = [ip for ip in ips if ip not in names]
    if missing:
        resolved = await asyncio.gather(*(resolve_mdns_name(ip) for ip in missing))
        for ip, name in zip(missing, resolved):
            if name:
                names[ip] = name
    return names


_UPNP_LOCATION_RE = re.compile(r"Location:\s*https?://([\d.]+)(?::\d+)?/")
_UPNP_FIELD_RE = re.compile(r"^\s*(Name|Manufacturer|Model Name|Server)\s*:\s*(.+?)\s*$")
_UPNP_FIELD_MAP = {"Name": "name", "Manufacturer": "manufacturer", "Model Name": "model", "Server": "server"}


def _parse_upnp_output(output: str) -> dict[str, dict]:
    """The aggregated text of broadcast-upnp-info lists one block per device that
    replied, but under the multicast address (239.255.255.250) and not under the
    device's real IP: the only way to know who replied is the IP
    inside the URL of the Location line, present in every block."""
    devices: dict[str, dict] = {}
    current_ip = None
    for line in output.splitlines():
        loc_match = _UPNP_LOCATION_RE.search(line)
        if loc_match:
            current_ip = loc_match.group(1)
            devices.setdefault(current_ip, {})
            continue
        if current_ip is None:
            continue
        field_match = _UPNP_FIELD_RE.match(line)
        if field_match:
            devices[current_ip].setdefault(_UPNP_FIELD_MAP[field_match.group(1)], field_match.group(2))
    return devices


async def ssdp_scan(timeout: int = 6) -> dict[str, dict]:
    """SSDP/UPnP discovery (IETF/UPnP Forum standard, M-SEARCH multicast request):
    TVs, NAS, media servers and routers with DLNA features often reply with real name,
    manufacturer and model - information that neither ARP nor mDNS sees, because
    they are two different protocols covering different families of devices.

    It is a "prerule" script (nmap calls it broadcast-upnp-info): it runs only once
    for the whole LAN before processing any target, so a dummy
    target (127.0.0.1, never actually scanned) is enough just to get
    nmap started - verified that the script activates anyway."""
    xml_text = await _run_nmap([
        "-sn", "--script", "broadcast-upnp-info", "-e", lan_iface(),
        "--host-timeout", f"{timeout}s", "127.0.0.1",
    ], semaphore=_LIGHT_NMAP_SEMAPHORE)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}
    script_el = root.find("prescript/script[@id='broadcast-upnp-info']")
    if script_el is None or not script_el.get("output"):
        return {}
    return _parse_upnp_output(script_el.get("output"))


def parse_igmp(output: str) -> dict[str, list[str]]:
    """broadcast-igmp-discovery text -> {ip: multicast groups}."""
    out: dict[str, list[str]] = {}
    current = None
    for raw in output.splitlines():
        line = raw.strip()
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+)$", line)
        if m:
            current = m.group(1)
            out.setdefault(current, [])
            continue
        if current and line.startswith("Group:"):
            out[current].append(line[6:].strip())
        elif current and re.match(r"^\d+\.\d+\.\d+\.\d+\s", line) and "Group" not in line:
            pass
    return {ip: g for ip, g in out.items() if g}


async def igmp_scan(timeout: int = 7) -> dict[str, list[str]]:
    """General IGMP query: who is subscribed to multicast groups (TVs, Chromecast,
    Sonos, IPTV). Optional and off by default: on networks with IGMP snooping or
    provider IPTV a query from a foreign device can interfere."""
    xml_text = await _run_nmap([
        "-sn", "--script", "broadcast-igmp-discovery", "-e", lan_iface(),
        "--script-args", f"broadcast-igmp-discovery.timeout={timeout}s",
        "--host-timeout", f"{timeout + 4}s", "127.0.0.1",
    ], semaphore=_LIGHT_NMAP_SEMAPHORE)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}
    script_el = root.find("prescript/script[@id='broadcast-igmp-discovery']")
    if script_el is None or not script_el.get("output"):
        return {}
    return parse_igmp(script_el.get("output"))


def parse_dhcp_offers(output: str) -> list[dict]:
    """broadcast-dhcp-discover text -> one entry for each server that replied
    (DHCPOFFER): server, offered IP, gateway, DNS, domain, lease duration."""
    keys = {"server identifier": "server", "ip offered": "offered", "router": "router",
            "domain name server": "dns", "domain name": "domain", "ip address lease time": "lease",
            "subnet mask": "netmask", "dhcp message type": "type"}
    offers: list[dict] = []
    current: dict | None = None
    for raw in output.splitlines():
        line = raw.strip()
        if line.lower().startswith("response "):
            current = {}
            offers.append(current)
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        field = keys.get(key.strip().lower())
        if field:
            value = value.strip()
            current[field] = [v.strip() for v in value.split(",") if v.strip()] if field in ("dns", "router") else value
    return [o for o in offers if o.get("server") and str(o.get("type", "DHCPOFFER")).upper() == "DHCPOFFER"]


async def dhcp_discover(timeout: int = 8) -> list[dict]:
    """Test DHCP DISCOVER (RFC 2131): DHCP servers reply with an offer
    that is NEVER accepted (no lease assigned). It reveals who hands out
    the addresses and what clients receive: gateway, DNS, domain, lease duration;
    more than one server = unwanted DHCP on the network."""
    xml_text = await _run_nmap([
        "-sn", "--script", "broadcast-dhcp-discover", "-e", lan_iface(),
        "--script-args", f"broadcast-dhcp-discover.timeout={timeout}s",
        "--host-timeout", f"{timeout + 8}s", "127.0.0.1",
    ], semaphore=_LIGHT_NMAP_SEMAPHORE)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    script_el = root.find("prescript/script[@id='broadcast-dhcp-discover']")
    if script_el is None or not script_el.get("output"):
        return []
    return parse_dhcp_offers(script_el.get("output"))


_NETBIOS_NAME_RE = re.compile(r"NetBIOS name:\s*([^,]+)")
_SNMP_DESCR_RE = re.compile(r"(?:System description|sysDescr)\s*:\s*(.+)")


def _parse_protocol_scripts(xml_text: str) -> dict:
    """Extracts the results of the NSE scripts launched per-host (nbstat, snmp-*):
    they appear under <hostscript>, a sibling of <ports> inside <host> - a
    different structure from the one already handled in _parse_hosts() for port
    scripts like http-title."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}
    host_el = root.find("host")
    if host_el is None:
        return {}
    info: dict = {}
    for script_el in host_el.findall("hostscript/script"):
        script_id = script_el.get("id")
        output = script_el.get("output") or ""
        if script_id == "nbstat":
            m = _NETBIOS_NAME_RE.search(output)
            if m:
                info["netbios_name"] = truncate_name(m.group(1).strip())
        elif script_id in ("snmp-sysdescr", "snmp-info"):
            m = _SNMP_DESCR_RE.search(output)
            value = m.group(1).strip() if m else output.strip().splitlines()[0].strip() if output.strip() else None
            if value and "snmp_descr" not in info:
                info["snmp_descr"] = value
    return info


async def protocol_scan(ip: str, timeout: int = 12) -> dict:
    """Queries additional standard protocols, very low-level and open
    (NetBIOS Name Service and SNMP, the same way printers, managed switches
    and NAS use to make themselves recognized), instead of proprietary APIs tied to
    a router brand. On many IoT/consumer devices nothing answers
    (SNMP community disabled by default, NetBIOS not implemented): in that
    case it returns an empty dict without errors, which is normal."""
    xml_text = await _run_nmap([
        "-sU", "-p", "137,161", "-T4", "--script", "nbstat,snmp-sysdescr,snmp-info",
        "--host-timeout", f"{timeout}s", ip,
    ], semaphore=_LIGHT_NMAP_SEMAPHORE)
    return _parse_protocol_scripts(xml_text)


def format_scan_info(info: dict) -> dict:
    """Turns the result of full_scan into fields ready to be shown in 'Additional info'."""
    fields = {}
    # The text nmap puts when the page has no real <title>
    # ("Site doesn't have a title (text/html; charset=...)") is not a title,
    # it is a placeholder: showing it as if it were useful information confuses
    # more than it helps. Better to omit it altogether.
    if info.get("http_title") and not is_useless_title(info["http_title"]):
        fields["http_title"] = info["http_title"]
    if info.get("http_server"):
        fields["http_server"] = info["http_server"]
    if info.get("mdns_name"):
        fields["mdns_name"] = info["mdns_name"]
    if info.get("netbios_name"):
        fields["netbios_name"] = info["netbios_name"]
    if info.get("snmp_descr"):
        fields["snmp_descr"] = info["snmp_descr"]
    if info.get("upnp_name"):
        fields["upnp_name"] = info["upnp_name"]
    if info.get("upnp_manufacturer"):
        fields["upnp_manufacturer"] = info["upnp_manufacturer"]
    if info.get("upnp_model"):
        fields["upnp_model"] = info["upnp_model"]
    if info.get("mdns_model"):
        fields["mdns_model"] = info["mdns_model"]
    if info.get("mdns_manufacturer"):
        fields["mdns_manufacturer"] = info["mdns_manufacturer"]
    for key in ("onvif_name", "onvif_hardware", "onvif_manufacturer", "wsd_types", "rtsp_server",
                "tls_subject", "tls_issuer", "ssh_hostkey", "api_source", "api_vendor", "api_model", "api_name",
                "api_fw", "mdns_services", "igmp_groups"):
        if info.get(key):
            fields[key] = info[key]
    if info.get("battery") in ("yes", "no"):
        fields["battery"] = info["battery"]
    if info.get("full_ports_at"):
        fields["full_ports_at"] = info["full_ports_at"]
    if info.get("services_at"):
        fields["services_at"] = info["services_at"]
    if info.get("slow_scan"):
        fields["slow_scan"] = True  # slow device: the next scans use the targeted ports

    ports = []
    for p in info.get("ports", []):
        label = f"{p['port']} · {p['product']}" if p.get("product") else (
            f"{p['port']} · {p['service']}" if p.get("service") else str(p["port"])
        )
        item = {
            "label": label,
            "confirmed": bool(p.get("confirmed")),
            "category": _categorize_port(p["port"], p.get("service")),
        }
        if "web_ui" in p:   # the page was really requested: does it answer with something a person can open?
            item["web_ui"] = bool(p["web_ui"])
            item["web_scheme"] = p.get("web_scheme") or "http"
        ports.append(item)
    if ports:
        fields["ports"] = ports
    return fields


WEB_SERVICE_NAMES = {"http", "https", "http-alt", "http-proxy", "https-alt", "www", "sun-answerbook"}

# Service categories for coloring the "scanned ports" in Additional info:
# grouped by function (web interface, remote access, automation/IoT,
# network infrastructure, file sharing, databases) rather than by individual
# protocol - a port OR a service name recognized in a group is enough
# to classify it (the name is for non-standard ports detected by -sV in
# full_scan, the number for deep_scan which does not do version detection). Everything
# else falls into "other".
_PORT_CATEGORY_RULES: list[tuple[str, set[int], set[str]]] = [
    ("media", {554, 1935, 7000, 8008, 8009, 1400, 8060, 32400, 8096, 8200},
     {"rtsp", "rtmp", "airplay", "airtunes", "dlna", "upnp"}),
    ("print", {631, 9100, 515}, {"ipp", "jetdirect", "printer", "pdl-datastream"}),
    ("vpn", {1194, 51820, 500, 4500, 1701, 1723}, {"openvpn", "isakmp", "ipsec", "l2tp", "pptp", "wireguard"}),
    ("mail", {25, 465, 587, 110, 995, 143, 993}, {"smtp", "smtps", "submission", "pop3", "pop3s", "imap", "imaps"}),
    ("web", {80, 443, 3000, 8080, 8081, 8443, 8888, 9000, 9090, 8123, 8006},
     {"http", "https", "http-alt", "http-proxy", "https-alt", "www", "sun-answerbook"}),
    ("remote", {22, 23, 3389, 5900, 5555, 5985, 5986},
     {"ssh", "telnet", "rdp", "ms-wbt-server", "vnc", "adb", "wsman"}),
    ("iot", {1883, 8883, 5683, 6053},
     {"mqtt", "secure-mqtt", "coap"}),
    ("infra", {53, 67, 68, 111, 123, 137, 138, 139, 161, 162, 389, 5353, 5355},
     {"domain", "dhcps", "dhcpc", "rpcbind", "ntp", "snmp", "snmptrap", "ldap", "mdns", "llmnr"}),
    ("file", {21, 445, 548, 2049},
     {"ftp", "microsoft-ds", "netbios-ssn", "afpovertcp", "nfs"}),
    ("db", {3306, 5432, 6379, 27017, 1433},
     {"mysql", "postgresql", "redis", "mongodb", "ms-sql-s"}),
]


def _categorize_port(port: int, service: str | None) -> str:
    for category, ports, services in _PORT_CATEGORY_RULES:
        if port in ports or (service and service in services):
            return category
    return "other"


EPHEMERAL_PORT_START = 49152  # IANA dynamic/private range: never a stable service

def _der_item(buf: bytes, pos: int) -> tuple[int, int, int]:
    """(tag, content start, content end) of the DER element in buf[pos:]."""
    tag, ln = buf[pos], buf[pos + 1]
    pos += 2
    if ln & 0x80:
        n = ln & 0x7F
        ln = int.from_bytes(buf[pos:pos + n], "big")
        pos += n
    return tag, pos, pos + ln


_DER_NAME_OIDS = {bytes.fromhex("550403"): "commonName", bytes.fromhex("55040a"): "organizationName",
                   bytes.fromhex("55040b"): "organizationalUnitName"}


def cert_subject(der: bytes) -> str | None:
    """Subject of an X.509 certificate (DER) in nmap's ssl-cert format:
    "commonName=pve.local/organizationName=Proxmox Virtual Environment". Only CN, O and OU."""
    try:
        _, c, _ = _der_item(der, 0)                  # Certificate
        _, c, _ = _der_item(der, c)                  # TBSCertificate
        tag, s, e = _der_item(der, c)
        if tag == 0xA0:                              # version [0] optional
            c = e
        for _ in range(4):                           # serial, signature, issuer, validity
            _, _, c = _der_item(der, c)
        _, c, end = _der_item(der, c)                # subject (sequence of RDNs)
        parts = []
        while c < end:
            _, rs, re_ = _der_item(der, c)           # RDN (set)
            _, as_, _ = _der_item(der, rs)           # AttributeTypeAndValue
            _, os_, oe = _der_item(der, as_)         # OID
            key = _DER_NAME_OIDS.get(der[os_:oe])
            _, vs, ve = _der_item(der, oe)
            if key:
                parts.append(f"{key}={der[vs:ve].decode('utf-8', 'ignore')}")
            c = re_
        return "/".join(parts)[:160] or None
    except (IndexError, ValueError):
        return None


async def _https_get(ip: str, port: int, timeout: float) -> tuple[bytes, str | None] | None:
    """GET over TLS without verification (it is a home device with its own certificate): response
    and certificate subject."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port, ssl=ctx), timeout=timeout)
        subject = None
        sslobj = writer.get_extra_info("ssl_object")
        if sslobj:
            der = sslobj.getpeercert(binary_form=True)
            subject = cert_subject(der) if der else None
        writer.write(f"GET / HTTP/1.0\r\nHost: {ip}\r\n\r\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(65536), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return data, subject
    except Exception:
        return None


async def _confirm_http_port(ip: str, port: int, timeout: float = 1.5) -> dict | None:
    """Direct, minimal proof (a single GET) that an HTTP server really
    answers on that port, instead of guessing from the service name or the
    port number. Used in deep_scan/probe_and_classify, which do not run
    -sV/--script (too slow there, see deep_scan): without this check, on
    a host with many open ports but none recognized by name (e.g. mqtt,
    llmnr, non-standard internal services) the old heuristic "first port not
    obviously non-web" still ended up guessing wrong (verified: on a
    Home Assistant VM with 14 open ports, the real 8123 lost against lower
    ports like 1884, never recognized but not excludable a priori
    without an endless list of exceptions).

    Returns how many response bytes arrived (cap 64KB, no need to
    download everything) instead of a simple yes/no: if several ports of the same
    host all turn out to be real HTTP (rare but it happened: a main app +
    a lighter internal console), there must be a way to choose which one to
    propose. None if the port does not speak HTTP."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        writer.write(f"GET / HTTP/1.0\r\nHost: {ip}\r\n\r\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(65536), timeout=timeout)
        # Many small servers send the headers and the page in separate packets: keep reading (briefly) until the
        # connection closes, otherwise a real page looks empty.
        while data.startswith(b"HTTP/") and len(data) < 65536:
            try:
                chunk = await asyncio.wait_for(reader.read(65536 - len(data)), timeout=0.4)
            except asyncio.TimeoutError:
                break
            if not chunk:
                break
            data += chunk
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        tls_subject = None
        used_tls = False
        # A TLS port answers plain text badly (no HTTP, or a 4xx/5xx error): we
        # retry over TLS, which also provides page, title and certificate.
        head0 = data.partition(b"\r\n\r\n")[0].lower()
        plain_ok = data.startswith(b"HTTP/") and (data[9:10] == b"2" or (data[9:10] == b"3" and b"location: https:" not in head0))
        if not plain_ok:
            tls = await _https_get(ip, port, max(timeout, 4.0))
            if tls and tls[0].startswith(b"HTTP/"):
                data, tls_subject = tls
                used_tls = True
            elif not data.startswith(b"HTTP/"):
                return None
        # The response is already here: besides the size we read, almost
        # for free, the Server header and the page title. They say what
        # is really running on that port (e.g. "pve-api-daemon" = Proxmox) much
        # better than the MAC prefix of the network card alone.
        head, _, body = data.partition(b"\r\n\r\n")
        server = re.search(rb"\r\nServer:[ \t]*([^\r\n]+)", head, re.IGNORECASE)
        title = re.search(rb"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        status_line = re.match(rb"HTTP/[0-9.]+ (\d{3})", data)
        status = int(status_line.group(1)) if status_line else None
        page_title = " ".join(title.group(1).decode("utf-8", "ignore").split())[:120] if title else None
        return {
            "tls_subject": tls_subject,
            "size": len(data),
            "server": server.group(1).decode("latin-1").strip()[:120] if server else None,
            "title": page_title,
            "status": status,
            "scheme": "https" if used_tls else "http",
            "usable": is_web_ui(status, page_title, len(body)),
        }
    except Exception:
        return None


def is_web_ui(status: int | None, title: str | None, body_len: int) -> bool:
    """True if what answers on `/` is a page a person can open: a normal page (2xx/3xx with a title or some content),
    or a login that asks for credentials (401). A 403 is a refusal, not a login: the page is not for people.
    A 404/400/5xx, an empty answer or a few bytes of API output (the REST service of a TV, the control port of a streaming stick, the UPnP
    port of a speaker that answers 403) is not a web interface, even if a web server is running."""
    if status is None:
        return False
    if status == 401:
        return True
    if 300 <= status < 400:
        return True
    if 200 <= status < 300:
        return bool(title and not is_useless_title(title)) or body_len >= 60
    return False


async def _confirm_http_ports(ip: str, ports: list[dict]) -> None:
    """Marks in place (key 'http_body_size') every stable port on which
    an HTTP server really answers. All ports in parallel: the cost is
    that of the slowest single check (max ~1.5s), not the sum."""
    # Also the ports on which nmap already read a title: the GET is needed to read
    # the Server header, which nmap does not give us.
    stable_ports = [p for p in ports if p["port"] < EPHEMERAL_PORT_START]
    if not stable_ports:
        return
    results = await asyncio.gather(*(_confirm_http_port(ip, p["port"]) for p in stable_ports))
    for p, found in zip(stable_ports, results):
        p["http_body_size"] = found["size"] if found else None
        p["web_ui"] = bool(found and found["usable"])
        p["web_scheme"] = found["scheme"] if found else "http"
        if found:
            p["http_server"] = found["server"]
            p["http_page_title"] = found["title"]
            if found.get("tls_subject"):
                p["tls_subject"] = found["tls_subject"]


def _guess_port(ports: list[dict]) -> int:
    """Picks the most likely port for the device's web interface.

    Not all services run on 80 (e.g. Home Assistant on 8123): the choice
    is based on evidence, in order: a port that really answered over
    HTTP, one whose service is recognized as web, 80 if open; without
    evidence it stays 80. The user can still correct it in the confirmation pop-up.

    Ephemeral ports (>= 49152, IANA dynamic range) are excluded a priori: they
    are never a stable service, just a port open by chance at the instant
    of the scan (typical of phones). Using them as the "reference port" gave a
    link that stops working on the next round - verified on an iPhone
    that was assigned 49152 only because it was the only open port found.
    """
    stable_ports = [p for p in ports if p["port"] < EPHEMERAL_PORT_START]

    # Strongest proof of all: nmap really obtained an HTML page with a
    # title from that port, not just a guess from the service name.
    # It solves the case of a Home Assistant VM where 80 was open (for
    # whatever other reason) but serving nothing real, while the real
    # interface was on 8123 - the "always prefer 80" rule below
    # would pick it first anyway, by convention, discarding the right one.
    # http_body_size comes from _confirm_http_ports: a direct GET, not
    # a guess. Among several ports confirmed as real HTTP (rare: a
    # device with two real web interfaces, e.g. a main app + an internal
    # console) the one with more content wins: a full frontend
    # is almost always more "substantial" than an internal service page -
    # verified on Home Assistant (frontend 8123: 8.9KB, Supervisor Observer
    # 4357: 1.1KB) and on a host with InfluxDB (8086: 19 bytes, the real app on
    # 3000: 63KB). It is not a guarantee, just a reasonable convention;
    # it can still be corrected by hand.
    confirmed = [p for p in stable_ports if p.get("has_http_title") or p.get("http_body_size")]
    if confirmed:
        # If 80 or 443 are among the confirmed ports, they win anyway
        # before looking at the response size: they are such a widespread
        # convention that the user expects to find the main interface there,
        # even when a secondary service on the
        # same machine answers with a "heavier" page (verified:
        # a router with MiniDLNA on 8200 - larger response - was winning
        # over the real administration interface, which is on 80).
        for p in confirmed:
            if p["port"] in (80, 443):
                return p["port"]
        return max(confirmed, key=lambda p: float("inf") if p.get("has_http_title") else p["http_body_size"])["port"]
    for p in stable_ports:
        if p["service"] in WEB_SERVICE_NAMES:
            return p["port"]
    if any(p["port"] == 80 for p in stable_ports):
        return 80

    # No proof that a port is web (neither an HTTP response nor a recognized
    # service): we do not invent one. A phone or a printer without a web
    # interface has no "right port": 80 stays by convention,
    # correctable by hand. Interfaces on non-standard ports are found with the
    # HTTP confirmation (_confirm_http_ports), not by guessing from the number.
    return 80


def web_identity(ports: list[dict]) -> dict:
    """Server and title read from the web port chosen as the default (if the confirmation
    GET found them): they are the best proof of what the device is."""
    chosen = _guess_port(ports)
    for p in ports:
        if p["port"] == chosen and p.get("http_body_size"):
            return {"http_server": p.get("http_server"), "http_title": p.get("http_page_title"),
                    "tls_subject": p.get("tls_subject")}
    return {}


def is_valid_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
        return True
    except ValueError:
        return False
