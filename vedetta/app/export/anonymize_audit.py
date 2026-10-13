"""AuditMixin: methods of Anonymizer that belong together (moved out of anonymize.py by tools/split_class.py)."""
from .anonymize_patterns import _DOMAIN, _EMAIL, _HOME_DOT, _IPV4, _IPV4_SEP, _IPV6, _KEEP, _SECRET_PAIR, _VERSION_WORD, _WELL_KNOWN, _ip_ok, _public_domain, _v6_ok
from itertools import chain
import ipaddress
import re


class AuditMixin:
    def _leaks_addresses(self, text: str):
        """Private and public IPv4 addresses still readable, in the order they are looked for."""
        for m in _HOME_DOT.finditer(text):
            yield "home network address", m.group(0)
        for m in _IPV4_SEP.finditer(text):
            if self._home_sep_match(m):
                yield "home network address", m.group(0)
        for ip in self._public_known:
            if ip in text:
                yield "public address", ip
        for m in _IPV4.finditer(text):
            if self._public_leak(m, text):
                yield "public address", m.group(0)

    @staticmethod
    def _home_sep_match(m: re.Match) -> bool:
        """An address written with dashes or underscores in a home range (192.168.* or 172.16-31.*), the last two numbers valid."""
        a, _sep, b, c, d = m.groups()
        return AuditMixin._home_range(a, b) and int(c) <= 255 and int(d) <= 255

    @staticmethod
    def _home_range(a: str, b: str) -> bool:
        return (int(a) == 192 and int(b) == 168) or (int(a) == 172 and 16 <= int(b) <= 31)

    @staticmethod
    def _unmasked_candidate(m: re.Match) -> bool:
        """Exactly the addresses _ip() masks as public: valid numbers, not multicast / loopback / broadcast (_ip_ok), not a well known
        DNS, and not our own placeholders."""
        ip = m.group(0)
        return all(int(g) <= 255 for g in m.groups()) and _ip_ok(ip) and ip not in _WELL_KNOWN and not ip.startswith("203.0.")

    def _public_leak(self, m: re.Match, text: str) -> bool:
        """A global address that _ip() would have replaced, and not one written after "version"."""
        return (self._unmasked_candidate(m) and ipaddress.ip_address(m.group(0)).is_global
                and not _VERSION_WORD.search(text[max(0, m.start() - 14):m.start()]))

    def _leaks_identifiers(self, text: str):
        """MAC addresses, e-mails, IPv6 addresses and domain names still readable."""
        if self._macs and self._mac_re(text.lower()) is not None:
            for m in self._mac_rx.finditer(text.lower()):
                yield "MAC address", text[m.start():m.end()]
        for m in _EMAIL.finditer(text):
            if not m.group(0).endswith("@masked.invalid"):
                yield "email address", m.group(0)
        for m in _IPV6.finditer(text):
            if _v6_ok(m.group(0)):
                yield "IPv6 address", m.group(0)
        for m in _DOMAIN.finditer(text):
            if not _public_domain(m.group(0)):
                yield "domain name", m.group(0)

    def _leaks_secrets_and_names(self, text: str):
        """Passwords or tokens, and the names of people, devices and rooms that were registered."""
        for m in _SECRET_PAIR.finditer(text):
            if m.group(3) != "***":
                yield "password or token", m.group(3)
        for m in re.finditer(r"://([^/\s:@*]+:[^/\s@*]+)@", text):
            yield "password or token", m.group(1)
        table = {**self._areas, **self._names}
        if table:
            rest = text
            for label in sorted(set(table.values()), key=len, reverse=True):
                rest = rest.replace(label, " ")
            for m in self._compile_for(table).finditer(rest):
                yield "name", m.group(0)

    def leak_items(self, text: str) -> list[tuple[str, str]]:
        """What is still readable in already masked text: [(kind, value)], the value being the real thing found. Empty list =
        clean. The values are for the person who is exporting (shown in the window, never written to a log or to the file)."""
        found: list[tuple[str, str]] = []
        for part in (self._leaks_addresses, self._leaks_identifiers, self._leaks_secrets_and_names):
            for kind, value in part(text):
                if value and (kind, value) not in found:
                    found.append((kind, value))
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
            return self._repair_dict(obj, path)
        if isinstance(obj, list):
            return self._repair_list(obj, key, path)
        if isinstance(obj, str) and key not in _KEEP and obj != "***":
            text, fixed, rest = self.repair(obj)
            return text, fixed, [(kind, val, path) for kind, val in rest]
        return obj, 0, []

    def _repair_dict(self, obj: dict, path: str):
        out, fixed, left = {}, 0, []
        for k, v in obj.items():
            k2, f, rest = self._repair_key(k, path)
            fixed += f
            left += rest
            v2, f, rest = self.repair_data(v, k if isinstance(k, str) else "", f"{path}/{k}")
            out[k2] = v2
            fixed += f
            left += rest
        return out, fixed, left

    def _repair_key(self, k, path: str):
        """A key is repaired like a text (only the string ones); what is left of it is reported at the path of the dictionary."""
        if not isinstance(k, str):
            return k, 0, []
        k2, fixed, rest = self.repair(k)
        return k2, fixed, [(kind, val, path or "/") for kind, val in rest]

    def _repair_list(self, obj: list, key: str, path: str):
        out, fixed, left = [], 0, []
        for i, v in enumerate(obj):
            v2, f, rest = self.repair_data(v, key, f"{path}/{i}")
            out.append(v2)
            fixed += f
            left += rest
        return out, fixed, left

    def _mac_re(self, low: str):
        """A real MAC in the text, written like text() would have masked it (whole, not part of a longer run of hex digits)."""
        if getattr(self, "_mac_forms", None) != len(self._macs):
            self._mac_forms = len(self._macs)
            forms = list(chain.from_iterable((mac, mac.replace(":", "-")) for mac in self._macs))
            flat = [mac.replace(":", "") for mac in self._macs]
            self._mac_rx = re.compile(
                r"(?<![0-9a-z])(?<![^0-9a-z][0-9a-f]{2}[:\-])(?<!^[0-9a-f]{2}[:\-])(?:" + "|".join(re.escape(f) for f in forms) + r")(?![0-9a-f])(?![:\-][0-9a-f]{2}[:\-][0-9a-f]{2})"
                + r"|(?<![0-9a-f])(?:" + "|".join(re.escape(f) for f in flat) + r")(?![0-9a-f])")
        return self._mac_rx.search(low)

    def leaks_data(self, obj, key: str = "") -> list[str]:
        """Same check over parsed JSON, skipping the fields that describe the device (kept on purpose)."""
        if isinstance(obj, dict):
            return self._leaks_data_dict(obj)
        if isinstance(obj, list):
            return sorted(set(chain.from_iterable(self.leaks_data(v, key) for v in obj)))
        if isinstance(obj, str) and key not in _KEEP and obj != "***":
            return self.leaks(obj)
        return []

    def _leaks_data_dict(self, obj: dict) -> list[str]:
        """The kinds found in the keys (read together) and in every value."""
        out = set(self.leaks(" ".join(str(k) for k in obj)))
        for k, v in obj.items():
            out |= set(self.leaks_data(v, k if isinstance(k, str) else ""))
        return sorted(out)
