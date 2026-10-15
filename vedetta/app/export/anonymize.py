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

from .anonymize_patterns import _DOMAIN, _EMAIL, _HOME_DOT, _IPV4, _IPV4_SEP, _IPV6, _KEEP, _MAC, _NEVER, _PRIVATE_KEYS, products, _PUBLIC_DOMAINS, _SECRET_KEY, _SECRET_PAIR, _TLDS, _URL_CREDS, _V6_PLACEHOLDER, _VERSION_WORD, _WELL_KNOWN, _WORD, _brand_keys, _ip_ok, _norm, _pattern, _public_domain, _v6_ok  # noqa: F401
from .anonymize_audit import AuditMixin
from .anonymize_registry import Registry


class Anonymizer(Registry, AuditMixin):
    # ------------------------------------------------------------------ notes
    def text_note(self, note: str | None) -> str | None:
        """Free text written by the person (a note in the report): a single word of a known device name ("Giulia" in
        "Giulia's iPad") is masked as the placeholder of that device. Product and brand words stay. Addresses and the rest are
        left to text(), which the export applies to the whole file afterwards (masking twice would turn 10.0.0.x into 10.1.0.x)."""
        if not note:
            return note
        words = self._note_words()
        if not words:
            return note
        rx = re.compile(r"(?<![0-9A-Za-z])(" + "|".join(sorted(map(re.escape, words), key=len, reverse=True)) + r")(?![0-9A-Za-z])", re.IGNORECASE)
        return rx.sub(lambda m: words[m.group(1).lower()], note)

    def _note_words(self) -> dict[str, str]:
        """Word -> placeholder, for each single word of a registered name or area (the first one found wins)."""
        words: dict[str, str] = {}
        for key, label in {**self._names, **self._areas}.items():
            for w in key.split("-"):
                if self._is_personal_word(w):
                    words.setdefault(w, label)
        return words

    @staticmethod
    def _is_personal_word(w: str) -> bool:
        """A word of a name that can be a person or a place: long enough, only letters, and neither a product nor a brand."""
        return len(w) >= 4 and w.isalpha() and w not in _NEVER and w not in _brand_keys() and not any(rx.search(w) for _, rx in products())

    # ------------------------------------------------------------------ replacement

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
        return re.compile("|".join(_pattern(k.replace("-", " ")) for k in sorted(table, key=len, reverse=True)), re.IGNORECASE | re.UNICODE)

    def text(self, s: str) -> str:
        if not s:
            return s
        for flat, fake in self._literal.items():
            if flat in s.lower():
                s = re.sub(r"(?<![0-9A-Fa-f])" + flat + r"(?![0-9A-Fa-f])", fake, s, flags=re.IGNORECASE)
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
            return {self._data_key(k): self.data(v, k if isinstance(k, str) else "") for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.data(v, key) for v in obj]
        if isinstance(obj, str):
            return self._data_value(obj, key)
        return obj

    def _data_key(self, k):
        return self.text(k) if isinstance(k, str) else k

    def _data_value(self, value: str, key: str) -> str:
        """A text value: hidden when its field is a secret or a private one, left alone when the field describes the device."""
        if value and (_SECRET_KEY.search(key) or key in _PRIVATE_KEYS):
            return "***"
        return value if key in _KEEP else self.text(value)

    def _compile_for(self, table: dict) -> re.Pattern:
        if getattr(self, "_leak_re", None) is None or self._leak_re[0] != len(table):
            self._leak_re = (len(table), re.compile("|".join(_pattern(k.replace("-", " ")) for k in sorted(table, key=len, reverse=True)), re.IGNORECASE | re.UNICODE))
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
