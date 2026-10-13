"""scan_protocols: moved out of scanner.py (see tools/split_module.py)."""
import xml.etree.ElementTree as ET
from .scan_nmap import _LIGHT_NMAP_SEMAPHORE, _run_nmap
from ..iface import lan_iface
import re
from ..formatters import truncate_name


_UPNP_LOCATION_RE = re.compile(r"Location:\s*https?://([\d.]+)(?::\d+)?/")


_UPNP_FIELD_RE = re.compile(r"^\s*(Name|Manufacturer|Model Name|Server)\s*:\s*(.+?)\s*$")


_UPNP_FIELD_MAP = {"Name": "name", "Manufacturer": "manufacturer", "Model Name": "model", "Server": "server"}


async def ssdp_scan(timeout: int = 6) -> dict[str, dict]:
    """SSDP/UPnP discovery (IETF/UPnP Forum standard, M-SEARCH multicast request):
    TVs, NAS, media servers and routers with DLNA features often reply with real name,
    manufacturer and model - information that neither ARP nor mDNS sees, because
    they are two different protocols covering different families of devices.

    It is a "prerule" script (nmap calls it broadcast-upnp-info): it runs only once
    for the whole LAN before processing any target, so a dummy
    target (127.0.0.1, never actually scanned) is enough just to get
    nmap started - verified that the script activates anyway."""
    output = await _prescript_output("broadcast-upnp-info", timeout)
    return _parse_upnp_output(output) if output else {}


async def _prescript_output(script_id: str, host_timeout: int, script_args: str | None = None) -> str | None:
    """The output of an nmap "prerule" script (it runs once for the whole LAN; the target 127.0.0.1 is never scanned, it only gets nmap started), or None when
    nmap gave no usable XML or the script said nothing."""
    args = ["-sn", "--script", script_id, "-e", lan_iface()]
    if script_args:
        args += ["--script-args", script_args]
    xml_text = await _run_nmap(args + ["--host-timeout", f"{host_timeout}s", "127.0.0.1"], semaphore=_LIGHT_NMAP_SEMAPHORE)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    script_el = root.find(f"prescript/script[@id='{script_id}']")
    if script_el is None or not script_el.get("output"):
        return None
    return script_el.get("output")


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
    output = await _prescript_output("broadcast-igmp-discovery", timeout + 4, f"broadcast-igmp-discovery.timeout={timeout}s")
    return parse_igmp(output) if output else {}


# What a line of broadcast-dhcp-discover says -> the key of the offer; the two that are lists of addresses.
_DHCP_KEYS = {"server identifier": "server", "ip offered": "offered", "router": "router",
              "domain name server": "dns", "domain name": "domain", "ip address lease time": "lease",
              "subnet mask": "netmask", "dhcp message type": "type"}
_DHCP_LISTS = ("dns", "router")


def parse_dhcp_offers(output: str) -> list[dict]:
    """broadcast-dhcp-discover text -> one entry for each server that replied
    (DHCPOFFER): server, offered IP, gateway, DNS, domain, lease duration."""
    offers: list[dict] = []
    current: dict | None = None
    for raw in output.splitlines():
        line = raw.strip()
        if line.lower().startswith("response "):
            current = {}
            offers.append(current)
            continue
        parsed = _dhcp_field(line) if current is not None else None
        if parsed:
            field, value = parsed
            current[field] = [v.strip() for v in value.split(",") if v.strip()] if field in _DHCP_LISTS else value
    return [o for o in offers if _is_offer(o)]


def _dhcp_field(line: str) -> tuple[str, str] | None:
    """(key of the offer, value) of a "Name: value" line the offer cares about; None for any other line."""
    if ":" not in line:
        return None
    key, value = line.split(":", 1)
    field = _DHCP_KEYS.get(key.strip().lower())
    return (field, value.strip()) if field else None


def _is_offer(offer: dict) -> bool:
    """A real offer: it names its server and is not a refusal (DHCPNAK)."""
    return bool(offer.get("server")) and str(offer.get("type", "DHCPOFFER")).upper() == "DHCPOFFER"


async def dhcp_discover(timeout: int = 8) -> list[dict]:
    """Test DHCP DISCOVER (RFC 2131): DHCP servers reply with an offer
    that is NEVER accepted (no lease assigned). It reveals who hands out
    the addresses and what clients receive: gateway, DNS, domain, lease duration;
    more than one server = unwanted DHCP on the network."""
    output = await _prescript_output("broadcast-dhcp-discover", timeout + 8, f"broadcast-dhcp-discover.timeout={timeout}s")
    return parse_dhcp_offers(output) if output else []


_NETBIOS_NAME_RE = re.compile(r"NetBIOS name:\s*([^,]+)")


_SNMP_DESCR_RE = re.compile(r"(?:System description|sysDescr)\s*:\s*(.+)")


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
        _apply_host_script(info, script_el.get("id"), script_el.get("output") or "")
    return info


def _apply_host_script(info: dict, script_id: str | None, output: str) -> None:
    if script_id == "nbstat":
        name = _netbios_name(output)
        if name is not None:
            info["netbios_name"] = name
    elif script_id in ("snmp-sysdescr", "snmp-info"):
        value = _snmp_description(output)
        if value and "snmp_descr" not in info:
            info["snmp_descr"] = value


def _netbios_name(output: str) -> str | None:
    m = _NETBIOS_NAME_RE.search(output)
    return truncate_name(m.group(1).strip()) if m else None


def _snmp_description(output: str) -> str | None:
    """The "System description" line, or else the first line of whatever the script printed."""
    m = _SNMP_DESCR_RE.search(output)
    if m:
        return m.group(1).strip()
    return output.strip().splitlines()[0].strip() if output.strip() else None
