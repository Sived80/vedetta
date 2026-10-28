"""Run INSIDE a client's namespace: broadcasts one DHCP request as the phone would (`ip netns exec ls-<client> python3 send_dhcp.py <mac> <android|ios|windows|console> <address> [host name]`)."""
import os
import socket
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.lansim import dhcp, fingerprints  # noqa: E402


def main(mac: str, kind: str, address: str, hostname: str | None = None) -> None:
    profile = fingerprints.PROFILES[kind]
    packet = dhcp.client_packet(mac, dhcp.REQUEST, hostname or profile["hostname"], profile["vendor_class"], profile["prl"], requested_ip=address)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((address, 68))
        sock.sendto(packet, ("255.255.255.255", 67))


if __name__ == "__main__":
    main(*sys.argv[1:5])
