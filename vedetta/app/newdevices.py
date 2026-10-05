"""Nuovi dispositivi in rete: confronta i MAC visti via ARP (e DHCP) con quelli
gia' noti, salvati nella tabella known_macs dello storico SQLite.

Stati: 'known' (configurato o gia' visto), 'new' (mai visto dopo la baseline,
da segnalare), 'ignored' (scartato dall'utente). Al primissimo ciclo (chiave
meta 'newdev_baseline' assente) tutti i MAC presenti diventano 'known' senza
avvisi: altrimenti l'intera LAN risulterebbe "nuova". La funzione evaluate e'
sincrona e senza dipendenze dallo stato dell'app, cosi' si prova da sola."""
import logging
import re
import time
from pathlib import Path

from .history import History, history
from .vendor_lookup import lookup_vendor, resolve_vendor_info

logger = logging.getLogger("dashboard")

BASELINE_KEY = "newdev_baseline"

# MAC visti nell'ultimo ciclo. Un "nuovo dispositivo" che non c'e' piu' in rete
# non e' una cosa su cui l'utente possa agire (la scansione non lo trova): resta
# registrato ma sparisce da contatore ed elenco finche' non ricompare.
_present: set[str] | None = None
_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


def normalize_mac(mac: str | None) -> str | None:
    """MAC in maiuscolo con i due punti, None se non valido o non utilizzabile
    (tutto zero, tutto F, multicast)."""
    if not mac:
        return None
    mac = mac.strip().upper().replace("-", ":")
    if not _MAC_RE.match(mac) or mac in ("00:00:00:00:00:00", "FF:FF:FF:FF:FF:FF"):
        return None
    if int(mac[:2], 16) & 0x01:
        return None
    return mac


def own_macs() -> set[str]:
    """MAC delle interfacce del container (non e' un dispositivo "nuovo")."""
    macs = set()
    try:
        for p in Path("/sys/class/net").iterdir():
            m = normalize_mac((p / "address").read_text().strip())
            if m:
                macs.add(m)
    except OSError:
        pass
    return macs


def observed_macs(arp_by_ip: dict[str, dict], dhcp_seen: dict[str, dict], skip_ips: set[str] = frozenset()) -> dict[str, dict]:
    """{MAC: {"ip", "hostname", "vendor"}} da ARP e DHCP. L'ARP da' l'IP; dal
    DHCP (anche per MAC non visti in ARP) arriva il nome."""
    result: dict[str, dict] = {}
    for ip, host in arp_by_ip.items():
        mac = normalize_mac(host.get("mac"))
        if not mac or ip in skip_ips:
            continue
        result[mac] = {"ip": ip, "hostname": None, "vendor": resolve_vendor_info(mac, host.get("vendor"))["vendor"]}
    # Il DHCP serve solo a dare il nome ai MAC visti ora in rete: una richiesta
    # DHCP rimane nel file per sempre, ma il dispositivo puo' essere andato via da
    # un pezzo, e un MAC "presente" solo per quello non si trova con la ricerca.
    for raw, info in dhcp_seen.items():
        mac = normalize_mac(raw)
        if mac in result:
            result[mac]["hostname"] = info.get("hostname") or None
    return result


def _brand_fields(mac: str, hostname: str | None) -> dict:
    """Marca del prodotto (None se non nota) e ruolo del produttore del MAC: il
    "vendor" di un dispositivo nuovo e' il produttore della scheda, non la marca."""
    info = resolve_vendor_info(mac, None, [hostname] if hostname else [])
    return {"brand": info["brand"], "vendor_role": info["vendor_role"]}


def readable_label(row: dict) -> str:
    return row.get("hostname") or row.get("brand") or row.get("vendor") or row.get("ip") or row["mac"]


def evaluate(observed: dict[str, dict], configured_ips: set[str], configured_macs: set[str],
             ignore_macs: set[str] = frozenset(), hist: History = history, now: float | None = None) -> tuple[list[dict], list[dict]]:
    """Aggiorna known_macs con i MAC osservati. Ritorna (nuovi_da_avvisare,
    elenco_completo_dei_new). Un MAC gia' 'new' non viene riavvisato."""
    global _present
    now = time.time() if now is None else now
    observed = {m: o for m, o in observed.items() if m not in ignore_macs}
    _present = set(observed)
    rows = hist.known_all()

    if hist.meta_get(BASELINE_KEY) is None:
        if not observed:
            return [], []  # ARP vuoto (errore o rete spenta): la baseline aspetta
        for mac, obs in observed.items():
            hist.known_set(mac, now, obs["ip"], obs["vendor"] or lookup_vendor(mac), obs["hostname"], "known")
        hist.meta_set(BASELINE_KEY, str(int(now)))
        logger.info("Nuovi dispositivi: baseline di %d MAC, nessun avviso", len(observed))
        return [], []

    fresh: list[dict] = []
    for mac, obs in observed.items():
        configured = (obs["ip"] in configured_ips) or (mac in configured_macs)
        row = rows.get(mac)
        vendor = obs["vendor"] or lookup_vendor(mac)
        if row is None:
            status = "known" if configured else "new"
            hist.known_set(mac, now, obs["ip"], vendor, obs["hostname"], status)
            if status == "new":
                fresh.append({"mac": mac, "ip": obs["ip"], "vendor": vendor, "hostname": obs["hostname"],
                              "first_seen": now, **_brand_fields(mac, obs["hostname"])})
            continue
        status = "known" if (row["status"] == "new" and configured) else row["status"]
        ip = obs["ip"] or row["ip"]
        hostname = obs["hostname"] or row["hostname"]
        vendor = vendor or row["vendor"]
        if (status, ip, hostname, vendor) != (row["status"], row["ip"], row["hostname"], row["vendor"]):
            hist.known_set(mac, row["first_seen"], ip, vendor, hostname, status)
    return fresh, list_new(hist)


def sync_present(macs: set[str]) -> None:
    """Dopo una ricerca: presenti sono solo i MAC che la ricerca ha davvero trovato
    (cosi' il contatore non segnala cio' che il pulsante poi non trova)."""
    global _present
    _present = {m for m in (normalize_mac(x) for x in macs) if m}


def list_new(hist: History = history) -> list[dict]:
    """I dispositivi 'new', nel formato dell'API."""
    out = []
    for r in hist.known_all().values():
        if r["status"] == "new" and (_present is None or r["mac"] in _present):
            out.append({
                "mac": r["mac"], "ip": r["ip"], "vendor": lookup_vendor(r["mac"]) or r["vendor"],
                "hostname": r["hostname"], "first_seen": r["first_seen"], **_brand_fields(r["mac"], r["hostname"]),
            })
    return sorted(out, key=lambda d: d["first_seen"])


def ignore(macs: list[str] | None, hist: History = history) -> list[dict]:
    """Segna come 'ignored' i MAC dati (lista vuota/assente = tutti i 'new');
    ritorna l'elenco aggiornato dei 'new'."""
    wanted = {normalize_mac(m) for m in macs or []} - {None}
    if macs and not wanted:
        return list_new(hist)  # solo MAC non validi: niente da fare (non "tutti")
    hist.known_ignore(sorted(wanted) if wanted else None)
    return list_new(hist)


def list_ignored(hist: History = history) -> list[dict]:
    """I MAC rilevati in rete che l'utente ha ignorato."""
    out = [{"mac": r["mac"], "ip": r["ip"], "vendor": lookup_vendor(r["mac"]) or r["vendor"], "hostname": r["hostname"],
            "first_seen": r["first_seen"]}
           for r in hist.known_all().values() if r["status"] == "ignored"]
    return sorted(out, key=lambda d: d["first_seen"])


def unignore(mac: str, hist: History = history) -> bool:
    """Riporta un MAC ignorato tra i nuovi (ricompare se e' in rete)."""
    mac = normalize_mac(mac)
    row = next((r for k, r in hist.known_all().items() if mac and k.upper() == mac), None)
    if not row or row["status"] != "ignored":
        return False
    hist.known_set(row["mac"], row["first_seen"], row["ip"], row["vendor"], row["hostname"], "new")
    return True


def event(devices: list[dict]) -> dict:
    return {"type": "new_devices", "count": len(devices), "devices": devices}
