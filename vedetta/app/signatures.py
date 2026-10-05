"""Catalogo di firme dichiarative dei prodotti (app/data/signatures.json).

Una firma e' un insieme di condizioni su cio' che il dispositivo dichiara (modello mDNS, servizi, tipo UPnP, classe
DHCP, intestazione Server, titolo, porte...) e dice cos'e' (categoria, tipo). Serve dove i segnali generici sono
ambigui: Google Home e Chromecast annunciano entrambi "Cast", ma solo il modello li distingue. Si estende
aggiungendo una riga al file, senza toccare il codice; ogni firma indica da quale dispositivo viene ("fixture":
"real" = letto da un dispositivo vero, "simulated" = dai dati noti del produttore, da confermare con uno vero).

Condizioni (tutte da soddisfare):
  {"field": <campo>, "re": <espressione regolare, senza distinzione di maiuscole>}   campo testuale
  {"field": "mdns_services" | "ports" | "ha_domains", "has": <valore>}                 campo a elenco
Campi: mdns_model, mdns_services, upnp_model, upnp_manufacturer, dhcp_class, http_server, title, brand, port_labels,
ports, api_source, ha_domains."""
import json
import re
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "data" / "signatures.json"
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
    """I campi su cui si valutano le firme, dal dispositivo (formato di probe)."""
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
    """Firme soddisfatte dal dispositivo, dalla piu' specifica (piu' condizioni) alla meno."""
    ctx = context(device, upnp_types)
    found = [s for s in load() if s["_conds"] and all(_holds(c, ctx) for c in s["_conds"])]
    found.sort(key=lambda s: -len(s["_conds"]))
    return found
