"""Anonymisation of the export for analysis: only the copy inside the zip changes, never the live data.

Every sensitive value becomes the same placeholder everywhere in the file (JSON, log, database), so the
relations stay readable and the values do not:
  - private IP   -> 10.<network>.0.<same last number>  (the first network found is 10.0.0.x)
  - public IP    -> 203.0.113.<n>
  - MAC          -> same manufacturer prefix + a counter (the prefix is needed to judge the brand)
  - device names (own name, DHCP hostname, Bonjour name, name in Home Assistant) -> iPhone-1, TV-2, ...
  - areas of Home Assistant -> Area-1
Ports, times, scores, clues, brand, model and versions are left as they are."""
import ipaddress
import re

from . import brands

# JSON fields that describe the device or a fingerprint, not a person: never rewritten (an icon called like an area, an SSH
# fingerprint that looks like a MAC...). IPs and MACs used as KEYS are still replaced.
_KEEP = {"icon", "type", "type_user", "adapter", "logo", "logo_color", "brand", "brand_source", "brand_confidence", "vendor",
         "vendor_role", "name_source", "family", "category", "kind", "ssh_hostkey", "http_server",
         "manufacturer", "model", "mdns_model", "mdns_manufacturer", "sw_version", "domains"}

# Product word found in a name -> label. The first rule that matches wins.
_PRODUCTS = (
    ("iPhone", r"iphone"), ("iPad", r"ipad"), ("MacBook", r"macbook"), ("iMac", r"imac"), ("AppleWatch", r"apple[\W_]*watch"),
    ("AppleTV", r"apple[\W_]*tv"), ("HomePod", r"homepod"), ("Mac", r"(?<!\w)mac(?!\w)"),
    ("Chromecast", r"chromecast"), ("Echo", r"(?<!\w)echo"), ("Alexa", r"alexa"), ("Nest", r"(?<!\w)nest"),
    ("PlayStation", r"playstation|(?<!\w)ps[2345](?!\w)"), ("Xbox", r"xbox"), ("Switch", r"nintendo"),
    ("Shelly", r"shelly"), ("Tasmota", r"tasmota"), ("ESP", r"(?<!\w)esp[\W_]*\d*[\W_]?[0-9a-f]*"),
    ("Galaxy", r"galaxy"), ("Pixel", r"pixel"), ("Android", r"android"), ("Phone", r"phone|cellulare|telefono"),
    ("TV", r"(?<!\w)tv(?!\w)|television|televisore"), ("Printer", r"printer|stampante"),
    ("Camera", r"camera|(?<!\w)cam(?!\w)"), ("Router", r"router|gateway|fritz"), ("NAS", r"(?<!\w)nas(?!\w)"),
    ("PC", r"(?<!\w)pc(?!\w)|desktop|laptop|notebook"), ("Raspberry", r"raspberry|(?<!\w)rpi"),
)
_PRODUCTS = tuple((label, re.compile(rx, re.I)) for label, rx in _PRODUCTS)
_TYPE_LABELS = {"router": "Router", "server": "Server", "pc": "PC", "phone": "Phone", "media": "Media", "audio": "Audio",
                "iot": "IoT", "printer": "Printer"}
_NEVER = {"unknown", "localhost", "homeassistant", "home assistant", "none", "null", "true", "false"}
_WORD = re.compile(r"[^\W_]+", re.U)   # letters and digits: "_" is a separator

_IPV4 = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?!\d|\.\d)")
# the same address written with dashes or underscores, as in the device ids ("scan-192-168-1-5")
_IPV4_SEP = re.compile(r"(?<![\d])(\d{1,3})([-_])(\d{1,3})\2(\d{1,3})\2(\d{1,3})(?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# "password=abc", "token": "abc", "Authorization: Bearer abc" -> the value is hidden
_SECRET_PAIR = re.compile(r"(?i)\b(pass(?:word|wd)?|token|secret|api[_-]?key|authorization)(\W{0,3}[:=]\W{0,2})(?:bearer\s+)?([^\s\"',;&<>]{4,})")
_URL_CREDS = re.compile(r"(://)[^/\s:@]+:[^/\s@]+@")
_SECRET_KEY = re.compile(r"pass|token|secret|api_?key|credential|authorization", re.I)
_PRIVATE_KEYS = {"user", "username", "mqtt_user", "mqtt_username", "mqtt_host"}
# whatever still looks like a real home network or a person after the masking: used to refuse the export
_REAL_NET = re.compile(r"(?<![\d])(?:192[.\-_]168|172[.\-_](?:1[6-9]|2\d|3[01]))[.\-_]\d{1,3}[.\-_]\d{1,3}(?![\d])")
_MAC = re.compile(r"(?<![0-9A-Fa-f:\-])([0-9A-Fa-f]{2})([:\-])(?:[0-9A-Fa-f]{2}\2){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])")


def _norm(text: str) -> str:
    return "-".join(w.lower() for w in _WORD.findall(text))


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


def _brand_in(brand: str, name: str) -> bool:
    """The brand is written in the name, with or without separators (NodeRED, node-red, Node RED)."""
    words = _WORD.findall(brand)
    return bool(words) and bool(re.search(r"(?<![^\W_])" + r"[\W_]*".join(re.escape(w) for w in words), name, re.I))


def _ip_ok(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_loopback or a.is_unspecified or a.is_multicast or ip == "255.255.255.255")


class Anonymizer:
    def __init__(self) -> None:
        self._nets: dict[str, int] = {}      # first three numbers -> network index
        self._pub: dict[str, int] = {}
        self._macs: dict[str, str] = {}      # real mac (lower, ":") -> placeholder (lower, ":")
        self._names: dict[str, str] = {}     # normalised name -> placeholder
        self._areas: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        self._literal: dict[str, str] = {}   # other forms of a mac: 12 hex, last 6 hex
        self._public_known: set[str] = set()
        self._emails: dict[str, str] = {}
        self._name_re: re.Pattern | None = None

    # ------------------------------------------------------------------ collection
    def add_public_ip(self, ip: str | None) -> None:
        if ip and _ip_ok(ip):
            self._public_known.add(ip)

    def add_ip(self, ip: str | None) -> None:
        if ip and _ip_ok(ip) and ipaddress.ip_address(ip).is_private:
            self._nets.setdefault(".".join(ip.split(".")[:3]), len(self._nets))

    def add_mac(self, mac: str | None) -> None:
        m = str(mac or "").strip().lower().replace("-", ":")
        if not re.fullmatch(r"(?:[0-9a-f]{2}:){5}[0-9a-f]{2}", m) or m in self._macs:
            return
        n = len(self._macs) + 1
        fake = m[:8] + ":" + ":".join(f"{n:06x}"[i:i + 2] for i in (0, 2, 4))
        self._macs[m] = fake
        flat, tail = m.replace(":", ""), m[9:].replace(":", "")
        self._literal[flat] = fake.replace(":", "")
        if re.search(r"[a-f]", tail):
            self._literal[tail] = fake[9:].replace(":", "")

    def add_names(self, names: list, brand: str | None = None, skip: tuple = ()) -> None:
        """Names that appear in the registries of the house (Home Assistant, Bonjour, DHCP) even if the device is not on the board."""
        keep = {_norm(s) for s in skip if s}
        self.add_device([n for n in names if _norm(str(n or "")) not in keep], None, brand)

    def add_area(self, name: str | None) -> None:
        if name and _norm(name) and _norm(name) not in self._areas:
            self._areas[_norm(name)] = f"Area-{len(self._areas) + 1}"
            self._name_re = None

    def add_device(self, aliases: list, hint: str | None = None, brand: str | None = None, icon: str | None = None) -> str | None:
        """All the names of one device share one placeholder. Returns it (None if there is nothing to hide)."""
        usable = []
        for alias in aliases:
            a = str(alias or "").strip()
            key = _norm(a)
            if len(key) < 3 or key in _NEVER or key.replace("-", "").isdigit() or _IPV4.fullmatch(a):
                continue
            if re.fullmatch(r"[a-z]{3}", key):                       # "pve", "nas", "tv": a short technical word, kept (a clue for the debug)
                continue
            if key in _brand_keys() or key == _norm(brand or ""):   # a bare brand name is not personal and the debug needs it
                continue
            usable.append((a, key))
        if not usable:
            return None
        existing = next((self._names[k] for _, k in usable if k in self._names), None)
        label = existing or self._new_label([a for a, _ in usable], hint, brand, icon)
        for _, key in usable:
            self._names.setdefault(key, label)
        self._name_re = None
        return label

    def _new_label(self, names: list[str], hint: str | None, brand: str | None = None, icon: str | None = None) -> str:
        # the brand written in the name stays visible: it is the clue the brand was recognised from
        base = re.sub(r"[^A-Za-z0-9]+", "", brand or "") if brand and any(_brand_in(brand, n) for n in names) else None
        base = base or next((label for label, rx in _PRODUCTS for n in names if rx.search(n)), None)
        # the kind of device (thermostat, gate, camera...) tells what the name was about
        kind = "".join(w.capitalize() for w in re.findall(r"[a-z0-9]+", icon or "")) if icon not in (None, "server", "help") else ""
        base = base or kind or _TYPE_LABELS.get(hint or "") or "Device"
        self._counts[base] = self._counts.get(base, 0) + 1
        return f"{base}-{self._counts[base]}"

    # ------------------------------------------------------------------ replacement
    def _private_ip(self, ip: str) -> str:
        parts = ip.split(".")
        idx = self._nets.setdefault(".".join(parts[:3]), len(self._nets))
        return f"10.{idx}.0.{int(parts[3])}"

    def _ip(self, m: re.Match) -> str:
        ip = m.group(0)
        if any(int(g) > 255 for g in m.groups()) or not _ip_ok(ip):
            return ip
        if ipaddress.ip_address(ip).is_private:
            return self._private_ip(ip)
        if ip in self._public_known:
            return f"203.0.113.{self._pub.setdefault(ip, len(self._pub) + 1)}"
        return ip                                    # other public numbers are mostly versions or well-known servers

    def _ip_sep(self, m: re.Match) -> str:
        """192-168-1-5 -> 10-0-0-5, only for the networks that really exist here (so "10-06-12-30" in a date is safe)."""
        a, sep, b, c, d = m.groups()
        if ".".join((a, b, c)) not in self._nets or int(d) > 255:
            return m.group(0)
        return self._private_ip(f"{a}.{b}.{c}.{d}").replace(".", sep)

    def _email(self, m: re.Match) -> str:
        key = m.group(0).lower()
        return f"email-{self._emails.setdefault(key, len(self._emails) + 1)}@masked.invalid" if not key.endswith("@masked.invalid") else m.group(0)

    def _mac(self, m: re.Match) -> str:
        raw = m.group(0)
        low = raw.lower().replace("-", ":")
        self.add_mac(low)
        fake = self._macs.get(low, low)
        fake = fake.replace(":", m.group(2))
        return fake.upper() if raw.upper() == raw and re.search(r"[A-F]", raw) else fake

    def _compile(self) -> re.Pattern | None:
        table = {**self._areas, **self._names}
        if not table:
            return None
        # the originals, longest first so "Anna's iPhone 2" wins over "Anna"
        return re.compile("|".join(_pattern(k.replace("-", " ")) for k in sorted(table, key=len, reverse=True)), re.I | re.U)

    def text(self, s: str) -> str:
        if not s:
            return s
        for flat, fake in self._literal.items():
            if flat in s.lower():
                s = re.sub(r"(?<![0-9A-Fa-f])" + flat + r"(?![0-9A-Fa-f])", fake, s, flags=re.I)
        s = _EMAIL.sub(self._email, s)
        s = _URL_CREDS.sub(r"\1***:***@", s)
        s = _SECRET_PAIR.sub(r"\1\2***", s)
        s = _MAC.sub(self._mac, s)
        s = _IPV4.sub(self._ip, s)
        s = _IPV4_SEP.sub(self._ip_sep, s)
        if self._name_re is None:
            self._name_re = self._compile()
        if self._name_re is not None:
            table = {**self._areas, **self._names}
            s = self._name_re.sub(lambda m: table.get(_norm(m.group(0)), m.group(0)), s)
        return s

    def data(self, obj, key: str = ""):
        """Same replacement over parsed JSON: the keys that describe the device are kept as they are."""
        if isinstance(obj, dict):
            return {self.text(k) if isinstance(k, str) else k: self.data(v, k if isinstance(k, str) else "") for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.data(v, key) for v in obj]
        if isinstance(obj, str) and obj and (_SECRET_KEY.search(key) or key in _PRIVATE_KEYS):
            return "***"
        if isinstance(obj, str) and key not in _KEEP:
            return self.text(obj)
        return obj

    def leaks(self, text: str) -> list[str]:
        """What is still readable in already masked text (kinds only, never the values). Empty list = clean."""
        found = set()
        low = text.lower()
        if _REAL_NET.search(text):
            found.add("home network address")
        if any(ip in text for ip in self._public_known):
            found.add("public address")
        for mac in self._macs:
            if mac in low or mac.replace(":", "-") in low or mac.replace(":", "") in low:
                found.add("MAC address")
                break
        if any(not m.group(0).endswith("@masked.invalid") for m in _EMAIL.finditer(text)):
            found.add("email address")
        if any(m.group(3) != "***" for m in _SECRET_PAIR.finditer(text)) or re.search(r"://[^/\s:@*]+:[^/\s@*]+@", text):
            found.add("password or token")
        table = {**self._areas, **self._names}
        if table:
            rest = text
            for label in sorted(set(table.values()), key=len, reverse=True):
                rest = rest.replace(label, " ")
            if self._compile_for(table).search(rest):
                found.add("name")
        return sorted(found)

    def leaks_data(self, obj, key: str = "") -> list[str]:
        """Same check over parsed JSON, skipping the fields that describe the device (kept on purpose)."""
        if isinstance(obj, dict):
            out = set(self.leaks(" ".join(str(k) for k in obj)))
            for k, v in obj.items():
                out |= set(self.leaks_data(v, k if isinstance(k, str) else ""))
            return sorted(out)
        if isinstance(obj, list):
            return sorted({x for v in obj for x in self.leaks_data(v, key)})
        if isinstance(obj, str) and key not in _KEEP and obj != "***":
            return self.leaks(obj)
        return []

    def _compile_for(self, table: dict) -> re.Pattern:
        if getattr(self, "_leak_re", None) is None or self._leak_re[0] != len(table):
            self._leak_re = (len(table), re.compile("|".join(_pattern(k.replace("-", " ")) for k in sorted(table, key=len, reverse=True)), re.I | re.U))
        return self._leak_re[1]

    def mapping(self) -> dict:
        """Placeholder -> original value: for the owner only, never put in the zip."""
        return {"emails": {f"email-{i}@masked.invalid": e for e, i in self._emails.items()},
                "ip_networks": {f"10.{i}.0.x": f"{net}.x" for net, i in self._nets.items()},
                "public_ips": {f"203.0.113.{i}": ip for ip, i in self._pub.items()},
                "macs": {v: k for k, v in self._macs.items()},
                "names": {v: sorted(k for k, x in {**self._names, **self._areas}.items() if x == v)
                          for v in sorted(set(self._names.values()) | set(self._areas.values()))}}
