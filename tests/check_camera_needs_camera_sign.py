# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""GitHub issue #61: the maker of the MAC prefix alone does not make a camera. An alarm interface whose MAC prefix belongs to a maker of cameras (the public OUI 00:40:8C) was shown as a camera and named
"<brand> camera" with no camera sign at all. The brand of a camera maker (data/device_kinds.json, "brands" of the type camera, with "brand_alone": false) now only confirms a camera that shows a sign of
its own (RTSP, ONVIF / WS-Discovery, the camera port, a camera word, Home Assistant); the brand itself still shows in the name."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import i18n  # noqa: E402
from app.ha import ha_data  # noqa: E402
from app.scan import probe_names  # noqa: E402
from app.scan.probe_record import Product  # noqa: E402

i18n.current_lang.set("en")
BASE = {"ip": "192.0.2.61", "mac": "00:40:8c:00:00:61", "vendor": "Axis Communications AB", "vendor_role": "brand", "brand": "Axis", "scanned_ports": []}


def card(**changes) -> dict:
    return {**BASE, **changes}


def generated_name(device: dict) -> str:
    f = SimpleNamespace(ip=device["ip"], scanned_ports=device["scanned_ports"], ha_card=device.get("ha_registry"))
    names = probe_names.NameState(base_name=None, placeholder=False, ha_stale=False, display_name=device["ip"])
    product = Product(device.get("extra") or {}, device["vendor"], device["brand"])
    probe_names.name_from_brand_and_type(f, names, product, {"vendor_role": device["vendor_role"], "brand_source": "vendor", "brand_evidence": "confirmed"}, False)
    return names.display_name


# the prefix alone: not a camera, not called a camera, the brand stays
alone = card()
assert ha_data.infer_type(alone) != "camera", ha_data.type_evidence(alone)
assert generated_name(alone) == "Axis", generated_name(alone)
assert ha_data.infer_type(card(brand=None)) != "camera", "the vendor alone"
assert ha_data.infer_type(card(scanned_ports=[{"label": "80/tcp http", "confirmed": True}])) != "camera", "a web page is not a camera sign"

# with a sign of a camera it stays a camera, and the brand still counts for it
for sign in (card(extra={"rtsp_server": "GStreamer RTSP server"}),
             card(extra={"wsd_types": "dn:NetworkVideoTransmitter"}),
             card(extra={"onvif_name": "Front"}),
             card(scanned_ports=[{"label": "554/tcp rtsp", "confirmed": True}]),
             card(name="Ingresso ipcam")):
    assert ha_data.infer_type(sign) == "camera", (sign, ha_data.type_evidence(sign))
    assert any(e["family"] == "brand" for e in ha_data.type_evidence(sign)), "the brand confirms the camera"
assert generated_name(card(extra={"rtsp_server": "GStreamer RTSP server"})) == "Axis camera"

# the other types that list makers are unchanged: the brand alone still counts
printer = {"ip": "192.0.2.62", "mac": "02:00:00:00:00:62", "brand": "Epson", "vendor": "Seiko Epson", "vendor_role": "brand", "scanned_ports": []}
assert any(e["family"] == "brand" and e["group"] == "printer" for e in ha_data.type_evidence(printer))
print("ALL OK")
