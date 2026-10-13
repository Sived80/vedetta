"""mdns_parse: moved out of scan_mdns.py (see tools/split_module.py)."""
import re


_MDNS_NAME_KEYS = (("friendly_name", 3), ("fn", 3), ("location_name", 2))


# Services whose instance name is the name the user gave to the device
# (Apple, Sonos, HomeKit): better than the generic instance of any other service.
_MDNS_USER_NAMED = {"_airplay._tcp", "_companion-link._tcp", "_hap._tcp", "_sonos._tcp", "_googlecast._tcp"}


# Services whose instance name is the label of the service, not a name of the device: the Alexa app announces "expiscor" from every phone it runs on.
# Such a name is never told as the name of the device when it is all that was heard (the service itself still counts).
_MDNS_LABEL_ONLY = {"_amazon-expiscor._udp"}


_MDNS_SLUG_RE = re.compile(r"^[0-9a-f]{6,10}-", re.IGNORECASE)


_MDNS_MODEL_KEYS = ("model", "am", "md")


_MDNS_MANUFACTURER_KEYS = ("manufacturer", "mf")


def parse_mdns_txt(txt: str) -> dict:
    """{"model", "manufacturer"} from the TXT string (`"k=v" "k2=v2"`) built by _props_to_txt (`"k=v" "k2=v2"`)."""
    pairs = dict(m.groups() for m in re.finditer(r'"([A-Za-z]+)=([^"]*)"', txt))
    out = {}
    for field, keys in (("model", _MDNS_MODEL_KEYS), ("manufacturer", _MDNS_MANUFACTURER_KEYS)):
        for key in keys:
            if pairs.get(key):
                out[field] = pairs[key][:60]
                break
    return out


_MDNS_META_TYPE = "_services._dns-sd._udp.local."


def _props_to_txt(props: dict) -> str:
    """zeroconf TXT record -> string `"k=v" "k2=v2"`, the format that
    parse_mdns_txt and the name choice already knew how to read."""
    parts = []
    for key, val in (props or {}).items():
        k = key.decode("utf-8", "replace") if isinstance(key, bytes) else str(key)
        if val is None:
            continue
        v = val.decode("utf-8", "replace") if isinstance(val, bytes) else str(val)
        parts.append('"%s=%s"' % (k.replace('"', ""), v.replace('"', "")))
    return " ".join(parts)
