"""ha_type_text: moved out of ha_type_evidence.py (see tools/split_module.py)."""
import re
from functools import lru_cache

from .. import datafile


# Order in which the UI shows the groups by type.
TYPE_ORDER = ("router", "server", "pc", "phone", "media", "audio", "iot", "printer", "generic")


# Climate, appliances, energy, security, openings and water are smart home devices: a single
# group ("iot"); the precise type stays in the icon (data/device_kinds.json).
_MERGED_GROUPS = {"climate": "iot", "appliance": "iot", "energy": "iot", "security": "iot", "cover": "iot", "water": "iot"}


_TOKEN_RE = re.compile(r"[a-z0-9]+")


_PORT_RE = re.compile(r"^\s*(\d+)")


# Generic keyword rules per group (data/type_words.json): "subs" = substrings (long words),
# "toks" = whole words (the short ones, so they do not fire inside other words).
# The ports are in ha_type_evidence._PORT_TYPE. The analyzed text is name + brand + info
# collected by the scans + port labels: no special case
# for a single device.
@lru_cache(maxsize=1)
def rules() -> dict:
    """The keyword rules by group, in the order of the file (none when the file cannot be read: told once in the log)."""
    groups = datafile.read(datafile.DATA_DIR / "type_words.json", "groups", what="Table of type words", default={})
    return {group: {"subs": tuple(r["subs"]), "toks": set(r["toks"])} for group, r in groups.items()}


_PC_PORTS = {3389, 445, 139}


def _blob(device: dict) -> tuple[str, set[str], set[int]]:
    """Text (lowercase), set of words and port numbers of the device."""
    labels, ports = _blob_port_labels(device)
    parts = _blob_name_parts(device) + _blob_extra_texts(device) + labels
    text = " ".join(str(p) for p in parts if p).lower()
    return text, set(_TOKEN_RE.findall(text)), ports


def _blob_name_parts(device: dict) -> list:
    """Name, brand and vendor of the device. A name built by the app ("Apple phone") is not a clue: the app would just be agreeing with itself."""
    return [None if device.get("name_generated") else device.get("name"), device.get("brand"), device.get("vendor")]


# Extra fields made of opaque identifiers, not of prose: the declared mDNS services (RFC 6763, section 7: "some unique opaque Service Name"). They are compared whole with the tables of
# declared services (type_evidence, data/device_kinds.json "mdns"), never cut into words: read as text the same fact counted twice and a piece of a maker's compound name became a function.
_OPAQUE_EXTRAS = frozenset({"mdns_services"})


def _blob_extra_texts(device: dict) -> list:
    """Text values of the extra fields that say something about the device itself.
    The operating system ("Linux 4.14", "Windows 10") is not a role: it runs on phones, TVs,
    routers, cameras and servers. It counts as a weak clue, separately (see type_scores).
    What Home Assistant says about the device (ha_*: area, model, integration) is not what the device says about itself: the
    integrations are counted apart, by their own table. ("mikrotik_router" as a word made every device tracked by it a router.)"""
    return [v for k, v in (device.get("extra") or {}).items() if isinstance(v, str) and (not k.startswith("ha_") or k == "ha_model") and k not in _OPAQUE_EXTRAS]


def _blob_port_labels(device: dict) -> tuple[list, set[int]]:
    """Labels of the scanned ports (in order, empty ones included) and the port numbers that start those labels."""
    labels: list = []
    ports: set[int] = set()
    for p in device.get("scanned_ports") or []:
        label = p.get("label") or ""
        labels.append(label)
        m = _PORT_RE.match(label)
        if m:
            ports.add(int(m.group(1)))
    return labels, ports


# Words that mean the product only in the declared model: "camera" is also the room in Italian (a device called "Camera da letto"),
# but in a model ("lumi.camera.acn007", "C200 Camera") it is the product.
_MODEL_WORDS = {"media": {"camera", "cameras"}}


def _model_text(device: dict) -> tuple[str, set[str]]:
    """The model that the device declares about itself (mDNS, UPnP, its own interface) or that Home Assistant knows: it is the name
    of the product, so a word in it ("camera", "speaker", "router") says what the product is."""
    parts = [v for k, v in (device.get("extra") or {}).items() if isinstance(v, str) and (k == "model" or k.endswith("_model"))]
    text = " ".join(parts).lower()
    return text, set(_TOKEN_RE.findall(text))


def _word_pts(base: int, subs, toks, model: tuple[str, set[str]]) -> int:
    """A word that is in the declared model counts as a declaration (W_DECLARED); anywhere else in the text it counts base."""
    text, tokens = model
    return max(base, W_DECLARED) if (any(x in text for x in subs) or tokens & toks) else base


# ---- score-based category --------------------------------------------------
# Each clue gives points to one or more categories, with a weight that depends on how
# reliable it is; the category with the most points wins (on a tie, TYPE_ORDER order),
# below MIN_TYPE_SCORE the device stays "generic". No rule for a brand:
# what counts are network roles, declared protocols, verified services, ports and words.
W_ROLE, W_DECLARED, W_SERVICE, W_PORT_GUESS, W_WORD, W_BRAND = 10, 8, 4, 1, 2, 3
