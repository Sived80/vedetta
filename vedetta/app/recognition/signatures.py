"""Catalog of declarative product signatures (app/data/signatures.json).

A signature is a set of conditions on what the device declares (mDNS model, services, UPnP type, DHCP
class, Server header, title, ports...) and says what it is (category, type). It is used where the generic signals are
ambiguous: Google Home and Chromecast both announce "Cast", but only the model tells them apart. It is extended
by adding a row to the file, without touching the code; each signature states which device it comes from ("fixture":
"real" = read from a real device, "simulated" = from the manufacturer's known data, to be confirmed with a real one).

Conditions (all must be satisfied):
  {"field": <field>, "re": <regular expression, case-insensitive>}   text field
  {"field": "mdns_services" | "ports" | "ha_domains", "has": <value>}                 list field
Fields: mdns_model, mdns_services, upnp_model, upnp_manufacturer, dhcp_class, http_server, title, brand, port_labels,
ports, api_source, ha_domains."""
import json
import re
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "signatures.json"
_cache: dict = {"sigs": None}
TEXT_FIELDS = ("mdns_model", "upnp_model", "upnp_manufacturer", "dhcp_class", "http_server", "title", "brand", "port_labels", "api_source")
LIST_FIELDS = ("mdns_services", "ports", "ha_domains")


def load() -> list[dict]:
    if _cache["sigs"] is None:
        try:
            raw = json.loads(DATA_PATH.read_text(encoding="utf-8"))["signatures"]
        except (OSError, ValueError, KeyError):
            raw = []
        out = []
        for s in raw:
            conds = []
            for c in s.get("all") or []:
                if "re" in c:
                    conds.append((c["field"], re.compile(c["re"], re.IGNORECASE), None))
                else:
                    conds.append((c["field"], None, c["has"]))
            out.append({**s, "_conds": conds})
        _cache["sigs"] = out
    return _cache["sigs"]


def context(device: dict, upnp_types=()) -> dict:
    """The fields the signatures are evaluated on, taken from the device (probe format)."""
    extra = device.get("extra") or {}
    ports, labels = [], []
    for p in device.get("scanned_ports") or []:
        label = p.get("label") or ""
        labels.append(label.lower())
        m = re.match(r"\s*(\d+)", label)
        if m:
            ports.append(int(m.group(1)))
    return {
        "mdns_model": extra.get("mdns_model") or "", "upnp_model": extra.get("upnp_model") or "",
        "upnp_manufacturer": extra.get("upnp_manufacturer") or "", "dhcp_class": extra.get("dhcp_class") or "",
        "http_server": extra.get("http_server") or "", "title": extra.get("title") or "",
        "brand": device.get("brand") or "", "port_labels": " ".join(labels), "api_source": extra.get("api_source") or "",
        "mdns_services": {s.strip() for s in (extra.get("mdns_services") or "").replace(" ", "").split(",") if s.strip()},
        "ports": ports, "ha_domains": list((device.get("ha_registry") or {}).get("domains") or []),
        "upnp_types": list(upnp_types),
    }


def _holds(cond, ctx: dict) -> bool:
    field, rx, has = cond
    value = ctx.get(field)
    if rx is not None:
        return bool(value) and bool(rx.search(str(value)))
    return has in (value or ())


def matches(device: dict, upnp_types=()) -> list[dict]:
    """Signatures satisfied by the device, from the most specific (most conditions) to the least."""
    ctx = context(device, upnp_types)
    found = [s for s in load() if s["_conds"] and all(_holds(c, ctx) for c in s["_conds"])]
    found.sort(key=lambda s: -len(s["_conds"]))
    return found
