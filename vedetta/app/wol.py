"""Wake-on-LAN: magic packet standard (6 byte 0xFF + 16 ripetizioni del MAC
= 102 byte) inviato in UDP broadcast. Protocollo aperto, nessun privilegio
particolare: basta SO_BROADCAST."""
import re
import socket

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}([:-][0-9A-Fa-f]{2}){5}$")
PORTS = (9, 7)


def is_valid_mac(mac: str | None) -> bool:
    return bool(mac) and bool(_MAC_RE.match(mac))


def build_magic_packet(mac: str) -> bytes:
    if not is_valid_mac(mac):
        raise ValueError(mac)
    raw = bytes.fromhex(re.sub(r"[:-]", "", mac))
    return b"\xff" * 6 + raw * 16


def send(mac: str, broadcasts: list[str]) -> int:
    """Invia il pacchetto a ogni indirizzo di broadcast e porta (9 e 7).
    Ritorna quanti invii sono riusciti; un indirizzo irraggiungibile non
    blocca gli altri."""
    packet = build_magic_packet(mac)
    sent = 0
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for address in broadcasts:
            for port in PORTS:
                try:
                    sock.sendto(packet, (address, port))
                    sent += 1
                except OSError:
                    pass
    return sent
