"""Memoria e ascolto continuo dei nomi Bonjour (mDNS), come la memoria DHCP.

Molti dispositivi (iPhone, tablet) annunciano il proprio nome solo quando sono svegli: una scansione di pochi
secondi li manca spesso. Qui si fa in due modi:
- ascolto continuo: un browser DNS-SD (zeroconf) sempre attivo raccoglie gli annunci appena arrivano;
- memoria: ogni nome visto (anche da una scansione) si ricorda per MAC in /data/mdns_seen.json e non si perde
  quando il dispositivo torna a dormire.

Il nome arriva con un IP: si lega al MAC tramite la tabella ARP; se il MAC non e' ancora noto si tiene per IP
(valido per 14 giorni, un IP puo' cambiare padrone). Solo lettura passiva: nessuna richiesta mirata a un dispositivo."""
import asyncio
import json
import re
import time
from pathlib import Path

from . import paths
from .applog import logger

STORE_PATH = paths.data_path("mdns_seen.json")
IP_TTL_S = 14 * 86400
_NAME_STRONG = 3   # punteggio di un nome scelto dall'utente (friendly_name / servizio con nome utente)

by_mac: dict[str, dict] = {}   # mac minuscolo -> {"name", "score", "model", "manufacturer", "services", "ip", "seen"}
by_ip: dict[str, dict] = {}    # ip -> stessa scheda, finche' il MAC non e' noto
_mac_for_ip = lambda ip: None  # noqa: E731  (impostato da start)
_task: asyncio.Task | None = None
_dirty = False


def _load() -> None:
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        by_mac.update(data.get("by_mac") or {})
        by_ip.update(data.get("by_ip") or {})
    except (OSError, ValueError):
        pass


def _save() -> None:
    global _dirty
    _dirty = False
    try:
        tmp = STORE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({"by_mac": by_mac, "by_ip": by_ip}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STORE_PATH)
    except OSError:
        pass


def score_name(stype: str, instance: str, txt: str) -> tuple[int, str]:
    """(punteggio, nome) di un annuncio: stessa scelta della scansione (chiavi del TXT, servizi con nome utente)."""
    from . import scanner
    score, value = (2 if stype in scanner._MDNS_USER_NAMED else 1), instance
    for key, key_score in scanner._MDNS_NAME_KEYS:
        m = re.search(key + r'=([^"]*)', txt)
        if m and m.group(1) and not scanner._MDNS_SLUG_RE.match(m.group(1)):
            return key_score, m.group(1)
    return score, value


def record(ip: str, stype: str, instance: str, txt: str, now: float | None = None) -> None:
    """Ricorda un annuncio (chiamata sia dall'ascolto continuo sia dalla scansione)."""
    global _dirty
    from . import scanner
    if not scanner.is_valid_ipv4(ip):
        return
    now = time.time() if now is None else now
    score, name = score_name(stype, instance, txt)
    meta = scanner.parse_mdns_txt(txt)
    mac = _mac_for_ip(ip)
    card = by_mac.get(mac) if mac else by_ip.get(ip)
    card = dict(card or {})
    services = set(card.get("services") or []) | {stype}
    # un nome migliore sostituisce quello vecchio; a pari punteggio vale il piu' recente
    if score >= int(card.get("score") or 0):
        card.update(name=scanner.truncate_name(name), score=score)
    for key in ("model", "manufacturer"):
        if meta.get(key):
            card[key] = meta[key]
    card.update(services=sorted(services), ip=ip, seen=now)
    if mac:
        by_mac[mac] = card
        by_ip.pop(ip, None)
    else:
        by_ip[ip] = card
    _dirty = True


def remember_scan(found: list[tuple[str, str, str, str]]) -> None:
    """Annunci raccolti da una scansione mDNS (tipo, istanza, ip, txt)."""
    for stype, instance, ip, txt in found:
        record(ip, stype, instance, txt)


def lookup(mac, ip: str | None = None) -> dict | None:
    """Scheda ricordata per quel MAC o, se manca, per quell'IP (recente). None se mai visto."""
    m = str(mac or "").strip().lower().replace("-", ":")
    if m and m in by_mac:
        return by_mac[m]
    card = by_ip.get(ip or "")
    if card and time.time() - float(card.get("seen") or 0) < IP_TTL_S:
        return card
    return None


def as_scan_info(card: dict | None) -> dict:
    """La scheda ricordata nel formato dei campi di scan_info (solo i campi presenti)."""
    if not card:
        return {}
    out = {}
    for src, dst in (("name", "mdns_name"), ("model", "mdns_model"), ("manufacturer", "mdns_manufacturer")):
        if card.get(src):
            out[dst] = card[src]
    if card.get("services"):
        out["mdns_services"] = ", ".join(card["services"])[:200]
    return out


def _housekeeping() -> None:
    """Lega al MAC le schede tenute per IP (appena l'ARP lo conosce) e scarta quelle vecchie."""
    global _dirty
    now = time.time()
    for ip, card in list(by_ip.items()):
        mac = _mac_for_ip(ip)
        if mac:
            old = by_mac.get(mac)
            if not old or float(card.get("seen") or 0) >= float(old.get("seen") or 0):
                by_mac[mac] = card
            del by_ip[ip]
            _dirty = True
        elif now - float(card.get("seen") or 0) > IP_TTL_S:
            del by_ip[ip]
            _dirty = True


async def _listen() -> None:
    """Browser DNS-SD sempre attivo: scopre i tipi di servizio e naviga ogni tipo; ogni istanza vista si registra."""
    from zeroconf import IPVersion, ServiceStateChange
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf
    from . import scanner

    azc = AsyncZeroconf(ip_version=IPVersion.V4Only)
    browsers: list = []
    types: set[str] = set()
    tasks: set[asyncio.Task] = set()

    async def read_instance(stype: str, name: str) -> None:
        info = AsyncServiceInfo(stype, name)
        try:
            if not await info.async_request(azc.zeroconf, 3000):
                return
        except Exception:
            return
        suffix = "." + stype
        instance = name[: -len(suffix)] if name.endswith(suffix) else name
        txt = scanner._props_to_txt(info.properties)
        short = stype[: -len(".local.")] if stype.endswith(".local.") else stype
        for address in info.parsed_addresses(IPVersion.V4Only):
            record(address, short, instance, txt)

    def on_instance(zeroconf, service_type, name, state_change) -> None:
        if state_change is ServiceStateChange.Removed:
            return
        task = asyncio.ensure_future(read_instance(service_type, name))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def on_type(zeroconf, service_type, name, state_change) -> None:
        if state_change is ServiceStateChange.Removed or name in types:
            return
        types.add(name)
        browsers.append(AsyncServiceBrowser(azc.zeroconf, name, handlers=[on_instance]))

    try:
        browsers.append(AsyncServiceBrowser(azc.zeroconf, scanner._MDNS_META_TYPE, handlers=[on_type]))
        logger.info("Ascolto mDNS continuo avviato")
        while True:
            await asyncio.sleep(60)
            _housekeeping()
            if _dirty:
                await asyncio.to_thread(_save)
    except asyncio.CancelledError:
        raise
    finally:
        for b in browsers:
            try:
                await b.async_cancel()
            except Exception:
                pass
        for t in list(tasks):
            t.cancel()
        try:
            await azc.async_close()
        except Exception:
            pass
        if _dirty:
            _save()


def start(state) -> None:
    """Dal lifespan: carica la memoria e avvia l'ascolto (se zeroconf manca resta solo la memoria)."""
    global _task, _mac_for_ip
    _load()

    def mac_for_ip(ip: str):
        arp = state._arp[1] if getattr(state, "_arp", None) else {}
        host = arp.get(ip)
        m = (host or {}).get("mac")
        return str(m).lower() if m else None
    _mac_for_ip = mac_for_ip
    try:
        import zeroconf  # noqa: F401
    except ImportError:
        logger.warning("zeroconf non installato: ascolto mDNS continuo non attivo")
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(_listen())


async def stop() -> None:
    if _task:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
