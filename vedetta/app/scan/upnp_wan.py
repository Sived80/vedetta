"""The address of the router on its internet side, asked to the router itself over UPnP (IGD): the only sure way to tell a double NAT.

Two private hops on the way out are not enough: a router inside the network (between VLANs, a layer 3 switch) gives two private
hops without any NAT. So the gateway is asked, on the local network only, for its WAN address (GetExternalIPAddress, read only):
a private address = double NAT for certain, a public one = no double NAT, an address in 100.64.0.0/10 = the provider's CGNAT.
Three messages to the gateway and nothing else: an SSDP search for the gateway device, its description, the SOAP question.
A router without UPnP, or with UPnP off, answers nothing: the answer is None and the path decides alone ("possible")."""
import asyncio
import re
from urllib.parse import urljoin

from . import scan_common
from .discovery import SSDP_ADDR, _collect, _Locations

_SEARCH = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\n'
           'ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n')
_SERVICE_RE = re.compile(r"<service>(.*?)</service>", re.DOTALL)
_WAN_TYPES = ("urn:schemas-upnp-org:service:WANIPConnection:", "urn:schemas-upnp-org:service:WANPPPConnection:")
_EXTERNAL_RE = re.compile(r"<NewExternalIPAddress>\s*([0-9.]{7,15})\s*</NewExternalIPAddress>")


def _tag(block: str, name: str) -> str:
    m = re.search(r"<%s>\s*([^<]+?)\s*</%s>" % (name, name), block)
    return m.group(1) if m else ""


def wan_service(description: str, location: str, gateway: str) -> tuple[str, str] | None:
    """(control URL, service type) of the WAN connection in the description of the gateway, or None. The control URL must point
    back at the gateway (scan_common.safe_location): an address a device names is never a place to send data to by itself."""
    blocks = [b for b in _SERVICE_RE.findall(description or "") if _tag(b, "serviceType").startswith(_WAN_TYPES)]
    found = [(urljoin(_tag(description, "URLBase") or location, _tag(b, "controlURL")), _tag(b, "serviceType")) for b in blocks]
    return next((f for f in found if scan_common.safe_location(f[0], gateway)), None)


def external_address(soap_answer: str) -> str | None:
    m = _EXTERNAL_RE.search(soap_answer or "")
    return m.group(1) if m else None


def soap_body(service_type: str) -> str:
    return ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            '<u:GetExternalIPAddress xmlns:u="%s"/></s:Body></s:Envelope>' % service_type)


async def wan_address(gateway: str, own_ip: str | None = None, timeout: float = 2.5, http_transport=None) -> str | None:
    """The WAN address the gateway declares, or None (no UPnP, no answer, anything odd). `http_transport` is for the tests."""
    import httpx  # late: only needed here

    proto = await _collect(_Locations, _SEARCH.encode(), SSDP_ADDR, own_ip, timeout, "UPnP IGD")
    locations = sorted((proto.found if proto else {}).get(gateway, ()))[:2]
    try:
        answers = await _ask_all(httpx.AsyncClient(timeout=3, transport=http_transport), locations, gateway)
    except (OSError, asyncio.TimeoutError, ValueError, httpx.HTTPError):
        return None
    return next((external_address(a) for a in answers if a is not None), None)


async def _ask_all(client, locations: list[str], gateway: str) -> list:
    async with client:
        return [await _ask(client, location, gateway) for location in locations]


async def _ask(client, location: str, gateway: str) -> str | None:
    """The SOAP answer of the WAN service described at `location`, or None when that description has no WAN service."""
    service = wan_service((await client.get(location)).text, location, gateway)
    if not service:
        return None
    answer = await client.post(service[0], content=soap_body(service[1]), headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": '"%s#GetExternalIPAddress"' % service[1]})
    return answer.text
