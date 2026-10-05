import re

from .i18n import t

MAX_NAME_LEN = 40

# Unico testo tecnico da escludere per forma: il segnaposto di nmap quando la
# pagina non ha un <title> ("Site doesn't have a title (text/html; ...)"). Non
# e' un titolo vero. Tutto il resto si decide con regole generiche (sotto).
_USELESS_TITLE_RE = re.compile(r"^site doesn't have a title", re.IGNORECASE)

# Segnali strutturali nell'output di http-title: redirect non seguito o seguito
# verso un URL di accesso ("Did not follow redirect to http://x/login",
# "Requested resource was /login.html"): il titolo e' quello della pagina di
# login, non del dispositivo. Una pagina d'errore HTTP inizia con il codice
# (404, 403 Forbidden...): indipendente dalla lingua.
_LOGIN_REDIRECT_RE = re.compile(
    r"(did not follow redirect to|requested resource was)\s+\S*(login|signin|sign-in|logon|auth|session)", re.IGNORECASE)
_HTTP_ERROR_TITLE_RE = re.compile(r"^[1-5]\d\d\b")

# Titoli (normalizzati) che compaiono su 2+ dispositivi: se lo stesso titolo e'
# su host diversi non identifica nessuno di essi ("Login", "Index of /", "Welcome
# to nginx!"...). Ricalcolato dalla configurazione a ogni ciclo.
_generic_titles: set[str] = set()


def normalize_title(title: str | None) -> str:
    """Solo la prima riga (nmap aggiunge righe come 'Requested resource was ...'),
    minuscolo, spazi compressi."""
    if not title:
        return ""
    first = title.strip().splitlines()[0] if title.strip() else ""
    return " ".join(first.split()).lower()


def update_generic_titles(devices: list[dict]) -> None:
    """Calcola i titoli condivisi da 2+ dispositivi (scan_info.http_title)."""
    global _generic_titles
    seen: dict[str, int] = {}
    for d in devices:
        t = normalize_title(((d.get("scan_info") or {}).get("http_title")))
        if t:
            seen[t] = seen.get(t, 0) + 1
    _generic_titles = {t for t, n in seen.items() if n >= 2}


def is_useless_title(title: str | None) -> bool:
    """Placeholder tecnico di nmap (non un titolo vero)."""
    return bool(title) and bool(_USELESS_TITLE_RE.match(" ".join(title.split())))


def should_show_title(title: str | None) -> bool:
    """True solo se il titolo identifica davvero il dispositivo."""
    if not title or is_useless_title(title):
        return False
    if _LOGIN_REDIRECT_RE.search(title):
        return False
    norm = normalize_title(title)
    if not norm or _HTTP_ERROR_TITLE_RE.match(norm):
        return False
    return norm not in _generic_titles


def truncate_name(name: str | None) -> str | None:
    """Alcune sorgenti (mDNS in primis) a volte restituiscono etichette tecniche
    lunghissime (es. nomi DNS-SD con escape non decodificati): un limite
    generoso ma fisso evita che rompano il layout delle card."""
    if not name or len(name) <= MAX_NAME_LEN:
        return name
    return name[: MAX_NAME_LEN - 1].rstrip() + "…"


def quantize_uptime(seconds) -> int | None:
    """Secondi interi sotto il minuto, poi a minuti pieni: l'uptime che sta nel
    dizionario del dispositivo cambia al massimo una volta al minuto, cosi' la
    card non viene sostituita a ogni ciclo."""
    if seconds is None:
        return None
    seconds = int(seconds)
    return seconds if seconds < 60 else seconds // 60 * 60


def format_uptime(seconds) -> str | None:
    """Testo nella lingua corrente (chiamata dai template tramite filtro)."""
    if seconds is None:
        return None
    seconds = int(seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    if days > 0:
        return t("uptime.days_hours", d=days, h=hours)
    if hours > 0:
        return t("uptime.hours_minutes", h=hours, m=minutes)
    return t("uptime.minutes", m=minutes)


def format_uptime_short(seconds) -> str | None:
    """Solo secondi, minuti o ore (per le tabelle, dove lo spazio e' poco)."""
    if seconds is None:
        return None
    seconds = int(seconds)
    if seconds < 60:
        return t("uptime.short_seconds", n=seconds)
    if seconds < 3600:
        return t("uptime.short_minutes", n=seconds // 60)
    return t("uptime.short_hours", n=seconds // 3600)


# Le qualita' sono codici neutri ("excellent"...): il testo si sceglie in
# visualizzazione (chiave signal.<codice>), cosi' lo stato condiviso tra i
# browser non dipende dalla lingua di nessuno.
def wifi_quality(rssi) -> tuple[str, str] | tuple[None, None]:
    if rssi is None:
        return None, None
    if rssi >= -50:
        return "excellent", "green"
    if rssi >= -60:
        return "good", "green"
    if rssi >= -70:
        return "fair", "yellow"
    return "weak", "red"


def lan_quality(mbps) -> tuple[str, str] | tuple[None, None]:
    if mbps is None:
        return None, None
    if mbps >= 1000:
        return "excellent", "green"
    if mbps >= 100:
        return "good", "yellow"
    return "weak", "red"
