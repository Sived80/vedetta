"""ARP frames for the simulator, and the rule of a device that answers a direct ARP request but not a broadcast one (a camera that sleeps between the broadcasts it hears,
as in a report from a user). Standard library only; the frames are built and read here, so the rule is tested without a network."""
import socket

BROADCAST = b"\xff" * 6
ETH_ARP = b"\x08\x06"
HEADER = b"\x00\x01\x08\x00\x06\x04"        # Ethernet, IPv4, address lengths 6 and 4
REQUEST, REPLY = b"\x00\x01", b"\x00\x02"
FRAME_LENGTH = 14 + 28


def _mac(mac: str) -> bytes:
    return bytes(int(x, 16) for x in mac.split(":"))


def _frame(dst: bytes, src: bytes, operation: bytes, sender_mac: bytes, sender_ip: str, target_mac: bytes, target_ip: str) -> bytes:
    return dst + src + ETH_ARP + HEADER + operation + sender_mac + socket.inet_aton(sender_ip) + target_mac + socket.inet_aton(target_ip)


def request_frame(src_mac: str, src_ip: str, target_ip: str, target_mac: str | None = None) -> bytes:
    """"Who has target_ip?" from src: broadcast, or sent straight to the MAC the asker already knows."""
    return _frame(_mac(target_mac) if target_mac else BROADCAST, _mac(src_mac), REQUEST, _mac(src_mac), src_ip, bytes(6), target_ip)


def is_broadcast(frame: bytes) -> bool:
    return frame[0:6] == BROADCAST


def reply_to(frame: bytes, my_mac: str, my_ip: str, answer_broadcast: bool = False) -> bytes | None:
    """The answer of the device (my_mac, my_ip) to a frame it read, or None: only a request for its own address, and a broadcast one only when `answer_broadcast`."""
    if len(frame) < FRAME_LENGTH or frame[12:14] != ETH_ARP or frame[14:20] != HEADER or frame[20:22] != REQUEST:
        return None
    if frame[38:42] != socket.inet_aton(my_ip) or (is_broadcast(frame) and not answer_broadcast):
        return None
    asker_mac, asker_ip = frame[22:28], socket.inet_ntoa(frame[28:32])
    return _frame(asker_mac, _mac(my_mac), REPLY, _mac(my_mac), my_ip, asker_mac, asker_ip)
