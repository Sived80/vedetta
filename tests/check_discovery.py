"""WS-Discovery (ONVIF), RTSP and brand evidence (confirmed/plausible/declared generic)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import discovery  # noqa: E402
from app.recognition.identity import identify_brand  # noqa: E402

# Real ProbeMatch from a white-label camera (reduced form, real fields from the test).
PM = b"""<?xml version="1.0" encoding="UTF-8"?>
<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://www.w3.org/2003/05/soap-envelope" xmlns:wsdd="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:dn="http://www.onvif.org/ver10/network/wsdl"><SOAP-ENV:Body><wsdd:ProbeMatches><wsdd:ProbeMatch>
<wsdd:Types>dn:NetworkVideoTransmitter</wsdd:Types>
<wsdd:Scopes>onvif://www.onvif.org/type/video_encoder onvif://www.onvif.org/name/IPCAM onvif://www.onvif.org/hardware/IPCAM onvif://www.onvif.org/location/country/china</wsdd:Scopes>
<wsdd:XAddrs>http://192.168.50.199:8080/onvif/device_service</wsdd:XAddrs>
</wsdd:ProbeMatch></wsdd:ProbeMatches></SOAP-ENV:Body></SOAP-ENV:Envelope>"""
r = discovery.parse_probe_match(PM)
assert r["name"] == "IPCAM" and r["hardware"] == "IPCAM" and r["onvif"] and r["types"] == ["NetworkVideoTransmitter"], r
assert r["location"] == "country/china" and r["xaddrs"] == ["http://192.168.50.199:8080/onvif/device_service"], r
# Name encoded in the URL and manufacturer.
r = discovery.parse_probe_match(PM.replace(b"name/IPCAM", b"name/HIKVISION%20DS-2CD").replace(b"location/", b"mfr/Hikvision onvif://www.onvif.org/location/"))
assert r["name"] == "HIKVISION DS-2CD" and r["manufacturer"] == "Hikvision", r
assert discovery.parse_probe_match(b"<x/>") is None and discovery.parse_probe_match(b"not xml") is None

# RTSP OPTIONS.
r = discovery.parse_rtsp_response("RTSP/1.0 200 OK\r\nCSeq: 1\r\nServer: Hipcam RealServer/V1.0\r\nPublic: OPTIONS, DESCRIBE\r\n\r\n")
assert r == {"rtsp": True, "rtsp_server": "Hipcam RealServer/V1.0", "rtsp_methods": "OPTIONS, DESCRIBE"}, r
assert discovery.parse_rtsp_response("RTSP/1.0 200 OK\r\nCSeq: 1\r\n\r\n") == {"rtsp": True}
assert discovery.parse_rtsp_response("HTTP/1.1 200 OK\r\n\r\n") is None

# Brand evidence.
cam = identify_brand("00:AD:11:00:00:B1", names=["IPCAM"], declared=[None, None, "IPCAM"])
assert cam["brand"] is None and cam["brand_evidence"] is None and cam["brand_declared"] == "IPCAM", cam
tv = identify_brand("38:B8:00:00:00:A8", names=["SONY XR-55X92K"], upnp_manufacturer="Sony")
assert tv["brand"] == "Sony" and tv["brand_evidence"] in ("confirmed", "plausible"), tv
nvr = identify_brand("1C:C3:16:00:00:AA")
print("nvr:", nvr)
print("tv:", tv)
print("TUTTO OK")
