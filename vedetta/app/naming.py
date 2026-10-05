"""Device names. Principles shared with the other projects (NetAlertX, Home
Assistant, Pi-hole): each source proposes a name, useless names are discarded, among
the remaining ones the most reliable source wins, a hand-chosen name is never
touched and, if nothing is found, the IP address remains.

The name is saved together with its source ("name_source"): "user" = chosen by the user
(never overwritten); the others are automatic sources, and a later scan
may replace the name only with one from a more reliable source."""
import re

# Higher = more reliable. "adapter": name given by the device itself via its
# open API (Shelly); "mdns": name published by the device (service with a
# user-chosen name or .local hostname); "upnp": friendlyName; "dhcp":
# hostname announced to the router; "netbios": Windows/Samba name; "nmap": reverse DNS.
# "onvif": name declared via ONVIF (often generic, e.g. "IPCAM"), hence last.
# "tls": host name in the device's certificate (local network names only, see cn_host).
# "weak": system placeholder name ("Android_MGDZ1OUL"): better than the IP, worse than any other.
PRIORITY = {"adapter": 90, "mdns": 70, "upnp": 65, "dhcp": 55, "netbios": 45, "nmap": 40, "tls": 38, "onvif": 35, "web": 30,
            "ha": 68, "ha_user": 95, "weak": 20}

# Generic platform word + random code: a system's default hostname, not the device's name.
_PLACEHOLDER_RE = re.compile(r"^(android|iphone|ipad|galaxy|tablet|phone|device|esp|espressif|wlan|wifi|smart|unknown)[-_ ]?"
                             r"(?=[0-9a-z]*\d)[0-9a-z]{5,}$", re.IGNORECASE)

_LOCAL_CN = (".local", ".lan", ".home", ".fritz.box", ".localdomain", ".internal", ".home.arpa", ".homenet")


# Page titles that are not a name (login screens, errors, welcome pages).
_GENERIC_TITLES = {"login", "log in", "sign in", "signin", "welcome", "index", "home", "default", "error", "dashboard",
                   "admin", "web interface", "webui", "web ui", "authentication", "authorization required", "status",
                   "configuration", "setup", "main menu", "untitled", "document", "page", "it works", "test page"}
_TITLE_NOISE = re.compile(r"not found|forbidden|unauthori[sz]ed|bad request|welcome to|index of|^\d{3}\b|error|default web|apache|nginx",
                          re.IGNORECASE)
_TITLE_SUFFIX = re.compile(r"\s+(main menu|configuration|web ?(ui|interface|gui)|login|home|index|status|setup)$", re.IGNORECASE)


_GENERIC_FIRST = {"login", "log", "sign", "signin", "welcome", "error", "index", "unauthorized", "forbidden", "requested", "authentication"}


def title_name(title: str | None) -> str | None:
    """Name from the title of the device's web page ("Termostato - Main Menu" ->
    "Termostato", "pve - Proxmox Virtual Environment" -> "pve"). None for generic titles
    ("Login", "404 Not Found"): the title is a weak source, valid only if it looks like a name."""
    if not title:
        return None
    text = " ".join(str(title).split())
    from .formatters import is_useless_title, should_show_title  # late import: formatters imports i18n
    if is_useless_title(text) or not should_show_title(text):
        return None  # nmap placeholder ("Site doesn't have a title"), login, HTTP errors
    cand = re.split(r"\s+[-|–—:]\s+|\s*\|\s*", text)[0].strip()
    cand = _TITLE_SUFFIX.sub("", cand).strip()
    if re.search(r"\bv?\d+(\.\d+){1,3}$", cand):
        return None   # "software 1.47.45": the title of a program, not the appliance's name
    if not cand or len(cand) > 40 or cand.lower() in _GENERIC_TITLES or _TITLE_NOISE.search(cand):
        return None
    # A path ("/login.html") or a phrase that starts with a generic word
    # ("Login Requested resource...") is a screen, not a name.
    first = re.split(r"[\s_]+", cand.lower())[0]
    if "/" in cand or first in _GENERIC_TITLES or first in _GENERIC_FIRST:
        return None
    return cand


def cn_host(subject: str | None) -> str | None:
    """Host name from a certificate's subject ("commonName=pve.local/O=..."), only if
    it is a local network name (a single word or with a .local/.lan/... suffix): an
    internet domain (tplinkwifi.net) or a wildcard certificate (*.example.com) is not the
    device's name."""
    m = re.search(r"commonName=([^/,]+)", subject or "")
    if not m:
        return None
    cn = m.group(1).strip().lower()
    if not cn or cn.startswith("*") or _IP_RE.match(cn):
        return None
    if "." in cn and not cn.endswith(_LOCAL_CN):
        return None
    return cn

_DOMAIN_SUFFIXES = (".local", ".lan", ".home", ".fritz.box", ".localdomain", ".internal", ".home.arpa", ".homenet")
_ESCAPE_RE = re.compile(r"\\(\d{3}|.)")
_IP_RE = re.compile(r"^(ip[-_ ]?)?\d{1,3}([.\-_]\d{1,3}){3}$", re.IGNORECASE)
_MAC_RE = re.compile(r"^([0-9a-f]{2}[:\-]?){5}[0-9a-f]{2}$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[^0-9A-Za-z]+")
_GENERIC = {"localhost", "unknown", "unnamed", "default", "device", "host", "none", "null", "n/a", "-", "*"}


def _unescape(text: str) -> str:
    """DNS-SD escape sequences: \\032 = space (decimal), \\. = dot."""
    def repl(m: re.Match) -> str:
        g = m.group(1)
        return chr(int(g)) if g.isdigit() and len(g) == 3 else g
    return _ESCAPE_RE.sub(repl, text)


def _looks_generated(token: str) -> bool:
    """Part of a name that looks like a generated code (long hexadecimal): id, hash,
    random suffixes. A short number ("14", "S23") is not one."""
    if not re.fullmatch(r"[0-9a-fA-F]+", token) or len(token) < 8:
        return False
    has_digit = any(c.isdigit() for c in token)
    has_letter = any(c.isalpha() for c in token)
    return len(token) >= 12 or (has_digit and has_letter)


def clean_name(raw: str | None) -> str | None:
    """Normalized name, or None if it is not a usable name."""
    if not raw:
        return None
    name = " ".join(_unescape(str(raw)).split())
    # An IP inside the name ("AFTMM@ES(192.168.1.5)") is not part of the name: it is removed.
    name = re.sub(r"[(\[]?\b\d{1,3}(?:\.\d{1,3}){3}\b[)\]]?", "", name).strip(" -_@:,")
    # "<id>@<name>" (AirPlay/Whisperplay service instance): only the part after the at sign counts,
    # and only if it is long enough to be a name ("ES" is not).
    if "@" in name:
        name = name.split("@", 1)[1].strip(" -_@:,")
        if len(name) < 4:
            return None
    low = name.lower()
    for suffix in _DOMAIN_SUFFIXES:
        if low.endswith(suffix):
            name, low = name[: -len(suffix)], low[: -len(suffix)]
    low = name.lower()
    if low.startswith("_") or "._tcp" in low or "._udp" in low or low.endswith(".arpa"):
        return None  # a DNS-SD service type, not a name
    # The generated code must be looked for before cutting off the domain, otherwise
    # "amzn.dmgr.05837F86..." would be reduced to an apparently valid "amzn".
    if any(_looks_generated(t) for t in _TOKEN_RE.split(name) if t):
        return None
    if " " not in name and "." in name and not _IP_RE.match(name):
        name = name.split(".", 1)[0]  # fully qualified domain name: only the host counts
    name = name.strip(" ._-")
    low = name.lower()
    if not name or low in _GENERIC or low.startswith("("):
        return None
    if _IP_RE.match(name) or _MAC_RE.match(name):
        return None
    return name


def pick(candidates: list[tuple[str, str | None]]) -> tuple[str | None, str | None]:
    """Best (name, source) among the candidates [(source, raw_name)], or (None, None)."""
    best: tuple[int, str, str] | None = None
    for source, raw in candidates:
        name = clean_name(raw)
        if not name:
            continue
        if is_placeholder(name):
            source = "weak"
        rank = PRIORITY.get(source, 0)
        if best is None or rank > best[0]:
            best = (rank, name, source)
    return (best[1], best[2]) if best else (None, None)


# Technical name generated by an integration ("shelly1-8CAAB50000A2", "plug_4A3F21"): abbreviation + hexadecimal code.
_TECHNICAL_RE = re.compile(r"^[a-z][a-z0-9]*[-_][0-9a-f]{6,12}$", re.IGNORECASE)
_PLATFORM_WORDS = {"android", "iphone", "ipad", "ipod", "tablet", "phone", "device", "smartphone"}


def is_placeholder(name: str | None) -> bool:
    """Default system name: a bare platform word ("Android", "iPhone") or one with a
    random code ("Android_MGDZ1OUL"). It is not a chosen name: it yields to any other."""
    if not name:
        return False
    # Also a saved name that would not pass cleaning today (e.g. a service instance "ABC@ES").
    return name.strip().lower() in _PLATFORM_WORDS or bool(_PLACEHOLDER_RE.match(name)) or bool(_TECHNICAL_RE.match(name.strip())) or (clean_name(name) is None and not _IP_RE.match(name.strip()))


def is_better(device: dict, new_source: str) -> bool:
    """True if an automatic name from the given source may replace the device's
    one: never over a user-chosen name (or one whose origin is unknown
    and which differs from the IP), yes if the name is still the IP or comes from
    a less reliable source."""
    name = device.get("name")
    if not name or name == device.get("ip"):
        return True
    source = device.get("name_source")
    if source == "user" or (source not in PRIORITY and not is_placeholder(name)):
        return False  # chosen by hand, or a previous name without origin: presumed chosen by hand
    if is_placeholder(name):
        source = "weak"  # saved as "mdns" before placeholders were given little weight
    return PRIORITY[new_source] > PRIORITY[source]
