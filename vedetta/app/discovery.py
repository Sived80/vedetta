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

from .applog import logger

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
_ONVIF_SCOPE = re.compile(r"^onvif://www\.onvif\.org/(name|hardware|location|manufacturer|mfr|type|model)/(.+)$", re.I)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_probe_match(data: bytes) -> dict | None:
    """Fields of a WS-Discovery ProbeMatch; None if it is not a valid ProbeMatch."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    types = scopes = xaddrs = ""
    found = False
    for el in root.iter():
        name = _local(el.tag)
        if name == "ProbeMatch":
            found = True
        elif name == "Types" and el.text:
            types = el.text.strip()
        elif name == "Scopes" and el.text:
            scopes = el.text.strip()
        elif name == "XAddrs" and el.text:
            xaddrs = el.text.strip()
    if not found:
        return None
    info: dict = {"types": [t.split(":")[-1] for t in types.split()], "xaddrs": xaddrs.split()}
    onvif: dict[str, list[str]] = {}
    for scope in scopes.split():
        m = _ONVIF_SCOPE.match(scope)
        if m:
            key = m.group(1).lower()
            key = "manufacturer" if key == "mfr" else key
            onvif.setdefault(key, []).append(unquote(m.group(2)).replace("_", " ").strip())
    for key in ("name", "hardware", "manufacturer", "model"):
        if onvif.get(key):
            info[key] = onvif[key][0]
    if onvif.get("location"):
        info["location"] = onvif["location"][0]
    info["onvif"] = bool(onvif) or any("NetworkVideoTransmitter" in t for t in info["types"])
    return info


class _Collector(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.found: dict[str, dict] = {}

    def datagram_received(self, data: bytes, addr) -> None:
        info = parse_probe_match(data)
        if info and addr[0] not in self.found:
            self.found[addr[0]] = info


async def wsd_scan(own_ip: str | None = None, timeout: float = 3.0) -> dict[str, dict]:
    """WS-Discovery Probe in multicast; {ip: fields} for each device that answers.
    asyncio datagram endpoint (it also works with uvloop, which has no sock_recvfrom)."""
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    transport = None
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        if own_ip:
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(own_ip))
            except OSError:
                pass
        sock.bind((own_ip or "", 0))
        sock.setblocking(False)
        transport, proto = await loop.create_datagram_endpoint(_Collector, sock=sock)
        msg = _PROBE.format(mid=uuid.uuid4()).encode()
        for _ in range(2):  # UDP: two sends to be safe
            transport.sendto(msg, WSD_ADDR)
            await asyncio.sleep(0.1)
        await asyncio.sleep(timeout)
        found = dict(proto.found)
    except OSError as exc:
        logger.warning("WS-Discovery non disponibile: %s", exc)
        found = {}
    finally:
        if transport:
            transport.close()
        else:
            sock.close()
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
        try:
            await writer.wait_closed()
        except OSError:
            pass
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
        if m:
            self.found.setdefault(addr[0], set()).add(m.group(1).decode("latin-1", "replace"))


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


async def ssdp_devices(own_ip: str | None = None, timeout: float = 3.0) -> dict[str, dict]:
    """M-SEARCH ssdp:all and reading of the descriptors: {ip: {types, name, manufacturer, model}}."""
    import httpx  # late: only needed here

    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    transport = None
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        if own_ip:
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(own_ip))
            except OSError:
                pass
        sock.bind((own_ip or "", 0))
        sock.setblocking(False)
        transport, proto = await loop.create_datagram_endpoint(_Locations, sock=sock)
        for _ in range(2):
            transport.sendto(_MSEARCH.encode(), SSDP_ADDR)
            await asyncio.sleep(0.1)
        await asyncio.sleep(timeout)
        locations = {ip: sorted(locs)[:4] for ip, locs in proto.found.items()}
    except OSError as exc:
        logger.warning("SSDP non disponibile: %s", exc)
        locations = {}
    finally:
        if transport:
            transport.close()
        else:
            sock.close()

    async def describe(client, ip, urls):
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

    async with httpx.AsyncClient(timeout=4) as client:
        results = await asyncio.gather(*(describe(client, ip, urls) for ip, urls in locations.items()))
    return {ip: info for ip, info in results if info.get("types") or info.get("name")}
