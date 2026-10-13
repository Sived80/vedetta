"""scan_common: moved out of scanner.py (see tools/split_module.py)."""
import ipaddress
from urllib.parse import urlsplit


# IPs whose last nmap scan hit the time limit: on a slow device
# (ESP, plugs, low-CPU devices) the scan of all ports does not finish and nmap
# discards the ones already found. Whoever uses it (pipeline) runs a targeted fallback scan.
timed_out: set[str] = set()


# Where a printer prints whatever arrives: HP JetDirect (9100-9107) and LPD (515). Nothing is ever sent to these ports (nmap itself leaves 9100-9107 out of its version detection for the same reason): the
# probes of the search would come out of the printer on paper ("GET / HTTP/1.0 Host: ...").
PRINT_PORTS = frozenset(range(9100, 9108)) | {515}
_PRINT_SERVICES = ("jetdirect", "printer", "pdl-datastream", "lpd")


# Industrial control ports: S7 (102), Modbus (502), Niagara Fox (1911), IEC 60870-5-104 (2404), DNP3 (20000), EtherNet/IP (44818), BACnet/IP (47808). They speak a control
# protocol: data they do not expect may be read as a command. Rule: never risk commanding a device. A plain connect to see the port open is fine; nothing is written, and no
# service detection runs on them (nmap leaves out only 9100-9107 by itself; --exclude-ports is its documented way to leave others out, nmap 6.49 and later).
INDUSTRIAL_PORTS = frozenset({102, 502, 1911, 2404, 20000, 44818, 47808})
_WEB_WORDS = ("http", "ipp", "upnp", "www", "web")         # the names nmap gives to what can be a web server (https, https-alt, http-proxy, ipp...)
_UNNAMED = ("", "unknown", "tcpwrapped")                    # nmap did not name it: it can still be a web interface (8123, 3000...)
# Services that read text lines as commands, or are plainly not a web server (a shell, mail, a database, a broker, a file or remote-desktop service...): no request goes to them even when nmap only GUESSED
# the name from the port number (the deep search does not run -sV, so every name there is such a guess: 8123 is «polipo», 1880 «vsat-control», 8006 «wpl-analytics», and those are web interfaces).
_TEXT_SERVICES = ("ssh", "telnet", "ftp", "smtp", "pop3", "imap", "mqtt", "ajp", "mysql", "postgres", "redis", "mongo", "memcache", "microsoft-ds", "netbios", "domain", "ldap", "snmp",
                  "ms-wbt-server", "vnc", "sip", "rtsp", "nfs", "sunrpc", "rpcbind", "x11")
NO_TALK_PORTS = PRINT_PORTS | INDUSTRIAL_PORTS
# Besides those, the ports of the other control protocols nmap has scripts for: Red Lion 789, CODESYS 1200 and 2455, PCWorx 1962, OPC UA 4840, HART-IP 5094, MELSEC 5006 and 5007, OMRON FINS 9600,
# GE SRTP 18245, ProConOS 20547, PROFINET 34962-34964 (the registered numbers of each protocol; a list can only grow). Nothing is sent to them (no web request, no service detection) and they are still seen
# open with a plain connect; they do NOT make a card «don't touch» by themselves (a port number can be used by something else, and that would take recognition away without the user's choice).
CONTROL_PORTS_EXTRA = frozenset({789, 1200, 1962, 2455, 4840, 5006, 5007, 5094, 9600, 18245, 20547, 34962, 34963, 34964})
NO_REQUEST_PORTS = NO_TALK_PORTS | CONTROL_PORTS_EXTRA
_NO_TALK_SERVICES = _PRINT_SERVICES + ("modbus", "iso-tsap", "s7comm", "dnp3", "iec-104", "iec104", "enip", "ethernet-ip", "bacnet")


def is_no_talk_port(entry: dict) -> bool:
    """A port where data that is not expected could be taken as a command (printing and industrial control): by its number or by the service name read on it."""
    number = entry["port"] if entry.get("port") is not None else port_number(entry)   # an nmap entry has the number, a saved one has it in the label
    service = (entry.get("service") or entry.get("label") or "").lower()
    return number in NO_TALK_PORTS or any(name in service for name in _NO_TALK_SERVICES)


def can_be_web(entry: dict) -> bool:
    """May a request for a web page be sent to this open port? Only if it is not a no-talk port and nmap named it as web-like or did not name it at all. A port that nmap VERIFIED as ssh, mqtt, telnet,
    ajp... is no interface, so nothing is lost by leaving it alone; and a control protocol may read text as a command (rule: never risk commanding a device). A name that nmap only guessed from the port
    number (method «table») is not believed, unless it is one of the services that read text as commands: otherwise Home Assistant on 8123 («polipo») or Proxmox on 8006 would never get its link."""
    number = entry["port"] if entry.get("port") is not None else port_number(entry)
    if is_no_talk_port(entry) or number in CONTROL_PORTS_EXTRA:
        return False
    service = (entry.get("service") or "").lower()
    if service in _UNNAMED or any(word in service for word in _WEB_WORDS):
        return True
    if entry.get("confirmed"):
        return False              # nmap really queried the service and it is not a web one: believed
    return not any(word in service for word in _TEXT_SERVICES)      # a name guessed from the port number: only the services that read text as commands are left alone


def version_exclusion() -> list[str]:
    """The nmap arguments that keep service detection (-sV) away from the no-talk ports."""
    return ["--exclude-ports", ",".join(str(p) for p in sorted(NO_REQUEST_PORTS))]


def valid_port(value) -> int | None:
    """A TCP port that comes from outside (a request, a setting): a number or a string of digits from 1 to 65535 that is not a no-talk port; None otherwise. A port where data is taken as a command or
    printed is never a place the app connects to, even when somebody types it."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    text = str(value).strip()
    if not text.isdigit():
        return None
    port = int(text)
    return port if 1 <= port <= 65535 and port not in NO_TALK_PORTS else None


def safe_location(url: str | None, responder_ip: str) -> bool:
    """May this URL, written by a device in its answer (SSDP LOCATION), be fetched? Only if it points at the address that answered, with the http or https scheme, no user-info and a port that is not
    a no-talk port. An address a device names is never a place to send data to by itself (a printer's raw port, a controller, another host)."""
    try:
        parts = urlsplit(url or "")
        port = parts.port or {"http": 80, "https": 443}.get(parts.scheme)
    except ValueError:
        return False
    return (parts.scheme in ("http", "https") and parts.username is None and parts.hostname == responder_ip and port is not None
            and 1 <= port <= 65535 and port not in NO_TALK_PORTS)


def is_print_port(entry: dict) -> bool:
    """A port where a printer prints whatever it is sent: by its number, or by the service name that nmap read on it (a printer can listen elsewhere)."""
    service = (entry.get("service") or "").lower()
    return entry["port"] in PRINT_PORTS or any(name in service for name in _PRINT_SERVICES)


def port_number(entry: dict) -> int | None:
    """The port number of a saved port entry (its label is "80 · http" or just "18555"); None if the label does not start with a number."""
    head = str(entry.get("label", "")).split(" ")[0]
    return int(head) if head.isdigit() else None


def is_valid_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
        return True
    except ValueError:
        return False
