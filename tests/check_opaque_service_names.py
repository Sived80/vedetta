"""A DNS-SD service name is an opaque identifier (RFC 6763, section 7: "some unique opaque Service Name"): it is compared whole with the tables of declared services, never cut into words like free text.
Before, the declared services were also read as prose, so the same fact counted twice and a piece of a compound name of a maker became a word of function ("monitor" in _solaredge-sense-monitor._udp
made a computer of an inverter). The test is made from the data:
  - for EVERY word of function of the device types (data/device_kinds.json), a service called after it - alone or inside a compound - gives no point as a word;
  - the free text keeps its words (a device NAMED "monitor" is still read as a monitor);
  - the declared services keep telling (a printer with its printing services is a printer; a scanner service gives the type scanner, as the word in its name did before)."""
import os
import re
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402
from app.ha import ha_type_evidence as T  # noqa: E402


def card(services=None, name=None, brand=None):
    extra = {"mdns_services": services} if services else {}
    return {"id": "x", "ip": "10.0.0.50", "name": name or "10.0.0.50", "name_generated": name is None, "brand": brand, "vendor": brand, "vendor_role": None,
            "extra": extra, "scanned_ports": [], "ha_registry": None, "is_mobile": False}


def word_clues(device):
    """The clues that come from words of the text (the types of data/device_kinds.json and the rules of data/type_words.json)."""
    return [c for c in T._Clues(device, None, {}).collect() if c["source"].startswith("parola")]


def kinds_of(device):
    kinds: dict = {}
    T.type_scores(device, None, kinds)
    return kinds


# 1. the case seen in an export: a maker's compound name with a word of function inside
inverter = card("_solaredge-inv._tcp, _solaredge-modbus._tcp, _solaredge-sense-monitor._udp", brand="SolarEdge")
assert not word_clues(inverter) and ha_data.infer_type(inverter, None) == "generic", (word_clues(inverter), ha_data.infer_type(inverter, None))

# 2. the class, from the data: no word of function gives points when it only appears in a service name (alone or inside a compound)
WORDS = sorted({w.lower() for k in T._read_kind_rows() for w in list(k.get("words", [])) + list(k.get("tokens", [])) if re.fullmatch(r"[a-z0-9]+", w.lower())})
assert len(WORDS) > 200, len(WORDS)
bad = [w for w in WORDS for svc in ("_%s._tcp" % w, "_demo-%s._udp" % w, "_%s-demo._tcp" % w) if word_clues(card(svc))]
assert not bad, bad[:10]

# 3. the free text is still read: a device named after a function is read as such
named = card(name="monitor")
assert [c["source"] for c in word_clues(named)] == ["parola: monitor"] and ha_data.infer_type(named, None) == "pc", word_clues(named)

# 4. the declared services still tell: a printer with its services, and the service of a scanner (it was the word in its name that said "scanner" before)
hp = card("_http._tcp, _ipp._tcp, _ipps._tcp, _pdl-datastream._tcp, _scanner._tcp", brand="HP")
kinds = kinds_of(hp)
assert ha_data.infer_type(hp, None) == "printer" and kinds.get("printer", 0) > kinds.get("scanner", 0) > 0, (ha_data.infer_type(hp, None), kinds)
print("TUTTO OK")
