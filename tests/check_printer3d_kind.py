# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""3D printers: the generic clues of the open-source printer hosts and of the printers that say what they are land a device in the type
"printer3d" (group "printer"); a paper printer stays a printer, a device with only the MQTT port stays a smart device.
Clues, all generic (no maker): the mDNS services of the printer host software (_octoprint._tcp, _moonraker._tcp), the UPnP device type
"3dprinter" (urn:<maker>:device:3dprinter:1) and the one of the API server (Moonraker), the title of the web interfaces (OctoPrint, Mainsail,
Fluidd), the default port of the API server (7125), the words of names and hostnames (octopi, klipper, "3D printer" in five languages) and
the Home Assistant integrations of the printer host software. Every device here is invented."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402
from app.recognition import roles  # noqa: E402

UPNP: dict = {}
roles.roles_for = lambda ip: []
roles.upnp_types = lambda ip: list(UPNP.get(ip, []))

failed = 0


def check(cond, msg):
    global failed
    if cond:
        print("ok:", msg)
    else:
        failed += 1
        print("FAILED:", msg)


def port(label, confirmed=False):
    return {"label": label, "confirmed": confirmed}


def dev(ip, name, *, vendor=None, role=None, extra=None, ports=(), ha=None):
    return {"id": "scan-" + ip, "ip": ip, "name": name, "brand": None, "vendor": vendor, "vendor_role": role,
            "extra": dict(extra or {}), "scanned_ports": list(ports), "ha_registry": ha}


def kind(d):
    group = ha_data.infer_type(d)
    return group, ha_data.best_kind(d)


PI = "Raspberry Pi Trading"
SSH = port("22 · ssh · OpenSSH", True)
WEB = port("80 · http · nginx", True)

cases = [
    ("printer host with the web interface and its mDNS service",
     dev("192.0.2.10", "octopi", vendor=PI, role="brand", ports=[SSH, WEB],
         extra={"title": "OctoPrint", "mdns_services": "_octoprint._tcp, _http._tcp, _workstation._tcp"})),
    ("printer host with only its mDNS service (no title read yet)",
     dev("192.0.2.11", "Device-11", vendor=PI, role="brand", ports=[SSH],
         extra={"mdns_services": "_octoprint._tcp, _http._tcp"})),
    ("API server of the printer firmware: its mDNS service and the default port",
     dev("192.0.2.12", "Device-12", vendor=PI, role="brand", ports=[SSH, WEB, port("7125 · unknown")],
         extra={"mdns_services": "_moonraker._tcp"})),
    ("web interface of the printer firmware (one of the two open-source ones) and the API port",
     dev("192.0.2.13", "Device-13", ports=[WEB, port("7125 · unknown")], extra={"title": "Mainsail"})),
    ("the other open-source web interface",
     dev("192.0.2.14", "Device-14", ports=[WEB], extra={"title": "Fluidd"})),
    ("a printer that declares the UPnP device type 3dprinter, with the MQTT port open",
     dev("192.0.2.15", "Device-15", vendor="Some Module Maker", role="component", ports=[port("8883 · secure-mqtt", True)])),
    ("the API server that declares its UPnP device type",
     dev("192.0.2.16", "Device-16", ports=[WEB])),
    ("the hostname says it in German", dev("192.0.2.17", "3D-Drucker Keller")),
    ("the name says it in French", dev("192.0.2.18", "Imprimante 3D")),
    ("the name says it in Czech", dev("192.0.2.19", "3D tiskárna")),
    ("the integration of the printer host software in Home Assistant",
     dev("192.0.2.20", "Device-20", ha={"domains": ["octoprint"], "entity_domains": ["sensor", "binary_sensor"]})),
]
UPNP["192.0.2.15"] = ["3dprinter"]
UPNP["192.0.2.16"] = ["Moonraker"]

for label, d in cases:
    got = kind(d)
    check(got == ("printer", "printer3d"), "%s -> %s" % (label, got))

# A paper printer does not move.
paper = dev("192.0.2.30", "Device-30", ports=[port("631 · ipp", True), port("9100 · jetdirect", True), WEB],
            extra={"mdns_services": "_ipp._tcp, _printer._tcp", "title": "Printer status"})
check(kind(paper) == ("printer", "printer"), "a paper printer with IPP stays a paper printer: %s" % (kind(paper),))
# The word "printer" alone (a paper printer named so) is not a 3D printer.
named = dev("192.0.2.31", "Printer office")
check(kind(named)[1] != "printer3d", "the word printer alone is not a 3D printer: %s" % (kind(named),))
# A device with only the MQTT port stays a smart home device.
mqtt = dev("192.0.2.32", "Device-32", ports=[port("8883 · secure-mqtt", True)])
check(ha_data.infer_type(mqtt) == "iot", "only the MQTT port: still a smart home device (%s)" % ha_data.infer_type(mqtt))
# A plain Raspberry Pi with SSH stays a server.
pi = dev("192.0.2.33", "Device-33", vendor=PI, role="brand", ports=[SSH])
check(ha_data.infer_type(pi) != "printer", "a plain board with SSH is not a printer: %s" % ha_data.infer_type(pi))
# A sailing word is not a printer host: "mainsail" counts in a title or a hostname, but nothing else in a name gives points.
other = dev("192.0.2.34", "Device-34", ports=[WEB], extra={"title": "Router login"})
check(kind(other)[1] != "printer3d", "an unrelated web page is not a 3D printer: %s" % (kind(other),))

print("FAILED: %d" % failed if failed else "ALL OK")
sys.exit(1 if failed else 0)
