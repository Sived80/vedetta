"""DHCP packets for the simulator: what a client broadcasts (read by Vedetta's passive listener) and the answer of the small router. Standard library only."""
import socket

MAGIC_COOKIE = b"\x63\x82\x53\x63"
DISCOVER, OFFER, REQUEST, ACK = 1, 2, 3, 5


def _mac_bytes(mac: str) -> bytes:
    return bytes(int(x, 16) for x in mac.split(":"))


def _option(code: int, value: bytes) -> bytes:
    return bytes([code, len(value)]) + value


def _header(op: int, xid: bytes, mac: str, yiaddr: str = "0.0.0.0") -> bytes:
    """The fixed 236 bytes: operation, hardware type and length, transaction, addresses, client hardware address."""
    return (bytes([op, 1, 6, 0]) + xid + b"\x00\x00\x80\x00" + socket.inet_aton("0.0.0.0") + socket.inet_aton(yiaddr)
            + socket.inet_aton("0.0.0.0") * 2 + _mac_bytes(mac).ljust(16, b"\x00") + bytes(192))


def client_packet(mac: str, msg_type: int, hostname: str | None, vendor_class: str | None, prl: list[int],
                  requested_ip: str | None = None, xid: bytes = b"\x12\x34\x56\x78") -> bytes:
    """A DISCOVER or REQUEST as a phone sends it: its own MAC in the client hardware address, and the options that fingerprint its system."""
    options = _option(53, bytes([msg_type]))
    if requested_ip:
        options += _option(50, socket.inet_aton(requested_ip))
    if hostname:
        options += _option(12, hostname.encode())
    if vendor_class:
        options += _option(60, vendor_class.encode())
    options += _option(55, bytes(prl))
    return _header(1, xid, mac) + MAGIC_COOKIE + options + b"\xff"


def server_reply(request: bytes, msg_type: int, your_ip: str, server_ip: str, lease_s: int = 86400,
                 netmask: str = "255.255.255.0", router: str | None = None, dns: str | None = None) -> bytes:
    """An OFFER (2) or ACK (5) for a client packet: the same transaction and client address, the address given, the server identifier and the lease."""
    mac = ":".join("%02x" % b for b in request[28:34])
    options = (_option(53, bytes([5 if msg_type == ACK else 2])) + _option(54, socket.inet_aton(server_ip))
               + _option(51, lease_s.to_bytes(4, "big")) + _option(1, socket.inet_aton(netmask)))
    if router:
        options += _option(3, socket.inet_aton(router))
    if dns:
        options += _option(6, socket.inet_aton(dns))
    return _header(2, request[4:8], mac, your_ip) + MAGIC_COOKIE + options + b"\xff"
