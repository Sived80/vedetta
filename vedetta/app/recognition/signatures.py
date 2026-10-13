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
import re

from .. import datafile

DATA_PATH = datafile.DATA_DIR / "signatures.json"
_cache: dict = {"sigs": None}
TEXT_FIELDS = ("mdns_model", "upnp_model", "upnp_manufacturer", "dhcp_class", "http_server", "title", "brand", "port_labels", "api_source")
LIST_FIELDS = ("mdns_services", "ports", "ha_domains")


def load() -> list[dict]:
    if _cache["sigs"] is None:
        raw = datafile.read(DATA_PATH, "signatures", what="Catalog of signatures", default=[])      # once: the answer is cached
        _cache["sigs"] = [{**s, "_conds": [_condition(c) for c in s.get("all") or []]} for s in raw]
    return _cache["sigs"]


def _condition(c: dict) -> tuple:
    """(field, compiled pattern, None) for a regular expression, (field, None, text) for a plain «has»."""
    if "re" in c:
        return (c["field"], re.compile(c["re"], re.IGNORECASE), None)
    return (c["field"], None, c["has"])


def context(device: dict, upnp_types=()) -> dict:
    """The fields the signatures are evaluated on, taken from the device (probe format)."""
    extra = device.get("extra") or {}
    ports, labels = _ports_and_labels(device)
    return {
        "mdns_model": _text(extra, "mdns_model"), "upnp_model": _text(extra, "upnp_model"),
        "upnp_manufacturer": _text(extra, "upnp_manufacturer"), "dhcp_class": _text(extra, "dhcp_class"),
        "http_server": _text(extra, "http_server"), "title": _text(extra, "title"),
        "brand": _text(device, "brand"), "port_labels": " ".join(labels), "api_source": _text(extra, "api_source"),
        "mdns_services": _service_set(extra),
        "ports": ports, "ha_domains": list((device.get("ha_registry") or {}).get("domains") or []),
        "upnp_types": list(upnp_types),
    }


def _text(source: dict, key: str):
    """A text field of the device, "" when it is missing or empty."""
    return source.get(key) or ""


def _ports_and_labels(device: dict) -> tuple[list, list]:
    """The port numbers and the lower-case labels of the scanned ports (a label starts with the number of the port)."""
    ports, labels = [], []
    for p in device.get("scanned_ports") or []:
        label = p.get("label") or ""
        labels.append(label.lower())
        m = re.match(r"\s*(\d+)", label)
        if m:
            ports.append(int(m.group(1)))
    return ports, labels


def _service_set(extra: dict) -> set:
    """The mDNS services announced, as a set of names without spaces."""
    return {s.strip() for s in (extra.get("mdns_services") or "").replace(" ", "").split(",") if s.strip()}


def matches(device: dict, upnp_types=()) -> list[dict]:
    """Signatures satisfied by the device, from the most specific (most conditions) to the least."""
    ctx = context(device, upnp_types)
    found = [s for s in load() if s["_conds"] and all(_holds(c, ctx) for c in s["_conds"])]
    found.sort(key=lambda s: -len(s["_conds"]))
    return found


def _holds(cond, ctx: dict) -> bool:
    field, rx, has = cond
    value = ctx.get(field)
    if rx is not None:
        return bool(value) and bool(rx.search(str(value)))
    return has in (value or ())
