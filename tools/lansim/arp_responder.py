"""Run INSIDE a device's namespace: answers ARP for the device's own address, by the rule of tools/lansim/arp.py (a direct request is answered, a broadcast one is not unless asked to).
Linux and root only:  python3 arp_responder.py <mac> <address> [answer-broadcast]   (stops on SIGTERM)"""
import os
import socket
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tools.lansim import arp  # noqa: E402

ETH_P_ARP = 0x0806


def main(mac: str, address: str, answer_broadcast: bool) -> None:
    with socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ARP)) as sock:
        sock.bind(("e0", ETH_P_ARP))
        while True:
            reply = arp.reply_to(sock.recv(2048), mac, address, answer_broadcast)
            if reply:
                sock.send(reply)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], len(sys.argv) > 3 and sys.argv[3] == "answer-broadcast")
