"""scan_nmap: moved out of scanner.py (see tools/split_module.py)."""
import xml.etree.ElementTree as ET
import asyncio
from .scan_common import NO_REQUEST_PORTS, is_no_talk_port, is_valid_ipv4, timed_out, version_exclusion
from ..applog import logger
from .scan_cert import parse_ssh_hostkey, parse_ssl_cert
from ..recognition.vendor_lookup import resolve_vendor_info
import time
import contextlib


# The container runs on a shared, limited CPU: scanning -p- -sV -O on
# several weak IoT devices in true parallel makes them contend for the same CPU,
# slowing each one down until even the safety timeout (150s) can
# trigger and lose data (verified: 3 Shelly together, one cut off at 150s
# with 0 ports found instead of the real ports). Limiting concurrent heavy
# nmaps makes the total time longer with many slow devices
# together, but guarantees that each one actually finishes instead of being
# interrupted halfway.
_HEAVY_SLOTS = 2
_NMAP_SEMAPHORE = asyncio.Semaphore(_HEAVY_SLOTS)


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

# The pilot is judged on nmap's own elapsed time, which grows when other nmaps share the CPU: measured on real exports, a healthy device took
# 0.5-3 s alone but 6-16 s with many scans running, and was wrongly sent to the targeted scan (losing its high ports). So the pilot runs alone:
# one at a time, with the heavy slots taken, waiting for the heavy scans already running instead of interrupting them.
_PILOT_LOCK = asyncio.Lock()


@contextlib.asynccontextmanager
async def _alone():
    """No other pilot and no heavy nmap while the body runs; every permit is given back, also on cancellation."""
    async with _PILOT_LOCK, contextlib.AsyncExitStack() as slots:
        for _ in range(_HEAVY_SLOTS):
            await _NMAP_SEMAPHORE.acquire()
            slots.callback(_NMAP_SEMAPHORE.release)
        yield


async def pilot(ip: str) -> dict:
    """First measures whether the device can handle a scan of all ports. Returns
    {"slow": bool, "elapsed": seconds, "ports": open ports found}. nmap measures its own
    time (so waiting in the queue does not count), and the pilot waits until it can run alone."""
    async with _alone():
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
    xml_text = await _run_nmap(["-T4", "-sV", "--version-light", *version_exclusion(), "-p", FAST_PORTS, "--host-timeout", f"{timeout}s", ip],
                               semaphore=_LIGHT_NMAP_SEMAPHORE)
    hosts = _parse_hosts(xml_text)
    if not hosts:
        return None
    hosts[0]["ports"] = with_no_talk_ports(hosts[0]["ports"], await no_talk_open_ports(ip))
    return hosts[0]


async def no_talk_open_ports(ip: str) -> list[dict]:
    """The no-talk ports that are open: a plain TCP connect, no data sent, no service detection (the version scans leave them out, see scan_common)."""
    xml_text = await _run_nmap(["-T3", "-sT", "-Pn", "-p", ",".join(str(p) for p in sorted(NO_REQUEST_PORTS)), "--host-timeout", "10s", ip], semaphore=_LIGHT_NMAP_SEMAPHORE)
    hosts = _parse_hosts(xml_text)
    return hosts[0]["ports"] if hosts else []


def with_no_talk_ports(ports: list[dict], found: list[dict]) -> list[dict]:
    """The ports of a version scan plus the no-talk ports seen open by the plain connect (each port once)."""
    known = {p["port"] for p in ports}
    return ports + [p for p in found if p["port"] not in known]


NMAP_GRACE_S = 30      # how long past its own --host-timeout a nmap may still take before it is killed (it also has to start and write the answer)
NMAP_MAX_S = 300       # the longest a nmap WITHOUT a host timeout (a broadcast script, a traceroute) may take


async def _stop(proc) -> None:
    """Kill the process and wait for it, whatever the way out (a cancellation, an error, a hang): no process is left behind and no slot is held."""
    with contextlib.suppress(ProcessLookupError):
        proc.kill()
    with contextlib.suppress(Exception):
        await asyncio.wait_for(proc.wait(), 5)


async def _communicate_limited(proc, args: list[str]) -> bytes | None:
    """The output of the process, or None when it did not come back in time (the process is stopped). The limit is the host timeout of the command plus a grace, or a fixed maximum."""
    configured = _configured_host_timeout(args)
    limit = configured + NMAP_GRACE_S if configured is not None else NMAP_MAX_S
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), limit)
        return out
    except asyncio.TimeoutError:
        await _stop(proc)
        return None
    except BaseException:
        await _stop(proc)
        raise


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
            out = await _communicate_limited(proc, args)
        except asyncio.CancelledError:
            logger.info("Annullata: %s", label)
            raise
        if out is None:
            return _hung(args, label, time.monotonic() - t0)
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


def _hung(args: list[str], label: str, elapsed: float) -> str:
    """A nmap that did not come back in time was stopped: the address is marked as slow (like a host timeout) and the answer is empty."""
    target = args[-1] if args else ""
    if is_valid_ipv4(target):
        timed_out.add(target)
    logger.warning("nmap fermato dopo %.0fs senza risposta: %s", elapsed, label)
    return ""


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


def _parse_hosts(xml_text: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    return [h for h in map(_host_entry, root.findall("host")) if h]


def _host_entry(host_el) -> dict | None:
    """One <host> that is up and has an IPv4 address -> the dict the rest of the app reads; None otherwise."""
    status = host_el.find("status")
    if status is None or status.get("state") != "up":
        return None
    ip, mac, vendor = _addresses(host_el)
    if not ip:
        return None
    hostname_el = host_el.find("hostnames/hostname")
    ports, http_title, tls_subject, tls_issuer, ssh_hostkey = _open_ports(host_el)
    return {
        "ip": ip, "mac": mac, **resolve_vendor_info(mac, vendor),
        "hostname": hostname_el.get("name") if hostname_el is not None else None, "ports": ports,
        "http_title": http_title,
        **{k: v for k, v in (("tls_subject", tls_subject), ("tls_issuer", tls_issuer),
                             ("ssh_hostkey", ssh_hostkey)) if v},
    }


def _addresses(host_el) -> tuple:
    """(ipv4, mac, vendor) of a <host>; what is missing is None."""
    ip = mac = vendor = None
    for addr in host_el.findall("address"):
        if addr.get("addrtype") == "ipv4":
            ip = addr.get("addr")
        elif addr.get("addrtype") == "mac":
            mac = addr.get("addr")
            vendor = addr.get("vendor") or None
    return ip, mac, vendor


def _open_ports(host_el) -> tuple:
    """(open ports, first http title, tls subject, tls issuer, ssh host key) of a <host>."""
    ports = []
    http_title = None
    tls_subject = tls_issuer = ssh_hostkey = None
    for port_el in host_el.findall("ports/port"):
        state = port_el.find("state")
        if state is None or state.get("state") != "open":
            continue
        title = _script_output(port_el, "http-title")
        ports.append(_port_entry(port_el, bool(title)))
        if title and not http_title:
            http_title = title
        cert = _script_output(port_el, "ssl-cert")
        if cert and not tls_subject:
            tls_subject, tls_issuer = parse_ssl_cert(cert)
        key = _script_output(port_el, "ssh-hostkey")
        if key and not ssh_hostkey:
            ssh_hostkey = parse_ssh_hostkey(key)
    return ports, http_title, tls_subject, tls_issuer, ssh_hostkey


def _script_output(port_el, script_id: str) -> str | None:
    """The output of a script that ran on a port; None when there is no such script or it printed nothing."""
    el = port_el.find(f"script[@id='{script_id}']")
    return el.get("output") if el is not None and el.get("output") else None


def _port_entry(port_el, has_title: bool) -> dict:
    service = port_el.find("service")
    return {
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
    }


_TLS_PORTS = {443, 8443, 4443, 9443, 10443, 5001, 5986, 8006, 8883, 993, 995, 636, 465, 7443, 9090}


async def tls_ssh_scan(ip: str, ports: list[dict], timeout: int = 20) -> dict:
    """ssl-cert and ssh-hostkey only on the open ports that can speak TLS or SSH."""
    chosen = sorted({p["port"] for p in ports if _speaks_tls_or_ssh(p)})
    if not chosen:
        return {}
    xml_text = await _run_nmap(["-Pn", "-p", ",".join(map(str, chosen[:12])), "--script", "ssl-cert,ssh-hostkey",
                                "--host-timeout", f"{timeout}s", ip], semaphore=_LIGHT_NMAP_SEMAPHORE)
    hosts = _parse_hosts(xml_text)
    if not hosts:
        return {}
    return _tls_ssh_fields(hosts[0])


def _speaks_tls_or_ssh(p: dict) -> bool:
    """A port that can speak TLS or SSH: a well-known port, or a service name that says so."""
    if is_no_talk_port(p):
        return False            # a printer prints what it is sent, a TLS hello included
    return p["port"] in _TLS_PORTS or p["port"] == 22 or any(s in (p.get("service") or "") for s in ("https", "ssl", "ssh"))


def _tls_ssh_fields(host: dict) -> dict:
    """The certificate and host key fields of a parsed host that are not empty."""
    return {k: host[k] for k in ("tls_subject", "tls_issuer", "ssh_hostkey") if host.get(k)}
