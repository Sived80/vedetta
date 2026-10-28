"""The virtual LAN: one Linux network namespace per machine, all on one bridge. Needs Linux and root; everything it creates starts with "ls" and is removed on exit.

    router  .1      the gateway
    vedetta .2      where Vedetta (or arp-scan) looks at the network from
    ext     .3      a Wi-Fi extender: it answers ARP for the clients it "holds" (proxy ARP) with its own MAC
    ext2    .4      a second extender (optional), far from the first and at the same distance from the router: the geography is ext - router - ext2
    clients .20+    the phones; while an extender holds one, the phone does not answer ARP itself (arp_ignore), so exactly one MAC answers for the address,
                    as in the real network where the answers alternate between the phone and the extender. A phone that no extender holds is on the router's own Wi-Fi
                    (the middle of the geography) and answers with its own MAC
"""
import os
import subprocess
import sys

SUBNET = "10.9.0"
BRIDGE = "lsbr0"
ROUTER_MAC, VEDETTA_MAC, EXTENDER_MAC, EXTENDER2_MAC = "02:00:00:00:00:01", "02:00:00:00:00:02", "4e:00:00:00:00:03", "4e:00:00:00:00:04"


def _run(*cmd: str, check: bool = True) -> str:
    done = subprocess.run(cmd, check=check, capture_output=True, text=True)
    return done.stdout


def _ip(*args: str, check: bool = True) -> str:
    return _run("ip", *args, check=check)


def _ns(name: str) -> str:
    return "ls-" + name


class Lan:
    """A context manager: `with Lan() as lan:` builds the base network, `lan.add_client(...)` adds a phone, leaving the block removes everything."""

    def __init__(self, extenders: int = 1) -> None:
        self.nodes: list[str] = []
        self.extenders = extenders
        self.holder: dict[str, str | None] = {}       # client address -> the extender holding it now
        self.responders: list[subprocess.Popen] = []  # the ARP responders of devices that answer in their own way

    def __enter__(self) -> "Lan":
        self.cleanup()
        _ip("link", "add", BRIDGE, "type", "bridge")
        _ip("link", "set", BRIDGE, "up")
        _ip("addr", "add", SUBNET + ".254/24", "dev", BRIDGE)       # the host reaches the machines (Vedetta's web API) through the bridge
        self.add_node("router", ROUTER_MAC, SUBNET + ".1")
        self.add_node("vedetta", VEDETTA_MAC, SUBNET + ".2")
        self._add_extender("ext", EXTENDER_MAC, 3)
        if self.extenders > 1:
            self._add_extender("ext2", EXTENDER2_MAC, 4)
        return self

    def __exit__(self, *exc) -> None:
        self.cleanup()

    def cleanup(self) -> None:
        """Removes what an earlier run may have left (namespaces and the bridge named ls...)."""
        for proc in self.responders:
            proc.terminate()
        self.responders = []
        for line in _ip("netns", "list", check=False).splitlines():
            if line.startswith("ls-"):
                _ip("netns", "del", line.split()[0], check=False)
        _ip("link", "del", BRIDGE, check=False)
        for line in _ip("-o", "link", "show", check=False).splitlines():        # the host ends of the cables go away a little after their namespace
            name = line.split(":")[1].strip().split("@")[0] if ":" in line else ""
            if name.startswith("lsh-"):
                _ip("link", "del", name, check=False)

    def add_node(self, name: str, mac: str, address: str) -> None:
        """A machine on the bridge: its own namespace, an interface e0 with this MAC and address, the other end of the cable on the bridge."""
        ns, host = _ns(name), "lsh-" + name[:9]
        _ip("netns", "add", ns)
        _ip("link", "add", host, "type", "veth", "peer", "name", "e0", "netns", ns)
        _ip("-n", ns, "link", "set", "e0", "address", mac)
        _ip("-n", ns, "addr", "add", address + "/24", "dev", "e0")
        _ip("-n", ns, "link", "set", "lo", "up")
        _ip("-n", ns, "link", "set", "e0", "up")
        _ip("link", "set", host, "master", BRIDGE)
        _ip("link", "set", host, "up")
        self.nodes.append(name)

    def _add_extender(self, name: str, mac: str, host_number: int) -> None:
        """An extender holds a client by having a route to it through w0 (a cable to nowhere): with proxy ARP on e0 it then answers for it."""
        self.add_node(name, mac, "%s.%d" % (SUBNET, host_number))
        ns = _ns(name)
        _ip("-n", ns, "link", "add", "w0", "type", "dummy")
        _ip("-n", ns, "link", "set", "w0", "up")
        _run("ip", "netns", "exec", ns, "sysctl", "-qw", "net.ipv4.conf.e0.proxy_arp=1", "net.ipv4.ip_forward=1")

    def add_client(self, name: str, mac: str, host_number: int) -> str:
        """A phone with this MAC at 10.9.0.<host_number>; returns its address."""
        address = "%s.%d" % (SUBNET, host_number)
        self.add_node(name, mac, address)
        return address

    def add_camera(self, name: str, mac: str, host_number: int, answer_broadcast: bool = False) -> str:
        """A device that answers a direct ARP request but, unless `answer_broadcast`, not a broadcast one (a camera that sleeps between the broadcasts it hears): the kernel is
        silenced and a small responder of its own does the answering."""
        address = self.add_client(name, mac, host_number)
        ns = _ns(name)
        _run("ip", "netns", "exec", ns, "sysctl", "-qw", "net.ipv4.conf.all.arp_ignore=8", "net.ipv4.conf.e0.arp_ignore=8")
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "arp_responder.py")
        self.responders.append(subprocess.Popen(["ip", "netns", "exec", ns, sys.executable, "-B", helper, mac, address] + (["answer-broadcast"] if answer_broadcast else []),
                                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        return address

    def probe(self, *command: str) -> bool:
        """Runs a command in the vedetta machine and says whether it succeeded (the tools of a search: arp-scan, ping, nmap)."""
        return subprocess.run(["ip", "netns", "exec", _ns("vedetta"), *command], capture_output=True, text=True).returncode == 0

    def probe_output(self, *command: str) -> str:
        return subprocess.run(["ip", "netns", "exec", _ns("vedetta"), *command], capture_output=True, text=True).stdout

    def hold(self, name: str, address: str, by: str | None) -> None:
        """The extender `by` ("ext" or "ext2") starts answering for the client's address and the client stops answering for itself; `by` None gives the address back to the phone
        (it is on the router's Wi-Fi). A phone passes from one extender to the other without a moment in between."""
        before = self.holder.get(address)
        if before and before != by:
            _ip("-n", _ns(before), "route", "del", address + "/32", "dev", "w0", check=False)
        if by and by != before:
            _ip("-n", _ns(by), "route", "add", address + "/32", "dev", "w0", check=False)
        self.holder[address] = by
        ignore = "8" if by else "0"
        _run("ip", "netns", "exec", _ns(name), "sysctl", "-qw", "net.ipv4.conf.all.arp_ignore=" + ignore, "net.ipv4.conf.e0.arp_ignore=" + ignore)

    def set_mac(self, name: str, mac: str) -> None:
        """A phone that rotates its private MAC: the interface goes down, takes the new address, comes up."""
        ns = _ns(name)
        _ip("-n", ns, "link", "set", "e0", "down")
        _ip("-n", ns, "link", "set", "e0", "address", mac)
        _ip("-n", ns, "link", "set", "e0", "up")

    def arp_scan(self, first: int, last: int) -> dict[str, str]:
        """{address: MAC} of the first reply for each address from .first to .last, as seen from the vedetta machine."""
        out = _run("ip", "netns", "exec", _ns("vedetta"), "arp-scan", "-I", "e0", "-q", "--plain", "--retry=1", "--timeout=30",
                   "%s.%d-%s.%d" % (SUBNET, first, SUBNET, last))
        found: dict[str, str] = {}
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0] not in found:
                found[parts[0]] = parts[1].lower()
        return found

    def announce(self, name: str, kind: str, mac: str, address: str, hostname: str | None = None) -> None:
        """The phone broadcasts a DHCP request with the fingerprint of its system (kind: "android", "ios", "windows" or "console") and, optionally, its own host name, as when it joins or renews."""
        helper = os.path.join(os.path.dirname(os.path.abspath(__file__)), "send_dhcp.py")
        _run("ip", "netns", "exec", _ns(name), sys.executable, "-B", helper, mac, kind, address, *([hostname] if hostname else []))

    def move(self, name: str, old_address: str, new_address: str) -> None:
        """The phone leaves one address and takes another (the address of the card changes, the phone does not)."""
        ns = _ns(name)
        _ip("-n", ns, "addr", "del", old_address + "/24", "dev", "e0")
        _ip("-n", ns, "addr", "add", new_address + "/24", "dev", "e0")

    def link(self, name: str, up: bool) -> None:
        """The phone leaves the network (Wi-Fi off) or comes back."""
        _ip("-n", _ns(name), "link", "set", "e0", "up" if up else "down")
