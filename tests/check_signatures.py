"""Signature catalogue and hint families: file validation, real cases, ambiguous cases (Google Home / Chromecast),
double counts (Cast), port cap, margin between tied categories, hint explanation."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import ha_data, roles, signatures  # noqa: E402

roles.roles_for = lambda ip: []
roles.upnp_types = lambda ip: []

# ---- the signatures file is valid (unique ids, existing categories and types, compilable expressions, declared fixture)
data = json.load(open(signatures.DATA_PATH, encoding="utf-8"))
kind_ids = {k["id"] for k in json.load(open(ha_data.Path(ha_data.__file__).parent / "data" / "device_kinds.json", encoding="utf-8"))["kinds"]}
ids = [s["id"] for s in data["signatures"]]
assert data["schema"] == 1 and len(ids) == len(set(ids)), "id unici"
for s in data["signatures"]:
    assert ha_data._MERGED_GROUPS.get(s["group"], s["group"]) in ha_data.TYPE_ORDER, s["id"]
    assert s.get("kind") in kind_ids, (s["id"], s.get("kind"))
    assert s["fixture"] in ("real", "simulated") and s["all"], s["id"]
    for c in s["all"]:
        assert c["field"] in signatures.TEXT_FIELDS + signatures.LIST_FIELDS, (s["id"], c["field"])
        if "re" in c:
            re.compile(c["re"])
        else:
            assert "has" in c
print("ok: file delle firme valido (%d firme)" % len(ids))


def port(label, confirmed=False):
    return {"label": label, "confirmed": confirmed}


def kind_of(dev):
    """(category, type with the most points INSIDE that category), as the icon does."""
    group = ha_data.infer_type(dev)
    kinds = {}
    ha_data.type_scores(dev, None, kinds)
    in_group = {k: v for k, v in kinds.items() if any(kd["id"] == k and kd["group"] == group for kd in ha_data._kinds())}
    return group, max(in_group, key=in_group.get) if in_group else None


# ---- REAL devices (data read from the network on 2026-10-05)
real = [
    ("Proxmox", {"ip": "x", "name": "pve", "brand": "Proxmox", "extra": {"http_server": "pve-api-daemon/3.0", "title": "pve - Proxmox Virtual Environment"},
                 "scanned_ports": [port("22 · ssh"), port("8006 · wpl-analytics"), port("3128 · squid-http")]}, "server", "server"),
    ("Fire TV Stick", {"ip": "x", "name": "Android", "brand": "Amazon", "extra": {"mdns_services": "_amzn-wplay._tcp"},
                       "scanned_ports": [port("5555 · Android Debug Bridge", True), port("40027 · Amazon FireTV Stick", True)]}, "media", "streaming"),
    ("PlayStation 3", {"ip": "x", "name": "x", "brand": "Sony", "extra": {"dhcp_class": "PS3"},
                       "scanned_ports": [port("21 · ftp", True), port("80 · http"), port("9309 · unknown")]}, "media", "console"),
    ("Home Assistant", {"ip": "x", "name": "Home Assistant", "extra": {"title": "Home Assistant", "mdns_services": "_home-assistant._tcp"},
                        "scanned_ports": [port("8123 · polipo"), port("111 · rpcbind")]}, "server", "homeassistant"),
    ("Node-RED", {"ip": "x", "name": "Node-RED", "extra": {"title": "Node-RED"}, "scanned_ports": [port("22 · ssh"), port("1880 · vsat-control")]}, "server", None),
    ("Grafana", {"ip": "x", "name": "Grafana", "extra": {"title": "Grafana"}, "scanned_ports": [port("3000 · ppp")]}, "server", None),
]
for label, dev, group, kind in real:
    got_group, got_kind = kind_of(dev)
    assert got_group == group, (label, got_group, ha_data.type_scores(dev))
    if kind:
        assert got_kind == kind, (label, got_kind)
print("ok: casi reali")

# ---- Google Home and Chromecast both announce Cast: the model decides (data simulated by the manufacturer)
cast = {"mdns_services": "_googlecast._tcp", "api_source": "cast"}
cast_ports = [port("8008 · http", True), port("8009 · castv2", True), port("8443 · https-alt", True)]
home = {"ip": "x", "name": "Soggiorno", "brand": "Google", "extra": {**cast, "mdns_model": "Google Home Mini"}, "scanned_ports": cast_ports}
chrome = {"ip": "x", "name": "TV camera", "brand": "Google", "extra": {**cast, "mdns_model": "Chromecast"}, "scanned_ports": cast_ports}
nameless = {"ip": "x", "name": "Cast", "brand": "Google", "extra": dict(cast), "scanned_ports": cast_ports}
assert kind_of(home) == ("audio", "speaker"), (kind_of(home), ha_data.type_scores(home))
assert kind_of(chrome) == ("media", "streaming"), kind_of(chrome)
assert ha_data.infer_type(nameless) == "media"   # without a model: Cast alone says "media"
print("ok: Google Home / Chromecast")

# ---- Cast counts once (service + API + ports + DIAL are the same fact)
ev = ha_data.type_evidence(nameless)
cast_pts = [e["pts"] for e in ev if e["family"] == "cast" and e["group"] == "media"]
media_pts = ha_data.type_scores(nameless)["media"]
assert len(cast_pts) >= 3 and max(cast_pts) <= media_pts < sum(cast_pts), (cast_pts, media_pts)   # one, not the sum
# in the debug data every hint has group, family, points and source
assert all(set(e) == {"group", "family", "pts", "source"} for e in ev)

# ---- port cap: many "server" ports do not make a server by themselves
many = {"ip": "x", "name": "x", "extra": {}, "scanned_ports": [port("%d · x" % p, True) for p in (22, 2049, 3306, 5432, 6379, 27017, 1433)]}
assert ha_data.type_scores(many)["server"] <= ha_data.W_PORTS_MAX, ha_data.type_scores(many)

# ---- margin: two tied categories with weak hints -> "generic" instead of picking at random
tie = {"ip": "x", "name": "x", "extra": {}, "scanned_ports": [port("631 · x", True), port("22 · x", True)]}
scores = ha_data.type_scores(tie)
assert scores.get("printer") == scores.get("server") == 4 and ha_data.infer_type(tie) == "generic", scores
strong = {"ip": "x", "name": "x", "extra": {"mdns_services": "_googlecast._tcp"}, "scanned_ports": [port("22 · ssh", True)]}
assert ha_data.infer_type(strong) == "media"   # a declared hint always wins
print("TUTTO OK")
