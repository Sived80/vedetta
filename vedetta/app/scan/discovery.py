"""Self-declaration protocols not covered by nmap/zeroconf, in pure Python.

WS-Discovery (UDP multicast 239.255.255.250:3702, OASIS WS-Discovery 1.1, used by
ONVIF for cameras and by Windows/WSD printers): an unfiltered Probe, each
device answers with a ProbeMatch containing Types, Scopes and XAddrs. For
ONVIF the Scopes give name, hardware (model) and sometimes manufacturer:
  onvif://www.onvif.org/name/IPCAM, .../hardware/C6F0SgZ3N0PdL2, .../location/...

RTSP (TCP 554, RFC 2326/7826): an unauthenticated OPTIONS request returns
the Server header (e.g. "Hipcam RealServer/V1.0") and the supported methods.

No credentials, no access attempts: only standard requests that the
devices accept by design."""
import asyncio
import re
import socket
import uuid
import xml.etree.ElementTree as ET
from urllib.parse import unquote

from ..applog import logger
from . import scan_common
import contextlib

WSD_ADDR = ("239.255.255.250", 3702)
_PROBE = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
    'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">'
    "<e:Header><w:MessageID>uuid:{mid}</w:MessageID>"
    '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
    '<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
    "</e:Header><e:Body><d:Probe/></e:Body></e:Envelope>"
)
_ONVIF_SCOPE = re.compile(r"^onvif://www\.onvif\.org/(name|hardware|location|manufacturer|mfr|type|model)/(.+)$", re.IGNORECASE)


def parse_probe_match(data: bytes) -> dict | None:
    """Fields of a WS-Discovery ProbeMatch; None if it is not a valid ProbeMatch."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    found, texts = _scan_probe_match(root)
    if not found:
        return None
    info: dict = {"types": [t.split(":")[-1] for t in texts["Types"].split()], "xaddrs": texts["XAddrs"].split()}
    onvif = _onvif_scopes(texts["Scopes"])
    _add_onvif_fields(info, onvif)
    info["onvif"] = bool(onvif) or any("NetworkVideoTransmitter" in t for t in info["types"])
    return info


def _scan_probe_match(root) -> tuple[bool, dict[str, str]]:
    """Whether the document holds a ProbeMatch element, and the stripped text of the LAST non-empty Types, Scopes and XAddrs elements ("" if none)."""
    found = False
    texts = {"Types": "", "Scopes": "", "XAddrs": ""}
    for el in root.iter():
        name = el.tag.rsplit("}", 1)[-1]
        if name == "ProbeMatch":
            found = True
        elif name in texts and el.text:
            texts[name] = el.text.strip()
    return found, texts


def _onvif_scopes(scopes: str) -> dict[str, list[str]]:
    """The ONVIF scopes of a space-separated list, by lower-case key ("mfr" counts as "manufacturer"), values decoded in order of appearance."""
    onvif: dict[str, list[str]] = {}
    for scope in scopes.split():
        m = _ONVIF_SCOPE.match(scope)
        if m:
            key = m.group(1).lower()
            key = "manufacturer" if key == "mfr" else key
            onvif.setdefault(key, []).append(unquote(m.group(2)).replace("_", " ").strip())
    return onvif


def _add_onvif_fields(info: dict, onvif: dict[str, list[str]]) -> None:
    """Copy the first non-empty value of each known ONVIF key into `info` (name, hardware, manufacturer, model, then location)."""
    for key in ("name", "hardware", "manufacturer", "model"):
        if onvif.get(key):
            info[key] = onvif[key][0]
    if onvif.get("location"):
        info["location"] = onvif["location"][0]


class _Collector(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.found: dict[str, dict] = {}

    def datagram_received(self, data: bytes, addr) -> None:
        info = parse_probe_match(data)
        if info and addr[0] not in self.found:
            self.found[addr[0]] = info


async def _collect(factory, payload: bytes, dest: tuple[str, int], own_ip: str | None, timeout: float, label: str):
    """The only place that touches the network for the multicast protocols: sends `payload` twice (UDP) to `dest`, listens `timeout`
    seconds with the protocol made by `factory`, and returns that protocol (its `found` holds what was heard) or None if the network is not
    available. Tests replace this function with one that feeds recorded packets to the protocol.
    asyncio datagram endpoint (it also works with uvloop, which has no sock_recvfrom)."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    transport = None
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        if own_ip:
            with contextlib.suppress(OSError):
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(own_ip))
        sock.bind((own_ip or "", 0))
        sock.setblocking(False)
        transport, proto = await loop.create_datagram_endpoint(factory, sock=sock)
        for _ in range(2):  # UDP: two sends to be safe
            transport.sendto(payload, dest)
            await asyncio.sleep(0.1)
        await asyncio.sleep(timeout)
        return proto
    except OSError as exc:
        logger.warning("%s non disponibile: %s", label, exc)
        return None
    finally:
        if transport:
            transport.close()
        else:
            sock.close()


async def wsd_scan(own_ip: str | None = None, timeout: float = 3.0) -> dict[str, dict]:
    """WS-Discovery Probe in multicast; {ip: fields} for each device that answers."""
    proto = await _collect(_Collector, _PROBE.format(mid=uuid.uuid4()).encode(), WSD_ADDR, own_ip, timeout, "WS-Discovery")
    found = dict(proto.found) if proto else {}
    logger.info("WS-Discovery: %d dispositivi hanno risposto", len(found))
    return found


def parse_rtsp_response(text: str) -> dict | None:
    lines = text.split("\r\n") if "\r\n" in text else text.split("\n")
    if not lines or not lines[0].upper().startswith("RTSP/"):
        return None
    out: dict = {"rtsp": True}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip().lower(), value.strip()
        if key == "server" and value:
            out["rtsp_server"] = value[:120]
        elif key == "public" and value:
            out["rtsp_methods"] = value[:200]
    return out


async def rtsp_probe(ip: str, port: int = 554, timeout: float = 2.5) -> dict:
    """Unauthenticated RTSP OPTIONS: {} if the port does not answer as RTSP."""
    if port in scan_common.NO_REQUEST_PORTS:
        return {}        # never text to a printing or control port
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return {}
    try:
        writer.write(f"OPTIONS rtsp://{ip}:{port}/ RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: Vedetta\r\n\r\n".encode())
        await writer.drain()
        data = b""
        while b"\r\n\r\n" not in data and len(data) < 4096:
            chunk = await asyncio.wait_for(reader.read(1024), timeout)
            if not chunk:
                break
            data += chunk
    except (OSError, asyncio.TimeoutError):
        return {}
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    return parse_rtsp_response(data.decode("latin-1", "replace")) or {}


# ----------------------------------------------------------------- SSDP / UPnP
SSDP_ADDR = ("239.255.255.250", 1900)
_MSEARCH = 'M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\nST: ssdp:all\r\n\r\n'
_LOCATION = re.compile(rb"(?im)^location:\s*(\S+)")


class _Locations(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.found: dict[str, set[str]] = {}

    def datagram_received(self, data: bytes, addr) -> None:
        m = _LOCATION.search(data)
        location = m.group(1).decode("latin-1", "replace") if m else None
        if location and scan_common.safe_location(location, addr[0]):      # a URL that a device names is fetched only if it points back at that device (see check_ssdp_location.py)
            self.found.setdefault(addr[0], set()).add(location)


def parse_description(xml_text: str) -> dict:
    """Device types (deviceType, also nested) and name/manufacturer/model of the
    UPnP descriptor."""
    out: dict = {"types": []}
    for m in re.finditer(r"<deviceType>([^<]+)</deviceType>", xml_text):
        parts = m.group(1).strip().split(":")
        if len(parts) >= 2 and parts[-2] not in out["types"]:
            out["types"].append(parts[-2])
    for tag, key in (("friendlyName", "name"), ("manufacturer", "manufacturer"), ("modelName", "model")):
        m = re.search(r"<%s>([^<]*)</%s>" % (tag, tag), xml_text)
        if m and m.group(1).strip():
            out[key] = m.group(1).strip()[:120]
    return out


async def ssdp_devices(own_ip: str | None = None, timeout: float = 3.0, http_transport=None, skip: frozenset = frozenset()) -> dict[str, dict]:
    """M-SEARCH ssdp:all and reading of the descriptors: {ip: {types, name, manufacturer, model}}. `skip` = the addresses that must not be touched (touch_policy): their descriptor is not fetched.
    `http_transport` lets a test replace the HTTP network (httpx.MockTransport)."""
    import httpx  # late: only needed here

    proto = await _collect(_Locations, _MSEARCH.encode(), SSDP_ADDR, own_ip, timeout, "SSDP")
    locations = {ip: sorted(locs)[:4] for ip, locs in proto.found.items() if ip not in skip} if proto else {}

    async with httpx.AsyncClient(timeout=4, transport=http_transport) as client:
        results = await asyncio.gather(*(_describe_ssdp(client, ip, urls) for ip, urls in locations.items()))
    return {ip: info for ip, info in results if info.get("types") or info.get("name")}


async def _describe_ssdp(client, ip, urls):
    """The descriptors of one device, merged: every type, and the first value seen for each other field."""
    merged: dict = {"types": []}
    for url in urls:
        try:
            resp = await client.get(url)
            info = parse_description(resp.text)
        except Exception:
            continue
        merged["types"] += [t for t in info.pop("types") if t not in merged["types"]]
        for k, v in info.items():
            merged.setdefault(k, v)
    return ip, merged
