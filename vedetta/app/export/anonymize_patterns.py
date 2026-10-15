"""anonymize_patterns: moved out of anonymize.py (see tools/split_module.py)."""
from functools import lru_cache

from .. import datafile
from ..recognition import brands
import ipaddress
import re


# JSON fields that describe the device or a fingerprint, not a person: never rewritten (an icon called like an area, an SSH
# fingerprint that looks like a MAC...). IPs and MACs used as KEYS are still replaced.
_KEEP = {"icon", "type", "type_user", "adapter", "logo", "logo_color", "brand", "brand_source", "brand_confidence", "vendor",
         "vendor_role", "name_source", "family", "category", "kind", "ssh_hostkey", "http_server",
         "manufacturer", "model", "mdns_model", "mdns_manufacturer", "sw_version", "domains",
         "state", "reasons", "badges", "scores", "chosen", "group", "corner", "thresholds",
         "version", "generated", "since", "age_s", "analysing_for_s"}


# Product word found in a name -> label (data/product_words.json). The first rule that matches wins.
@lru_cache(maxsize=1)
def products() -> tuple:
    """(label, pattern) of the product words that stay readable in the export; none when the file cannot be read (told once in the log): the names are masked all the same."""
    rows = datafile.read(datafile.DATA_DIR / "product_words.json", "products", what="Table of product words", default=[])
    return tuple((label, re.compile(rx, re.IGNORECASE)) for label, rx in rows)


_TYPE_LABELS = {"router": "Router", "server": "Server", "pc": "PC", "phone": "Phone", "media": "Media", "audio": "Audio",
                "iot": "IoT", "printer": "Printer"}


_NEVER = {"unknown", "localhost", "homeassistant", "home assistant", "none", "null", "true", "false"}
# The only SHORT words (two or three letters) that are technical and stay readable, a clue for the debug: any other short word may be a first name (Leo, Eva, Jo) and is masked.
_SHORT_TECH = frozenset({"tv", "pc", "ap", "pi", "pve", "nas", "cam", "rpi", "ups", "hub", "dns", "vpn", "nvr", "dvr", "plc", "iot", "lan", "wan", "dhcp", "ntp", "ssh",
                          "mac", "usb", "ssd", "hdd", "cpu", "gpu", "ram", "web", "api", "tcp", "udp", "arp", "led", "ota", "gps", "sim", "tls", "ssl", "rtc", "bms", "rgb", "ptz", "lte", "gsm", "sdk", "app", "bus", "log", "net"})


_WORD = re.compile(r"[^\W_]+", re.UNICODE)   # letters and digits: "_" is a separator


_IPV4 = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?!\d|\.\d)")


# the same address written with dashes or underscores, as in the device ids ("scan-192-168-1-5")
_IPV4_SEP = re.compile(r"(?<![\d])(\d{1,3})([-_])(\d{1,3})\2(\d{1,3})\2(\d{1,3})(?!\d)")


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


# "password=abc", "token": "abc", "Authorization: Bearer abc" -> the value is hidden
_SECRET_PAIR = re.compile(r"(?i)\b(pass(?:word|wd)?|token|secret|api[_-]?key|authorization)(\W{0,3}[:=]\W{0,2})(?:bearer\s+)?([^\s\"',;&<>]{4,})")


_URL_CREDS = re.compile(r"(://)[^/\s:@]+:[^/\s@]+@")


_SECRET_KEY = re.compile(r"pass|token|secret|api_?key|credential|authorization", re.IGNORECASE)


_PRIVATE_KEYS = {"user", "username", "mqtt_user", "mqtt_username", "mqtt_host"}


# whatever still looks like a real home network or a person after the masking: used to refuse the export
_HOME_DOT = re.compile(r"(?<![\d.])(?:192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?!\d|\.\d)")   # same edges as _IPV4: what the masking would have masked


_MAC = re.compile(r"(?<![0-9A-Za-z])(?<![^0-9A-Za-z][0-9A-Fa-f]{2}[:\-])(?<!^[0-9A-Fa-f]{2}[:\-])([0-9A-Fa-f]{2})([:\-])(?:[0-9A-Fa-f]{2}\2){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])(?!\2[0-9A-Fa-f]{2}\2[0-9A-Fa-f]{2})")


# IPv6: a global, unique-local or link-local address (the last one carries the MAC) names a home as much as an IPv4 one
_IPV6 = re.compile(r"(?<![0-9A-Za-z:.-])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Za-z:])")


_V6_PLACEHOLDER = "2001:db8::"     # the documentation range: it can never be a real address


# Domain names (a family name, a dynamic-DNS name, "nas.home.example.com"): only with an ending that is really one, so that "dashboard.log"
# or "app.state" are not names; the public infrastructure that says nothing about a home stays readable.
_TLDS = ("com|org|net|io|it|de|fr|es|uk|cz|sk|pl|nl|be|ch|at|eu|info|biz|dev|app|cloud|online|xyz|ru|us|me|tv|cc|co|ai|link|site|pro|top|"
         "local|lan|home|localdomain|internal|box|arpa|"
         # dynamic-DNS and country endings (the ones that are also file extensions, sh, so, py, js, md, rs, are left out on purpose)
         "nu|su|tk|ml|ga|cf|gq|in|jp|cn|br|ca|au|nz|se|no|dk|fi|pt|gr|ie|hu|ro|bg|hr|si|lt|lv|ee|tr|il|kr|za|mx|ar|cl|my|sg|th|vn|ph|ws|fm|ly|gl|im|"
         "ua|by|kz|hk|tw|ae|sa|ng|ke|eg|ma|dz|tn|lu|li|mt|cy|name|mobi|asia|tel|club|shop|store|blog|live|life|world|zone|network|systems|tech|digital")


_DOMAIN = re.compile(r"(?<![\w.@-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+(?:%s)(?![\w-])" % _TLDS, re.IGNORECASE)


_PUBLIC_DOMAINS = ("github.com", "githubusercontent.com", "ghcr.io", "home-assistant.io", "hassio.io", "cloudflare.com", "cloudflare-dns.com",
                   "google.com", "quad9.net", "ntp.org", "debian.org", "alpinelinux.org", "python.org", "pypi.org", "pythonhosted.org",
                   "docker.io", "docker.com", "mozilla.org", "microsoft.com", "apple.com", "opendns.com", "adguard.com", "adguard-dns.com")


def _public_domain(name: str) -> bool:
    low = name.lower()
    return any(low == d or low.endswith("." + d) for d in _PUBLIC_DOMAINS)


def _v6_ok(text: str) -> bool:
    """A real IPv6 address worth hiding: not "::", "::1" or a multicast group (ff02::c), not our own placeholder, and a valid one (a MAC or a time is not)."""
    try:
        a = ipaddress.IPv6Address(text)
    except ValueError:
        return False
    if "::" not in text and max(len(g) for g in text.split(":")) <= 2:
        return False                 # eight pairs of hex digits ("9b:e9:0b:ab:cd:ef:01:23") is a fingerprint, not an address
    return not (a.is_unspecified or a.is_loopback or a.is_multicast) and not text.lower().startswith(_V6_PLACEHOLDER)


def _pattern(text: str) -> str:
    """Matches the name whatever the separators ("Anna's iPhone", "Annas-iPhone", "anna_s_iphone")."""
    words = _WORD.findall(text)
    return r"(?<![^\W_])" + r"[\W_]{1,3}".join(re.escape(w) for w in words) + r"(?![^\W_])"


def _brand_keys() -> set:
    """Every brand and software name the app knows: they are not personal and the debug needs them as they are."""
    rules = brands._rules()
    names = {b for _, b in rules["aliases"]}
    for table in ("name_hints", "software_hints"):
        names |= {item[1] for item in rules[table] if isinstance(item, (tuple, list)) and len(item) > 1 and isinstance(item[1], str)}
    return {_norm(n) for n in names if _norm(n)}


def _norm(text: str) -> str:
    return "-".join(w.lower() for w in _WORD.findall(text))


def _brand_in(brand: str, name: str) -> bool:
    """The brand is written in the name, with or without separators (NodeRED, node-red, Node RED)."""
    words = _WORD.findall(brand)
    return bool(words) and bool(re.search(r"(?<![^\W_])" + r"[\W_]*".join(re.escape(w) for w in words), name, re.IGNORECASE))


_WELL_KNOWN = {"1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4", "9.9.9.9", "149.112.112.112", "208.67.222.222", "208.67.220.220",
               "94.140.14.14", "94.140.15.15", "255.255.255.255"}


_VERSION_WORD = re.compile(r"(?i)(?<![a-z])(version|versione|firmware|fw|build|release|ver|v)\W{0,3}$")      # a whole word: not the end of "Server" or "DISCOVER"


def _ip_ok(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_loopback or a.is_unspecified or a.is_multicast or ip == "255.255.255.255")
