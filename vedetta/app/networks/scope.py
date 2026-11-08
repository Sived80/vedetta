"""The one guard of the networks: to which confirmed network an address belongs, and which addresses of a list may be touched.

Pure: it is handed the networks (the main one among them). Only confirmed networks count: a proposed or paused one, or an address in an excluded range, belongs to none.
Not used by the app yet: with the main network alone it gives exactly what netutil.filter_local_ips gives (tests/check_networks_scope.py), and the callers of that
function will move here one at a time. A value that is not an IPv4 address belongs to no network (filter_local_ips raises instead: its callers check first)."""
import ipaddress
from dataclasses import dataclass

from .model import Network


@dataclass(frozen=True)
class Scope:
    networks: tuple

    def network_of(self, ip) -> Network | None:
        if not isinstance(ip, str):
            return None
        try:
            address = ipaddress.IPv4Address(ip)
        except ValueError:
            return None
        return next((n for n in self.networks if n.state == "confirmed" and n.holds(address)), None)

    def allowed(self, ips) -> list:
        """The addresses that belong to a confirmed network, in the order given."""
        return [ip for ip in ips if self.network_of(ip) is not None]

    def arp_targets(self, ips) -> list:
        """The addresses that may be asked by ARP: those of a confirmed network reached through the host's own interface ("direct"), in the
        order given. ARP never leaves the interface: for any other address the router may answer with its own MAC (proxy ARP, K10)."""
        return [ip for ip in ips if (n := self.network_of(ip)) is not None and "direct" in n.via]
