"""anonymize_registry: the part of the Anonymizer that knows the real values (addresses, MACs, names, areas) and gives each one its placeholder.

Moved out of anonymize.py: how a placeholder is chosen (one per device, the brand and the product word stay readable, a name two devices share gets its own) changes for other reasons than how the
text and the data are rewritten with them. The state keeps its attribute names: the Anonymizer is built on this class and the tests read it there."""
from collections import Counter
from itertools import chain, product
import ipaddress
import re

from .anonymize_patterns import _IPV4, _NEVER, _SHORT_TECH, _TYPE_LABELS, _WELL_KNOWN, _brand_in, _brand_keys, _ip_ok, _norm, products


class Registry:
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
            if not self._skip_alias(a, key, brand):
                usable.append((a, key))
        if not usable:
            return None
        label = self._known_label(usable) or self._new_label([a for a, _ in usable], hint, brand, icon)
        for _, key in usable:
            self._names.setdefault(key, label)
        self._name_re = None
        return label

    @staticmethod
    def _skip_alias(a: str, key: str, brand: str | None) -> bool:
        """A name that is not worth a placeholder: noise, a short technical word, a bare brand or an address."""
        return Registry._is_noise(a, key) or key in _brand_keys() or key == _norm(brand or "")   # a bare brand name is not personal and the debug needs it

    @staticmethod
    def _is_noise(a: str, key: str) -> bool:
        if len(key) < 3 or key in _NEVER or key.replace("-", "").isdigit() or _IPV4.fullmatch(a):
            return True
        return len(key) == 3 and key.isalpha() and key in _SHORT_TECH   # "pve", "nas", "cam": a short technical word, kept (a clue for the debug); any other three letters may be a first name (Leo, Eva). Two letters stay noise: known limit

    def _known_label(self, usable: list[tuple[str, str]]) -> str | None:
        """The placeholder the first already known name of the device has, if any."""
        return next((self._names[k] for _, k in usable if k in self._names), None)

    def add_devices(self, devices: list[tuple]) -> None:
        """Several devices at once: [(aliases, hint, brand, icon), ...]. A name that two or more devices have in common (the
        service name an app announces from every phone, "Apple mobile") says nothing about who is who, so it never joins them
        into one placeholder: each device keeps its own, and the shared name gets a label of its own."""
        count = self._alias_counts(devices)
        shared: list[tuple] = []
        for aliases, hint, brand, icon in devices:
            own, common = self._split_shared(count, aliases)
            self.add_device(own, hint, brand, icon)
            shared += [(a, hint, brand, icon) for a in common]
        for a, hint, brand, icon in shared:
            self.add_device([a], hint, brand, icon)

    @staticmethod
    def _alias_counts(devices: list[tuple]) -> dict[str, int]:
        """In how many devices each normalised name appears."""
        return dict(Counter(chain.from_iterable({_norm(str(a or "")) for a in aliases if a} for aliases, *_ in devices)))

    @staticmethod
    def _split_shared(count: dict[str, int], aliases: list) -> tuple[list, list]:
        """(names only this device has, names that two or more devices have), the empty ones dropped."""
        own = [a for a in aliases if a and count.get(_norm(str(a)), 0) < 2]
        common = [a for a in aliases if a and count.get(_norm(str(a)), 0) >= 2]
        return own, common

    def _new_label(self, names: list[str], hint: str | None, brand: str | None = None, icon: str | None = None) -> str:
        base = self._brand_base(names, brand) or self._product_base(names) or self._icon_kind(icon) or _TYPE_LABELS.get(hint or "") or "Device"
        self._counts[base] = self._counts.get(base, 0) + 1
        return f"{base}-{self._counts[base]}"

    @staticmethod
    def _brand_base(names: list[str], brand: str | None) -> str | None:
        """The brand written in the name stays visible: it is the clue the brand was recognised from."""
        if brand and any(_brand_in(brand, n) for n in names):
            return re.sub(r"[^A-Za-z0-9]+", "", brand)
        return None

    @staticmethod
    def _product_base(names: list[str]) -> str | None:
        return next((label for (label, rx), n in product(products(), names) if rx.search(n)), None)

    @staticmethod
    def _icon_kind(icon: str | None) -> str:
        """The kind of device (thermostat, gate, camera...) tells what the name was about."""
        if icon in (None, "server", "help"):
            return ""
        return "".join(w.capitalize() for w in re.findall(r"[a-z0-9]+", icon or ""))

    def _private_ip(self, ip: str) -> str:
        parts = ip.split(".")
        idx = self._nets.setdefault(".".join(parts[:3]), len(self._nets))
        return f"10.{idx}.0.{int(parts[3])}"

    def _public_ip(self, ip: str) -> str:
        n = self._pub.setdefault(ip, len(self._pub) + 1) - 1
        return f"203.0.{113 + n // 254}.{n % 254 + 1}"      # documentation range: it can never be a real address
