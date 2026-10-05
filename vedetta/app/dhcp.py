"""Ascolto DHCP passivo: i client (telefoni compresi) annunciano in broadcast,
quando entrano in rete o chiedono un lease, il proprio nome (opzione 12), la
lista dei parametri richiesti (opzione 55, che per ogni sistema operativo ha
un ordine caratteristico - il principio delle impronte di Fingerbank) e la
classe del produttore (opzione 60). Non si invia nulla: si legge soltanto cio'
che passa in broadcast sul segmento."""
import asyncio
import json
import logging
import socket
import time


from .paths import DATA_DIR as CONFIG_DIR

logger = logging.getLogger("dashboard")

STORE_PATH = CONFIG_DIR / "dhcp_seen.json"
_DHCP_REQUEST_TYPES = {1, 3}  # DISCOVER, REQUEST
_MAGIC_COOKIE = b"\x63\x82\x53\x63"

# mac (minuscolo, con i due punti) -> {"hostname", "prl", "vendor_class", "seen"}
seen: dict[str, dict] = {}
# IP del server DHCP (opzione 54 nelle richieste dei client) -> ultimo istante visto
servers: dict[str, float] = {}


def _load() -> None:
    try:
        seen.update(json.loads(STORE_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass


def _save() -> None:
    try:
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(seen), encoding="utf-8")
        tmp.replace(STORE_PATH)
    except OSError:
        pass


def parse(packet: bytes) -> tuple[str, dict] | None:
    """Estrae MAC e opzioni utili da un pacchetto BOOTP/DHCP di un client."""
    if len(packet) < 241 or packet[0] != 1 or packet[236:240] != _MAGIC_COOKIE:
        return None
    mac = ":".join(f"{b:02x}" for b in packet[28:34])
    info: dict = {}
    msg_type = None
    i = 240
    while i < len(packet):
        code = packet[i]
        if code == 255:
            break
        if code == 0:
            i += 1
            continue
        if i + 1 >= len(packet):
            break
        length = packet[i + 1]
        value = packet[i + 2:i + 2 + length]
        i += 2 + length
        if code == 53 and value:
            msg_type = value[0]
        elif code == 12:
            info["hostname"] = value.decode("utf-8", "ignore").strip("\x00 ")
        elif code == 55:
            info["prl"] = ",".join(str(b) for b in value)
        elif code == 60:
            info["vendor_class"] = value.decode("utf-8", "ignore").strip("\x00 ")
        elif code == 54 and len(value) == 4:
            info["server_id"] = ".".join(str(b) for b in value)
    if msg_type not in _DHCP_REQUEST_TYPES:
        return None
    return mac, info


class _Listener(asyncio.DatagramProtocol):
    def datagram_received(self, data: bytes, addr) -> None:
        parsed = parse(data)
        if not parsed:
            return
        mac, info = parsed
        server = info.pop("server_id", None)
        if server:
            servers[server] = time.time()
        previous = seen.get(mac, {})
        # Una richiesta senza nome (frequente nei rinnovi) non cancella il
        # nome visto in precedenza.
        entry = {**previous, **{k: v for k, v in info.items() if v}, "seen": int(time.time())}
        changed = {k: v for k, v in entry.items() if k != "seen"} != {k: v for k, v in previous.items() if k != "seen"}
        seen[mac] = entry
        if changed:
            logger.info("DHCP: %s hostname=%s prl=%s classe=%s", mac, entry.get("hostname") or "-",
                        entry.get("prl") or "-", entry.get("vendor_class") or "-")
            _save()


async def start() -> asyncio.BaseTransport | None:
    _load()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", 67))
        sock.setblocking(False)
        transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(_Listener, sock=sock)
    except OSError as exc:
        sock.close()
        logger.warning("Ascolto DHCP non attivo (porta 67): %s", exc)
        return None
    logger.info("Ascolto DHCP passivo attivo (porta 67)")
    return transport


# ---- classificazione ----

def is_private_mac(mac: str | None) -> bool:
    """Bit U/L (secondo bit meno significativo del primo byte) = indirizzo
    assegnato localmente: e' il "MAC privato" di iOS/Android/Windows."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (AttributeError, ValueError):
        return False


def _os_family(prl: str | None, vendor_class: str | None) -> str | None:
    vc = (vendor_class or "").lower()
    if vc.startswith("android-dhcp"):
        return "android"
    if vc.startswith("msft"):
        return "windows"
    if vc.startswith(("dhcpcd", "udhcp")):
        return "linux"
    if not prl:
        return None
    opts = [int(x) for x in prl.split(",") if x.isdigit()]
    if opts[:3] == [1, 121, 3] and 252 in opts:
        # Stessa impronta base per iOS e macOS: macOS aggiunge 95, 44, 46.
        return "macos" if 95 in opts or 44 in opts else "ios"
    if 249 in opts and 252 in opts:
        return "windows"
    if 26 in opts and 28 in opts and 51 in opts and 58 in opts:
        return "android"
    if 28 in opts and 12 in opts:
        return "linux"
    return None


def os_family(mac: str | None) -> str | None:
    """Famiglia di sistema operativo dedotta dall'impronta DHCP del MAC, se visto."""
    entry = seen.get((mac or "").lower())
    return _os_family(entry.get("prl"), entry.get("vendor_class")) if entry else None


def mobile_score(mac: str | None, name_is_mobile: bool, has_ports: bool | None) -> tuple[int, str | None]:
    """Parte DHCP del punteggio "mobile" (le altre evidenze - modello mDNS, presenza,
    batteria di rete - si sommano in identity.mobile_assess). Punteggio "e' un telefono/tablet", con l'indizio principale per il
    tooltip. >= 3 conta come mobile. Regola: l'impronta iOS e il nome da telefono
    bastano da soli; l'impronta Android no (vale anche per le TV) e va
    confermata, di norma dal MAC privato; il MAC privato e l'assenza di porte in
    ascolto sono indizi deboli e da soli non bastano."""
    entry = seen.get((mac or "").lower())
    score, reason = 0, None
    if name_is_mobile:
        score, reason = score + 3, "nome"
    if entry:
        family = _os_family(entry.get("prl"), entry.get("vendor_class"))
        # iOS/iPadOS e' sempre un telefono o un tablet: basta l'impronta. Android gira
        # anche su TV, set-top box e proiettori: da sola non basta, serve un secondo
        # indizio (di norma il MAC privato, che i telefoni usano e le TV no).
        if family == "ios":
            score, reason = score + 3, reason or "impronta DHCP (ios)"
        elif family == "android":
            score, reason = score + 2, reason or "impronta DHCP (android)"
        elif family in ("windows", "macos", "linux"):
            score -= 2
        host = (entry.get("hostname") or "").lower()
        if host.startswith("iphone") or host.startswith("ipad"):
            score, reason = score + 3, reason or "nome DHCP"
        elif host.startswith("android-"):
            score, reason = score + 2, reason or "nome DHCP"
    if is_private_mac(mac):
        score, reason = score + 1, reason or "MAC privato"
    return score, reason
