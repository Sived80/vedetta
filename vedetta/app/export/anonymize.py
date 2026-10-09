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

from ..recognition import brands

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
_HOME_DOT = re.compile(r"(?<![\d.])(?:192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?!\d|\.\d)")   # same edges as _IPV4: what the masking would have masked
_MAC = re.compile(r"(?<![0-9A-Za-z])(?<![^0-9A-Za-z][0-9A-Fa-f]{2}[:\-])(?<!^[0-9A-Fa-f]{2}[:\-])([0-9A-Fa-f]{2})([:\-])(?:[0-9A-Fa-f]{2}\2){4}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])(?!\2[0-9A-Fa-f]{2}\2[0-9A-Fa-f]{2})")


# IPv6: a global, unique-local or link-local address (the last one carries the MAC) names a home as much as an IPv4 one
_IPV6 = re.compile(r"(?<![0-9A-Za-z:.-])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![0-9A-Za-z:])")
_V6_PLACEHOLDER = "2001:db8::"     # the documentation range: it can never be a real address
# Domain names (a family name, a dynamic-DNS name, "nas.home.example.com"): only with an ending that is really one, so that "dashboard.log"
# or "app.state" are not names; the public infrastructure that says nothing about a home stays readable.
_TLDS = ("com|org|net|io|it|de|fr|es|uk|cz|sk|pl|nl|be|ch|at|eu|info|biz|dev|app|cloud|online|xyz|ru|us|me|tv|cc|co|ai|link|site|pro|top|"
         "local|lan|home|localdomain|internal|box|arpa")
_DOMAIN = re.compile(r"(?<![\w.@-])(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+(?:%s)(?![\w-])" % _TLDS, re.I)
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


_WELL_KNOWN = {"1.1.1.1", "1.0.0.1", "8.8.8.8", "8.8.4.4", "9.9.9.9", "149.112.112.112", "208.67.222.222", "208.67.220.220",
               "94.140.14.14", "94.140.15.15", "255.255.255.255"}
_VERSION_WORD = re.compile(r"(?i)(?<![a-z])(version|versione|firmware|fw|build|release|ver|v)\W{0,3}$")      # a whole word: not the end of "Server" or "DISCOVER"


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
        self._dns: dict[str, int] = {}       # domain name (lower) -> number
        self._v6: dict[str, int] = {}        # IPv6 address (compressed) -> number
        self._name_re: re.Pattern | None = None

    # ------------------------------------------------------------------ collection
    def add_public_ip(self, ip: str | None) -> None:
        if ip and _ip_ok(ip) and not ipaddress.ip_address(ip).is_private and ip not in _WELL_KNOWN:
            self._public_known.add(ip)
            self._public_ip(ip)                      # the number is given now, so the user's own address comes first

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

    def add_devices(self, devices: list[tuple]) -> None:
        """Several devices at once: [(aliases, hint, brand, icon), ...]. A name that two or more devices have in common (the
        service name an app announces from every phone, "Apple mobile") says nothing about who is who, so it never joins them
        into one placeholder: each device keeps its own, and the shared name gets a label of its own."""
        count: dict[str, int] = {}
        for aliases, *_ in devices:
            for key in {_norm(str(a or "")) for a in aliases if a}:
                count[key] = count.get(key, 0) + 1
        shared: list[tuple] = []
        for aliases, hint, brand, icon in devices:
            own = [a for a in aliases if a and count.get(_norm(str(a)), 0) < 2]
            self.add_device(own, hint, brand, icon)
            shared += [(a, hint, brand, icon) for a in aliases if a and count.get(_norm(str(a)), 0) >= 2]
        for a, hint, brand, icon in shared:
            self.add_device([a], hint, brand, icon)

    def text_note(self, note: str | None) -> str | None:
        """Free text written by the person (a note in the report): a single word of a known device name ("Giulia" in
        "Giulia's iPad") is masked as the placeholder of that device. Product and brand words stay. Addresses and the rest are
        left to text(), which the export applies to the whole file afterwards (masking twice would turn 10.0.0.x into 10.1.0.x)."""
        if not note:
            return note
        out = note
        words: dict[str, str] = {}
        for key, label in {**self._names, **self._areas}.items():
            for w in key.split("-"):
                if len(w) >= 4 and w.isalpha() and w not in _NEVER and w not in _brand_keys() and not any(rx.search(w) for _, rx in _PRODUCTS):
                    words.setdefault(w, label)
        if words:
            rx = re.compile(r"(?<![0-9A-Za-z])(" + "|".join(sorted(map(re.escape, words), key=len, reverse=True)) + r")(?![0-9A-Za-z])", re.I)
            out = rx.sub(lambda m: words[m.group(1).lower()], out)
        return out

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

    def _public_ip(self, ip: str) -> str:
        n = self._pub.setdefault(ip, len(self._pub) + 1) - 1
        return f"203.0.{113 + n // 254}.{n % 254 + 1}"      # documentation range: it can never be a real address

    def _ip(self, m: re.Match) -> str:
        ip = m.group(0)
        if any(int(g) > 255 for g in m.groups()) or not _ip_ok(ip):
            return ip
        if ipaddress.ip_address(ip).is_private:
            return self._private_ip(ip)
        if ip in _WELL_KNOWN or _VERSION_WORD.search(m.string[max(0, m.start() - 14):m.start()]):
            return ip                                # a public DNS, or a version number written like an address
        if not ipaddress.ip_address(ip).is_global:
            return self._private_ip(ip)              # CGNAT, reserved ranges: part of somebody's network
        return self._public_ip(ip)

    def _ip_sep(self, m: re.Match) -> str:
        """192-168-1-5 -> 10-0-0-5, for the networks that exist here and for any 192.168.* / 172.16-31.* (so a date such as
        "10-06-12-30" is safe, and nothing the check below looks for is left)."""
        a, sep, b, c, d = m.groups()
        known = ".".join((a, b, c)) in self._nets
        home = (int(a) == 192 and int(b) == 168) or (int(a) == 172 and 16 <= int(b) <= 31)
        if not (known or home) or int(c) > 255 or int(d) > 255:
            return m.group(0)
        return self._private_ip(f"{a}.{b}.{c}.{d}").replace(".", sep)

    def _email(self, m: re.Match) -> str:
        key = m.group(0).lower()
        return f"email-{self._emails.setdefault(key, len(self._emails) + 1)}@masked.invalid" if not key.endswith("@masked.invalid") else m.group(0)

    def _dns_sub(self, m: re.Match) -> str:
        name = m.group(0)
        if _public_domain(name):
            return name
        return f"host-{self._dns.setdefault(name.lower(), len(self._dns) + 1)}.masked.invalid"

    def _v6_sub(self, m: re.Match) -> str:
        raw = m.group(0)
        if not _v6_ok(raw):
            return raw
        key = str(ipaddress.IPv6Address(raw))
        return f"{_V6_PLACEHOLDER}{self._v6.setdefault(key, len(self._v6) + 1):x}"

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
        s = _IPV6.sub(self._v6_sub, s)
        s = _DOMAIN.sub(self._dns_sub, s)
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

    def leak_items(self, text: str) -> list[tuple[str, str]]:
        """What is still readable in already masked text: [(kind, value)], the value being the real thing found. Empty list =
        clean. The values are for the person who is exporting (shown in the window, never written to a log or to the file)."""
        found: list[tuple[str, str]] = []

        def add(kind: str, value: str) -> None:
            if value and (kind, value) not in found:
                found.append((kind, value))
        low = text.lower()
        for m in _HOME_DOT.finditer(text):
            add("home network address", m.group(0))
        for m in _IPV4_SEP.finditer(text):
            a, _sep, b, c, d = m.groups()
            if ((int(a) == 192 and int(b) == 168) or (int(a) == 172 and 16 <= int(b) <= 31)) and int(c) <= 255 and int(d) <= 255:
                add("home network address", m.group(0))
        for ip in self._public_known:
            if ip in text:
                add("public address", ip)
        for m in _IPV4.finditer(text):
            ip = m.group(0)
            # exactly the addresses _ip() masks as public: not multicast / loopback / broadcast (_ip_ok), not a well known DNS,
            # not written after "version", and not our own placeholders
            if all(int(g) <= 255 for g in m.groups()) and _ip_ok(ip) and ip not in _WELL_KNOWN and not ip.startswith("203.0."):
                if ipaddress.ip_address(ip).is_global and not _VERSION_WORD.search(text[max(0, m.start() - 14):m.start()]):
                    add("public address", ip)
        if self._macs and self._mac_re(low) is not None:
            for m in self._mac_rx.finditer(low):
                add("MAC address", text[m.start():m.end()])
        for m in _EMAIL.finditer(text):
            if not m.group(0).endswith("@masked.invalid"):
                add("email address", m.group(0))
        for m in _IPV6.finditer(text):
            if _v6_ok(m.group(0)):
                add("IPv6 address", m.group(0))
        for m in _DOMAIN.finditer(text):
            if not _public_domain(m.group(0)):
                add("domain name", m.group(0))
        for m in _SECRET_PAIR.finditer(text):
            if m.group(3) != "***":
                add("password or token", m.group(3))
        for m in re.finditer(r"://([^/\s:@*]+:[^/\s@*]+)@", text):
            add("password or token", m.group(1))
        table = {**self._areas, **self._names}
        if table:
            rest = text
            for label in sorted(set(table.values()), key=len, reverse=True):
                rest = rest.replace(label, " ")
            for m in self._compile_for(table).finditer(rest):
                add("name", m.group(0))
        return found

    def leaks(self, text: str) -> list[str]:
        """What is still readable in already masked text (kinds only, never the values). Empty list = clean."""
        return sorted({kind for kind, _ in self.leak_items(text)})

    def fix_value(self, kind: str, value: str) -> str | None:
        """What a value found by leak_items() is replaced with, or None when it cannot be done safely (the person decides)."""
        if kind == "password or token":
            return "***"
        fixed = self.text(value)
        return fixed if fixed != value and not self.leak_items(fixed) else None

    def repair(self, text: str) -> tuple[str, int, list[tuple[str, str]]]:
        """Replaces what leak_items() finds by the same placeholders text() uses. Returns (text, how many values were replaced,
        what is still readable and could not be replaced)."""
        fixed = 0
        for kind, value in sorted(self.leak_items(text), key=lambda it: -len(it[1])):
            replacement = self.fix_value(kind, value)
            if replacement is not None and value in text:
                text = text.replace(value, replacement)
                fixed += 1
        return text, fixed, self.leak_items(text)

    def repair_data(self, obj, key: str = "", path: str = ""):
        """repair() over parsed JSON, skipping the fields that describe the device (kept on purpose).
        Returns (object, replaced, [(kind, value, where)])."""
        if isinstance(obj, dict):
            out, fixed, left = {}, 0, []
            for k, v in obj.items():
                k2 = k
                if isinstance(k, str):
                    k2, f, rest = self.repair(k)
                    fixed += f
                    left += [(kind, val, path or "/") for kind, val in rest]
                v2, f, rest = self.repair_data(v, k if isinstance(k, str) else "", f"{path}/{k}")
                out[k2] = v2
                fixed += f
                left += rest
            return out, fixed, left
        if isinstance(obj, list):
            out, fixed, left = [], 0, []
            for i, v in enumerate(obj):
                v2, f, rest = self.repair_data(v, key, f"{path}/{i}")
                out.append(v2)
                fixed += f
                left += rest
            return out, fixed, left
        if isinstance(obj, str) and key not in _KEEP and obj != "***":
            text, fixed, rest = self.repair(obj)
            return text, fixed, [(kind, val, path) for kind, val in rest]
        return obj, 0, []

    @staticmethod
    def _home_sep_left(text: str) -> bool:
        """A 192.168.* or 172.16-31.* written with dashes or underscores that _ip_sep() would have masked."""
        for m in _IPV4_SEP.finditer(text):
            a, _sep, b, c, d = m.groups()
            if ((int(a) == 192 and int(b) == 168) or (int(a) == 172 and 16 <= int(b) <= 31)) and int(c) <= 255 and int(d) <= 255:
                return True
        return False

    def _mac_re(self, low: str):
        """A real MAC in the text, written like text() would have masked it (whole, not part of a longer run of hex digits)."""
        if getattr(self, "_mac_forms", None) != len(self._macs):
            self._mac_forms = len(self._macs)
            chain = [m for mac in self._macs for m in (mac, mac.replace(":", "-"))]
            flat = [mac.replace(":", "") for mac in self._macs]
            self._mac_rx = re.compile(
                r"(?<![0-9a-z])(?<![^0-9a-z][0-9a-f]{2}[:\-])(?<!^[0-9a-f]{2}[:\-])(?:" + "|".join(re.escape(f) for f in chain) + r")(?![0-9a-f])(?![:\-][0-9a-f]{2}[:\-][0-9a-f]{2})"
                + r"|(?<![0-9a-f])(?:" + "|".join(re.escape(f) for f in flat) + r")(?![0-9a-f])")
        return self._mac_rx.search(low)

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
                "public_ips": {self._public_ip(ip): ip for ip in self._pub},
                "macs": {v: k for k, v in self._macs.items()},
                "domain_names": {f"host-{i}.masked.invalid": d for d, i in self._dns.items()},
                "ipv6": {f"{_V6_PLACEHOLDER}{i:x}": a for a, i in self._v6.items()},
                "names": {v: sorted(k for k, x in {**self._names, **self._areas}.items() if x == v)
                          for v in sorted(set(self._names.values()) | set(self._areas.values()))}}
