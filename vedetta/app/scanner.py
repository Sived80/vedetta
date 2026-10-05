import asyncio
import ssl
import ipaddress
import re
import struct
import time
import xml.etree.ElementTree as ET

from .applog import logger
from .formatters import is_useless_title, truncate_name
from .iface import lan_iface
from .vendor_lookup import resolve_vendor_info

# Il container gira su una CPU condivisa e limitata: scansionare -p- -sV -O su
# piu' dispositivi IoT deboli in vero parallelo li fa contendere la stessa CPU,
# rallentando ciascuno finche' anche il timeout di sicurezza (150s) puo'
# scattare perdendo dati (verificato: 3 Shelly insieme, uno tagliato a 150s
# con 0 porte trovate invece delle porte reali). Limitare i nmap pesanti
# concorrenti rende il tempo totale piu' lungo con tanti dispositivi lenti
# insieme, ma garantisce che ognuno finisca davvero invece di essere
# interrotto a meta'.
_NMAP_SEMAPHORE = asyncio.Semaphore(2)

# protocol_scan (SNMP/NetBIOS, 2 porte UDP, host-timeout 12s) e' un nmap
# separato lanciato IN PARALLELO al nmap pesante dentro full_scan (vedi sotto):
# condividendo lo stesso semaforo da 2, una singola scansione approfondita di
# UN dispositivo occupava gia' entrambi gli slot, mettendo in coda ogni altro
# dispositivo scelto nella stessa rescan finche' il primo non finiva del tutto
# - verificato: con piu' dispositivi selezionati insieme, alcuni restavano in
# coda per minuti pur avendo un host-timeout di 150s. Un semaforo separato,
# piu' permissivo, e' giustificato perche' questi nmap sono leggeri (2 porte,
# nessun -sV/-O/-p-) e non competono per le stesse risorse dei nmap pesanti.
_LIGHT_NMAP_SEMAPHORE = asyncio.Semaphore(4)


def _describe_nmap(args: list[str]) -> str:
    """Etichetta leggibile per il log: cosa fa questo nmap, non i flag grezzi."""
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


# IP la cui ultima scansione nmap ha raggiunto il tempo massimo: su un dispositivo lento
# (ESP, prese, dispositivi con poca CPU) la scansione di tutte le porte non finisce e nmap
# scarta quelle gia' trovate. Chi la usa (pipeline) fa una scansione mirata di ripiego.
timed_out: set[str] = set()

# Porte tipiche di casa e homelab: web, accesso remoto, file, database, domotica, media,
# videosorveglianza, stampa, VPN, posta. Si scansionano al posto di -p- sui dispositivi lenti.
FAST_PORTS = ("21,22,23,25,53,67,80,81,82,88,110,111,123,135,139,143,161,389,443,445,465,500,514,515,554,587,631,"
              "636,873,993,995,1080,1194,1400,1433,1521,1723,1883,1900,1935,2049,2323,2375,3000,3306,3389,3478,"
              "4343,4443,4567,5000,5001,5060,5222,5353,5357,5432,5555,5683,5900,5984,6053,6379,6466,6467,6668,7000,"
              "7001,7676,8000,8001,8006,8008,8009,8080,8081,8083,8086,8088,8090,8096,8123,8200,8443,8554,8581,8883,"
              "8888,8899,9000,9090,9100,9200,9999,10000,32400,34567,37777,49152,51820,55443")


# Prova pilota: 1000 porte. Un dispositivo sano le scansiona in ~1 s (quindi tutte le 65535
# in meno di 2 minuti); sopra PILOT_MAX_S la scansione completa non finirebbe nei tempi.
PILOT_MAX_S = 3.0
PILOT_TIMEOUT_S = 15


async def pilot(ip: str) -> dict:
    """Misura prima se il dispositivo regge la scansione di tutte le porte. Ritorna
    {"slow": bool, "elapsed": secondi, "ports": porte aperte trovate}. nmap misura il suo
    tempo (cosi' l'attesa in coda non conta)."""
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
    timed_out.discard(ip)  # la prova pilota non decide: lo fa pipeline.scan_host
    hosts = _parse_hosts(xml_text)
    return {"slow": timed or elapsed > PILOT_MAX_S, "elapsed": elapsed, "ports": hosts[0]["ports"] if hosts else []}


async def fast_ports(ip: str, timeout: int = 45) -> dict | None:
    """Scansione mirata (FAST_PORTS + riconoscimento servizi leggero), per i dispositivi su cui
    la scansione di tutte le porte e' scaduta. Ritorna l'host letto da nmap o None."""
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
        # Se il tempo impiegato e' vicino all'--host-timeout configurato, nmap
        # ha quasi certamente troncato la scansione su quell'host invece di
        # finirla per davvero: i dati raccolti sono probabilmente parziali,
        # merita un livello diverso da una scansione riuscita normalmente.
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
                # "probed" = nmap ha davvero interrogato il servizio, "table" = ha solo
                # indovinato dal numero di porta convenzionale (meno affidabile).
                "confirmed": service is not None and service.get("method") == "probed",
                # Prova diretta (non un'ipotesi sul nome del servizio) che su questa
                # porta gira davvero un'interfaccia web: http-title ha ottenuto una
                # pagina HTML reale con un titolo. Usato da _guess_port().
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
    """ssl-cert e ssh-hostkey sulle sole porte aperte che possono parlare TLS o SSH."""
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
    """Soggetto ed emittente del certificato (testo di ssl-cert)."""
    subject = issuer = None
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Subject:") and subject is None:
            subject = line[8:].strip()[:160] or None
        elif line.startswith("Issuer:") and issuer is None:
            issuer = line[7:].strip()[:160] or None
    return subject, issuer


def parse_ssh_hostkey(output: str) -> str | None:
    """Prima impronta della chiave dell'host (testo di ssh-hostkey): resta uguale anche
    se il dispositivo cambia IP."""
    for line in output.splitlines():
        line = line.strip()
        if line and line[0].isdigit():
            return line[:120]
    return None


# IP a cui hanno risposto MAC diversi nell'ultima arp-scan (conflitto di indirizzo).
arp_conflicts: dict[str, list[str]] = {}


async def arp_scan() -> list[dict]:
    """Scoperta host via ARP: solo livello 2, niente fallback ICMP/TCP come nmap
    -sn. Su una /24 tipica gira in 1-2 secondi invece di 3-5.

    Niente log qui dentro: e' chiamata anche a ogni refresh di pagina (dietro
    una cache di 15s, vedi get_cached_arp_by_ip in main.py), non solo quando
    l'utente lancia una ricerca - loggarla comunque avrebbe riempito il buffer
    di eventi di routine invisibili all'utente, seppellendo in pochi minuti
    quelli utili (scansioni vere, errori). Chi la chiama per un'azione
    esplicita (quick_scan) logga a quel livello."""
    proc = await asyncio.create_subprocess_exec(
        "arp-scan", f"--interface={lan_iface()}", "--localnet", "-x",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    return parse_arp_scan(out.decode(errors="replace"))


def own_host(own_ip: str | None, arp_hosts: list[dict]) -> dict | None:
    """Il computer su cui gira l'app: l'ARP non lo elenca mai (nessuno chiede a se' stesso
    "chi ha questo IP?"), quindi si aggiunge a mano con il MAC della sua interfaccia di rete."""
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
    """Righe di arp-scan -> host. Un indirizzo che risponde piu' volte (righe "DUP",
    tipico di ripetitori e router con proxy ARP) compare una sola volta: si tiene la
    prima risposta."""
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
    # Conflitto vero: piu' MAC sullo stesso IP, e nessuno di quei MAC risponde anche per
    # altri IP (quello sarebbe un proxy ARP o un ripetitore, non un indirizzo duplicato).
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
# Servizi il cui nome di istanza e' il nome che l'utente ha dato al dispositivo
# (Apple, Sonos, HomeKit): meglio dell'istanza generica di un servizio qualsiasi.
_MDNS_USER_NAMED = {"_airplay._tcp", "_companion-link._tcp", "_hap._tcp", "_sonos._tcp", "_googlecast._tcp"}
_MDNS_SLUG_RE = re.compile(r"^[0-9a-f]{6,10}-", re.IGNORECASE)


# Modello e produttore annunciati nei record TXT mDNS, per IP: {"model", "manufacturer"}.
# Chiavi per priorita': "model" (_device-info: MacBookPro18,1, iPhone15,2), "am" (AirPlay:
# AppleTV6,2), "md" (Chromecast/HomeKit). Si riempie a ogni mdns_scan; chi tace conserva
# l'ultimo valore noto (la rete e' una LAN domestica: poche decine di voci).
mdns_meta: dict[str, dict] = {}
_MDNS_MODEL_KEYS = ("model", "am", "md")
_MDNS_MANUFACTURER_KEYS = ("manufacturer", "mf")


def parse_mdns_txt(txt: str) -> dict:
    """{"model", "manufacturer"} dalla stringa TXT (`"k=v" "k2=v2"`) costruita da _props_to_txt (`"k=v" "k2=v2"`)."""
    pairs = dict(m.groups() for m in re.finditer(r'"([A-Za-z]+)=([^"]*)"', txt))
    out = {}
    for field, keys in (("model", _MDNS_MODEL_KEYS), ("manufacturer", _MDNS_MANUFACTURER_KEYS)):
        for key in keys:
            if pairs.get(key):
                out[field] = pairs[key][:60]
                break
    return out


_MDNS_META_TYPE = "_services._dns-sd._udp.local."
_MDNS_BUDGET = 6.0     # secondi totali per tutta la LAN (come con avahi-browse)
_MDNS_TYPES_WINDOW = 3.5  # dopo questo tempo non si cercano piu' nuovi tipi di servizio
_MDNS_INFO_TIMEOUT = 3000  # ms per la richiesta SRV/TXT/A di una singola istanza


def _props_to_txt(props: dict) -> str:
    """Record TXT di zeroconf -> stringa `"k=v" "k2=v2"`, il formato che
    parse_mdns_txt e la scelta del nome gia' sapevano leggere."""
    parts = []
    for key, val in (props or {}).items():
        k = key.decode("utf-8", "replace") if isinstance(key, bytes) else str(key)
        if val is None:
            continue
        v = val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)
        parts.append('"%s=%s"' % (k.replace('"', ""), v.replace('"', "")))
    return " ".join(parts)


async def _mdns_browse(found: list[tuple[str, str, str, str]]) -> None:
    """Navigazione DNS-SD con zeroconf: la meta-query _services._dns-sd._udp scopre i
    TIPI di servizio presenti in LAN, poi ogni tipo viene navigato e ogni istanza
    risolta (SRV+TXT+A). Riempie `found` con (tipo, istanza, ip, txt) man mano:
    se il budget scade restano i risultati gia' raccolti."""
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
        # per la meta-query `name` e' il tipo di servizio annunciato (es. _hap._tcp.local.)
        if state_change is ServiceStateChange.Removed or name in types_seen:
            return
        if time.monotonic() - t_start > _MDNS_TYPES_WINDOW:
            return
        types_seen.add(name)
        browsers.append(AsyncServiceBrowser(azc.zeroconf, name, handlers=[on_instance]))

    try:
        browsers.append(AsyncServiceBrowser(azc.zeroconf, _MDNS_META_TYPE, handlers=[on_type]))
        # Finestra intera: uscire prima per "quiete" faceva perdere dispositivi lenti
        # (collaudato in LAN: 9 nomi su 9 con la finestra piena, 6-8 con l'uscita anticipata).
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
    """Nomi reali via mDNS (Shelly, ESPHome, Home Assistant, Chromecast,
    dispositivi Apple...) con la libreria zeroconf: niente demone avahi, quindi
    gira anche dove non c'e' (add-on di Home Assistant). Una sola navigazione
    passiva copre l'intera LAN."""
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
            # Un valore tipo "5c53de3b-esphome" e' un id generato automaticamente
            # (es. da un add-on tecnico), non un nome scelto dall'utente: va ignorato
            # anche se compare sotto la chiave "friendly_name".
            if m and m.group(1) and not _MDNS_SLUG_RE.match(m.group(1)):
                score, value = key_score, m.group(1)
                break
        if address not in best or score > best[address][0]:
            best[address] = (score, value)
    for ip, meta in seen_meta.items():
        if "services" in meta:
            meta["services"] = sorted(meta["services"])
        mdns_meta.setdefault(ip, {}).update(meta)
    try:   # i nomi visti si ricordano per MAC (il telefono che dorme non li perde)
        from . import mdns_listener
        mdns_listener.remember_scan(found)
    except Exception:
        logger.exception("Memoria mDNS: salvataggio dalla scansione fallito")
    return {ip: truncate_name(v[1]) for ip, v in best.items()}


def _build_ptr_query(ip: str) -> bytes:
    """Pacchetto DNS: una domanda PTR per d.c.b.a.in-addr.arpa (classe IN, bit
    QU/unicast-response acceso come nelle query mDNS 'legacy' dirette)."""
    qname = ".".join(reversed(ip.split("."))) + ".in-addr.arpa"
    header = struct.pack(">HHHHHH", 0, 0, 1, 0, 0, 0)
    labels = b"".join(bytes([len(p)]) + p.encode("ascii") for p in qname.split("."))
    return header + labels + b"\x00" + struct.pack(">HH", 12, 0x8001)


def _read_dns_name(data: bytes, pos: int) -> tuple[str, int]:
    """Nome DNS (con puntatori di compressione) a `pos`: (nome, posizione dopo)."""
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
    """Primo record PTR nella sezione risposte (o aggiuntiva) di una risposta DNS."""
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
    """Query mDNS attiva e diretta su un singolo indirizzo ("chi ha questo IP?"),
    a differenza di mdns_scan() che e' passiva e ascolta solo chi annuncia
    servizi Bonjour/DNS-SD. Un telefono Android/iOS o un PC Windows spesso
    pubblica solo il proprio hostname .local senza annunciare nessun servizio:
    la scansione passiva li perde del tutto, questa li trova. Verificato che
    e' proprio cosi' che Advanced IP Scanner trova nomi come "MSI", "Android",
    "iPhone-di-Caio" che prima ci mancavano completamente.

    Query PTR unicast spedita a ip:5353 (pacchetto costruito a mano, nessun
    demone necessario); il dispositivo risponde all'indirizzo di origine."""
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
    """Nomi mDNS per un elenco di indirizzi: parte dalla scansione passiva (una
    sola chiamata per tutta la rete, nomi migliori per chi li pubblica come
    friendly_name/location_name) e completa con una query attiva mirata solo
    sugli indirizzi rimasti senza nome - in parallelo, costano quanto il piu'
    lento dei singoli timeout, non la somma."""
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
    """Il testo aggregato di broadcast-upnp-info elenca un blocco per dispositivo
    risposto, ma sotto l'indirizzo multicast (239.255.255.250) e non sotto il
    vero IP del dispositivo: l'unico modo per sapere chi ha risposto e' l'IP
    dentro l'URL della riga Location, presente in ogni blocco."""
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
    """Scoperta SSDP/UPnP (standard IETF/UPnP Forum, richiesta multicast M-SEARCH):
    TV, NAS, media server e router con funzioni DLNA spesso rispondono con nome,
    produttore e modello reali - informazioni che ne' ARP ne' mDNS vedono, perche'
    sono due protocolli diversi che coprono famiglie di dispositivi diverse.

    E' uno script "prerule" (nmap lo chiama broadcast-upnp-info): gira una sola
    volta per l'intera LAN prima di processare qualunque target, quindi basta un
    target fittizio (127.0.0.1, mai realmente scansionato) solo per far partire
    nmap - verificato che lo script si attiva comunque."""
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
    """Testo di broadcast-igmp-discovery -> {ip: gruppi multicast}."""
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
    """Query IGMP generale: chi e' iscritto a gruppi multicast (TV, Chromecast,
    Sonos, IPTV). Facoltativa e spenta di default: su reti con IGMP snooping o IPTV
    del provider una query da un dispositivo estraneo puo' interferire."""
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
    """Testo di broadcast-dhcp-discover -> una voce per ogni server che ha risposto
    (DHCPOFFER): server, IP offerto, gateway, DNS, dominio, durata del lease."""
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
    """DHCP DISCOVER di prova (RFC 2131): i server DHCP rispondono con un'offerta
    che NON viene mai accettata (nessun lease assegnato). Rivela chi distribuisce
    gli indirizzi e cosa ricevono i client: gateway, DNS, dominio, durata del lease;
    piu' di un server = DHCP non voluto in rete."""
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
    """Estrae i risultati degli script NSE lanciati per-host (nbstat, snmp-*):
    compaiono sotto <hostscript>, un fratello di <ports> dentro <host> - una
    struttura diversa da quella gia' gestita in _parse_hosts() per gli script
    di porta come http-title."""
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
    """Interroga protocolli standard aggiuntivi, a bassissimo livello e aperti
    (NetBIOS Name Service e SNMP, la stessa via usata da stampanti, switch
    gestiti e NAS per farsi riconoscere), invece di API proprietarie legate a
    una marca di router. Su molti dispositivi IoT/consumer non risponde nulla
    (community SNMP disabilitata di default, NetBIOS non implementato): in tal
    caso ritorna un dict vuoto senza errori, e' normale."""
    xml_text = await _run_nmap([
        "-sU", "-p", "137,161", "-T4", "--script", "nbstat,snmp-sysdescr,snmp-info",
        "--host-timeout", f"{timeout}s", ip,
    ], semaphore=_LIGHT_NMAP_SEMAPHORE)
    return _parse_protocol_scripts(xml_text)


def format_scan_info(info: dict) -> dict:
    """Trasforma il risultato di full_scan in campi pronti da mostrare in 'Info aggiuntive'."""
    fields = {}
    # Il testo che nmap mette quando la pagina non ha un <title> reale
    # ("Site doesn't have a title (text/html; charset=...)") non e' un titolo,
    # e' un placeholder: mostrarlo come se fosse informazione utile confonde
    # piu' che aiutare. Meglio ometterlo del tutto.
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
        fields["slow_scan"] = True  # dispositivo lento: le prossime scansioni usano le porte mirate

    ports = []
    for p in info.get("ports", []):
        label = f"{p['port']} · {p['product']}" if p.get("product") else (
            f"{p['port']} · {p['service']}" if p.get("service") else str(p["port"])
        )
        ports.append({
            "label": label,
            "confirmed": bool(p.get("confirmed")),
            "category": _categorize_port(p["port"], p.get("service")),
        })
    if ports:
        fields["ports"] = ports
    return fields


WEB_SERVICE_NAMES = {"http", "https", "http-alt", "http-proxy", "https-alt", "www", "sun-answerbook"}

# Categorie di servizio per colorare le "porte scansionate" in Info aggiuntive:
# raggruppate per funzione (interfaccia web, accesso remoto, automazione/IoT,
# infrastruttura di rete, condivisione file, database) invece che per singolo
# protocollo - una porta O un nome di servizio riconosciuto in un gruppo bastano
# a classificarla (il nome serve per porte non standard rilevate da -sV in
# full_scan, il numero per deep_scan che non fa version detection). Tutto il
# resto ricade in "other".
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


EPHEMERAL_PORT_START = 49152  # range dinamico/privato IANA: mai un servizio stabile

def _der_item(buf: bytes, pos: int) -> tuple[int, int, int]:
    """(tag, inizio contenuto, fine contenuto) dell'elemento DER in buf[pos:]."""
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
    """Soggetto di un certificato X.509 (DER) nel formato di nmap ssl-cert:
    "commonName=pve.local/organizationName=Proxmox Virtual Environment". Solo CN, O e OU."""
    try:
        _, c, _ = _der_item(der, 0)                  # Certificate
        _, c, _ = _der_item(der, c)                  # TBSCertificate
        tag, s, e = _der_item(der, c)
        if tag == 0xA0:                              # version [0] opzionale
            c = e
        for _ in range(4):                           # serial, signature, issuer, validity
            _, _, c = _der_item(der, c)
        _, c, end = _der_item(der, c)                # subject (sequenza di RDN)
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
    """GET su TLS senza verifica (e' un dispositivo di casa con certificato proprio): risposta
    e soggetto del certificato."""
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


async def _confirm_http_port(ip: str, port: int, timeout: float = 1.5) -> int | None:
    """Prova diretta e minimale (una sola GET) che su quella porta risponde
    davvero un server HTTP, invece di indovinare dal nome del servizio o dal
    numero di porta. Usata in deep_scan/probe_and_classify, che non fanno
    -sV/--script (troppo lenti li', vedi deep_scan): senza questo controllo, su
    un host con molte porte aperte ma nessuna riconosciuta per nome (es. mqtt,
    llmnr, servizi interni non standard) la vecchia euristica "prima porta non
    palesemente non-web" finiva comunque per indovinare male (verificato: su una
    VM Home Assistant con 14 porte aperte, la 8123 vera perdeva contro porte
    piu' basse come 1884, mai riconosciute ma nemmeno escludibili a priori
    senza un elenco infinito di eccezioni).

    Ritorna quanti byte di risposta sono arrivati (tetto 64KB, non serve
    scaricare tutto) invece di un semplice si'/no: se piu' porte dello stesso
    host risultano tutte HTTP vere (raro ma capitato: un'app principale +
    una console interna piu' leggera), serve un modo per scegliere quale
    proporre. None se la porta non parla HTTP."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
        writer.write(f"GET / HTTP/1.0\r\nHost: {ip}\r\n\r\n".encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(65536), timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        tls_subject = None
        # Una porta TLS risponde male al testo in chiaro (niente HTTP, o un errore 4xx/5xx): si
        # riprova su TLS, da cui arrivano anche pagina, titolo e certificato.
        head0 = data.partition(b"\r\n\r\n")[0].lower()
        plain_ok = data.startswith(b"HTTP/") and (data[9:10] == b"2" or (data[9:10] == b"3" and b"location: https:" not in head0))
        if not plain_ok:
            tls = await _https_get(ip, port, max(timeout, 4.0))
            if tls and tls[0].startswith(b"HTTP/"):
                data, tls_subject = tls
            elif not data.startswith(b"HTTP/"):
                return None
        # La risposta e' gia' qui: oltre alla dimensione si leggono, quasi
        # gratis, l'intestazione Server e il titolo della pagina. Dicono cosa
        # gira davvero su quella porta (es. "pve-api-daemon" = Proxmox) molto
        # meglio del solo prefisso MAC della scheda di rete.
        head, _, body = data.partition(b"\r\n\r\n")
        server = re.search(rb"\r\nServer:[ \t]*([^\r\n]+)", head, re.IGNORECASE)
        title = re.search(rb"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
        return {
            "tls_subject": tls_subject,
            "size": len(data),
            "server": server.group(1).decode("latin-1").strip()[:120] if server else None,
            "title": " ".join(title.group(1).decode("utf-8", "ignore").split())[:120] if title else None,
        }
    except Exception:
        return None


async def _confirm_http_ports(ip: str, ports: list[dict]) -> None:
    """Marca in-place (chiave 'http_body_size') ogni porta stabile su cui
    risponde davvero un server HTTP. Tutte le porte in parallelo: il costo e'
    quello del piu' lento singolo controllo (max ~1.5s), non la somma."""
    # Anche le porte su cui nmap ha gia' letto un titolo: la GET serve a leggere
    # l'intestazione Server, che nmap non ci da'.
    stable_ports = [p for p in ports if p["port"] < EPHEMERAL_PORT_START]
    if not stable_ports:
        return
    results = await asyncio.gather(*(_confirm_http_port(ip, p["port"]) for p in stable_ports))
    for p, found in zip(stable_ports, results):
        p["http_body_size"] = found["size"] if found else None
        if found:
            p["http_server"] = found["server"]
            p["http_page_title"] = found["title"]
            if found.get("tls_subject"):
                p["tls_subject"] = found["tls_subject"]


def _guess_port(ports: list[dict]) -> int:
    """Sceglie la porta piu' probabile per l'interfaccia web del dispositivo.

    Non tutti i servizi girano sulla 80 (es. Home Assistant sulla 8123): si
    sceglie in base alle prove, in ordine: una porta che ha risposto davvero in
    HTTP, una il cui servizio e' riconosciuto come web, la 80 se aperta; senza
    prove resta la 80. L'utente puo' comunque correggerla nel pop-up di conferma.

    Le porte effimere (>= 49152, range dinamico IANA) sono escluse a priori: non
    sono mai un servizio stabile, solo una porta aperta per caso nell'istante
    dello scan (tipico di telefoni). Usarle come "porta di riferimento" dava un
    link che smette di funzionare al prossimo giro - verificato su un iPhone
    a cui era stata assegnata la 49152 solo perche' l'unica trovata aperta.
    """
    stable_ports = [p for p in ports if p["port"] < EPHEMERAL_PORT_START]

    # Prova piu' forte di tutte: nmap ha davvero ottenuto una pagina HTML con
    # titolo da quella porta, non e' solo un'ipotesi sul nome del servizio.
    # Risolve il caso di una VM Home Assistant dove la 80 era aperta (per
    # qualunque altro motivo) ma senza servire nulla di reale, mentre la vera
    # interfaccia era sulla 8123 - la regola "preferisci sempre la 80" sotto
    # la sceglieva comunque per prima, per convenzione, scartando quella giusta.
    # http_body_size viene da _confirm_http_ports: una GET diretta, non
    # un'ipotesi. Tra piu' porte confermate come HTTP vero (raro: un
    # dispositivo con due interfacce web reali, es. un'app principale + una
    # console interna) vince quella con piu' contenuto: un frontend completo
    # e' quasi sempre piu' "sostanzioso" di una pagina di servizio interna -
    # verificato su Home Assistant (frontend 8123: 8.9KB, Supervisor Observer
    # 4357: 1.1KB) e su un host con InfluxDB (8086: 19 byte, la vera app sulla
    # 3000: 63KB). Non e' una garanzia, solo una convenzione ragionevole;
    # resta comunque correggibile a mano.
    confirmed = [p for p in stable_ports if p.get("has_http_title") or p.get("http_body_size")]
    if confirmed:
        # Se la 80 o la 443 sono tra le porte confermate, vincono comunque
        # loro prima di guardare la dimensione della risposta: sono la
        # convenzione talmente diffusa che l'utente si aspetta di trovarci
        # l'interfaccia principale, anche quando un servizio secondario sulla
        # stessa macchina risponde con una pagina piu' "pesante" (verificato:
        # un router con MiniDLNA sulla 8200 - risposta piu' grande - vinceva
        # sulla vera interfaccia di amministrazione, che sta sulla 80).
        for p in confirmed:
            if p["port"] in (80, 443):
                return p["port"]
        return max(confirmed, key=lambda p: float("inf") if p.get("has_http_title") else p["http_body_size"])["port"]
    for p in stable_ports:
        if p["service"] in WEB_SERVICE_NAMES:
            return p["port"]
    if any(p["port"] == 80 for p in stable_ports):
        return 80

    # Nessuna prova che una porta sia web (ne' risposta HTTP, ne' servizio
    # riconosciuto): non se ne inventa una. Un telefono o una stampante senza
    # interfaccia web non hanno una "porta giusta": resta la 80 di convenzione,
    # correggibile a mano. Le interfacce su porte non standard si trovano con la
    # conferma HTTP (_confirm_http_ports), non indovinando dal numero.
    return 80


def web_identity(ports: list[dict]) -> dict:
    """Server e titolo letti dalla porta web scelta come predefinita (se la GET
    di conferma li ha trovati): sono la prova migliore di cosa e' il dispositivo."""
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
