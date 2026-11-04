"""The router asked over UPnP for its WAN address (scan/upnp_wan.py): the WAN service is found in the description, its control URL must
point back at the gateway, the SOAP answer is read; a router without UPnP, a broken description or a URL towards another host give None."""
import asyncio
import os
import sys

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import upnp_wan  # noqa: E402

GW = "192.168.50.1"
DESC = """<root><device><deviceType>urn:schemas-upnp-org:device:InternetGatewayDevice:1</deviceType><deviceList><device>
<deviceType>urn:schemas-upnp-org:device:WANDevice:1</deviceType><serviceList>
<service><serviceType>urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1</serviceType><controlURL>/ctl/CmnIfCfg</controlURL></service>
<service><serviceType>urn:schemas-upnp-org:service:WANIPConnection:1</serviceType><controlURL>/ctl/IPConn</controlURL></service>
</serviceList></device></deviceList></device></root>"""
SOAP = """<s:Envelope><s:Body><u:GetExternalIPAddressResponse><NewExternalIPAddress>192.168.1.20</NewExternalIPAddress>
</u:GetExternalIPAddressResponse></s:Body></s:Envelope>"""

# the description
assert upnp_wan.wan_service(DESC, "http://192.168.50.1:5000/rootDesc.xml", GW) == ("http://192.168.50.1:5000/ctl/IPConn", "urn:schemas-upnp-org:service:WANIPConnection:1")
assert upnp_wan.wan_service(DESC.replace("WANIPConnection", "WANPPPConnection"), "http://192.168.50.1:5000/d.xml", GW)[1].endswith("WANPPPConnection:1")
assert upnp_wan.wan_service(DESC.replace("/ctl/IPConn", "http://192.168.50.9/ctl"), "http://192.168.50.1:5000/d.xml", GW) is None   # another host: never
assert upnp_wan.wan_service("<root/>", "http://192.168.50.1/d.xml", GW) is None and upnp_wan.wan_service(None, "", GW) is None
assert upnp_wan.external_address(SOAP) == "192.168.1.20" and upnp_wan.external_address("<x/>") is None
assert "GetExternalIPAddress" in upnp_wan.soap_body("urn:schemas-upnp-org:service:WANIPConnection:1")


# the whole question, with the network replaced: SSDP answer from the gateway, description and SOAP over a mock HTTP
class Heard:
    def __init__(self, found):
        self.found = found


def fake_collect(found):
    async def collect(factory, payload, dest, own_ip, timeout, label):
        assert b"InternetGatewayDevice" in payload
        return Heard(found)
    return collect


sent = []


def handler(request):
    sent.append((request.method, str(request.url)))
    if request.method == "GET":
        return httpx.Response(200, text=DESC)
    assert request.headers["SOAPAction"] == '"urn:schemas-upnp-org:service:WANIPConnection:1#GetExternalIPAddress"'
    return httpx.Response(200, text=SOAP)


upnp_wan._collect = fake_collect({GW: {"http://192.168.50.1:5000/rootDesc.xml"}})
assert asyncio.run(upnp_wan.wan_address(GW, http_transport=httpx.MockTransport(handler))) == "192.168.1.20"
assert sent == [("GET", "http://192.168.50.1:5000/rootDesc.xml"), ("POST", "http://192.168.50.1:5000/ctl/IPConn")], sent
# only the gateway counts; nothing heard; an HTTP error
sent.clear()
upnp_wan._collect = fake_collect({"192.168.50.7": {"http://192.168.50.7/d.xml"}})
assert asyncio.run(upnp_wan.wan_address(GW, http_transport=httpx.MockTransport(handler))) is None and not sent
upnp_wan._collect = fake_collect({})
assert asyncio.run(upnp_wan.wan_address(GW, http_transport=httpx.MockTransport(handler))) is None


def broken(request):
    raise httpx.ConnectError("refused")


upnp_wan._collect = fake_collect({GW: {"http://192.168.50.1:5000/rootDesc.xml"}})
assert asyncio.run(upnp_wan.wan_address(GW, http_transport=httpx.MockTransport(broken))) is None
print("TUTTO OK")
