"""Nomi dei dispositivi. Principi comuni agli altri progetti (NetAlertX, Home
Assistant, Pi-hole): ogni fonte propone un nome, i nomi inutili si scartano, tra
quelli rimasti vince la fonte piu' affidabile, il nome scelto a mano non si
tocca mai e, se non si trova nulla, resta l'indirizzo IP.

Il nome si salva con la sua fonte ("name_source"): "user" = scelto dall'utente
(mai sovrascritto); le altre sono fonti automatiche, e una scansione successiva
puo' sostituire il nome solo con uno di una fonte piu' affidabile."""
import re

# Piu' alto = piu' affidabile. "adapter": nome dato dal dispositivo stesso via la
# sua API aperta (Shelly); "mdns": nome pubblicato dal dispositivo (servizio con
# nome scelto dall'utente o hostname .local); "upnp": friendlyName; "dhcp":
# hostname annunciato al router; "netbios": nome Windows/Samba; "nmap": DNS inverso.
# "onvif": nome dichiarato via ONVIF (spesso generico, es. "IPCAM"), quindi per ultimo.
# "tls": nome host nel certificato del dispositivo (solo nomi di rete locale, vedi cn_host).
# "weak": nome segnaposto del sistema ("Android_MGDZ1OUL"): meglio dell'IP, peggio di qualunque altro.
PRIORITY = {"adapter": 90, "mdns": 70, "upnp": 65, "dhcp": 55, "netbios": 45, "nmap": 40, "tls": 38, "onvif": 35, "web": 30,
            "ha": 68, "ha_user": 95, "weak": 20}

# Parola generica di piattaforma + codice casuale: l'hostname predefinito di un sistema, non il nome del dispositivo.
_PLACEHOLDER_RE = re.compile(r"^(android|iphone|ipad|galaxy|tablet|phone|device|esp|espressif|wlan|wifi|smart|unknown)[-_ ]?"
                             r"(?=[0-9a-z]*\d)[0-9a-z]{5,}$", re.IGNORECASE)

_LOCAL_CN = (".local", ".lan", ".home", ".fritz.box", ".localdomain", ".internal", ".home.arpa", ".homenet")


# Titoli di pagina che non sono un nome (schermate di accesso, errori, pagine di benvenuto).
_GENERIC_TITLES = {"login", "log in", "sign in", "signin", "welcome", "index", "home", "default", "error", "dashboard",
                   "admin", "web interface", "webui", "web ui", "authentication", "authorization required", "status",
                   "configuration", "setup", "main menu", "untitled", "document", "page", "it works", "test page"}
_TITLE_NOISE = re.compile(r"not found|forbidden|unauthori[sz]ed|bad request|welcome to|index of|^\d{3}\b|error|default web|apache|nginx",
                          re.IGNORECASE)
_TITLE_SUFFIX = re.compile(r"\s+(main menu|configuration|web ?(ui|interface|gui)|login|home|index|status|setup)$", re.IGNORECASE)


_GENERIC_FIRST = {"login", "log", "sign", "signin", "welcome", "error", "index", "unauthorized", "forbidden", "requested", "authentication"}


def title_name(title: str | None) -> str | None:
    """Nome dal titolo della pagina web del dispositivo ("Termostato - Main Menu" ->
    "Termostato", "pve - Proxmox Virtual Environment" -> "pve"). None per i titoli generici
    ("Login", "404 Not Found"): il titolo e' una fonte debole, vale solo se sembra un nome."""
    if not title:
        return None
    text = " ".join(str(title).split())
    from .formatters import is_useless_title, should_show_title  # tardivo: formatters importa i18n
    if is_useless_title(text) or not should_show_title(text):
        return None  # segnaposto di nmap ("Site doesn't have a title"), login, errori HTTP
    cand = re.split(r"\s+[-|–—:]\s+|\s*\|\s*", text)[0].strip()
    cand = _TITLE_SUFFIX.sub("", cand).strip()
    if re.search(r"\bv?\d+(\.\d+){1,3}$", cand):
        return None   # "software 1.47.45": titolo di un programma, non il nome dell'apparecchio
    if not cand or len(cand) > 40 or cand.lower() in _GENERIC_TITLES or _TITLE_NOISE.search(cand):
        return None
    # Un percorso ("/login.html") o una frase che comincia con una parola generica
    # ("Login Requested resource...") e' una schermata, non un nome.
    first = re.split(r"[\s_]+", cand.lower())[0]
    if "/" in cand or first in _GENERIC_TITLES or first in _GENERIC_FIRST:
        return None
    return cand


def cn_host(subject: str | None) -> str | None:
    """Nome host dal soggetto di un certificato ("commonName=pve.local/O=..."), solo se
    e' un nome di rete locale (una parola sola o con suffisso .local/.lan/...): un
    dominio internet (tplinkwifi.net) o un certificato jolly (*.example.com) non e' il
    nome del dispositivo."""
    m = re.search(r"commonName=([^/,]+)", subject or "")
    if not m:
        return None
    cn = m.group(1).strip().lower()
    if not cn or cn.startswith("*") or _IP_RE.match(cn):
        return None
    if "." in cn and not cn.endswith(_LOCAL_CN):
        return None
    return cn

_DOMAIN_SUFFIXES = (".local", ".lan", ".home", ".fritz.box", ".localdomain", ".internal", ".home.arpa", ".homenet")
_ESCAPE_RE = re.compile(r"\\(\d{3}|.)")
_IP_RE = re.compile(r"^(ip[-_ ]?)?\d{1,3}([.\-_]\d{1,3}){3}$", re.IGNORECASE)
_MAC_RE = re.compile(r"^([0-9a-f]{2}[:\-]?){5}[0-9a-f]{2}$", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[^0-9A-Za-z]+")
_GENERIC = {"localhost", "unknown", "unnamed", "default", "device", "host", "none", "null", "n/a", "-", "*"}


def _unescape(text: str) -> str:
    """Sequenze di escape del DNS-SD: \\032 = spazio (decimale), \\. = punto."""
    def repl(m: re.Match) -> str:
        g = m.group(1)
        return chr(int(g)) if g.isdigit() and len(g) == 3 else g
    return _ESCAPE_RE.sub(repl, text)


def _looks_generated(token: str) -> bool:
    """Parte di nome che pare un codice generato (esadecimale lungo): id, hash,
    suffissi casuali. Un numero corto ("14", "S23") non lo e'."""
    if not re.fullmatch(r"[0-9a-fA-F]+", token) or len(token) < 8:
        return False
    has_digit = any(c.isdigit() for c in token)
    has_letter = any(c.isalpha() for c in token)
    return len(token) >= 12 or (has_digit and has_letter)


def clean_name(raw: str | None) -> str | None:
    """Nome normalizzato oppure None se non e' un nome utilizzabile."""
    if not raw:
        return None
    name = " ".join(_unescape(str(raw)).split())
    # Un IP dentro il nome ("AFTMM@ES(192.168.1.5)") non fa parte del nome: si toglie.
    name = re.sub(r"[(\[]?\b\d{1,3}(?:\.\d{1,3}){3}\b[)\]]?", "", name).strip(" -_@:,")
    # "<id>@<nome>" (istanza di servizio AirPlay/Whisperplay): conta solo la parte dopo la chiocciola,
    # e solo se e' abbastanza lunga da essere un nome ("ES" non lo e').
    if "@" in name:
        name = name.split("@", 1)[1].strip(" -_@:,")
        if len(name) < 4:
            return None
    low = name.lower()
    for suffix in _DOMAIN_SUFFIXES:
        if low.endswith(suffix):
            name, low = name[: -len(suffix)], low[: -len(suffix)]
    low = name.lower()
    if low.startswith("_") or "._tcp" in low or "._udp" in low or low.endswith(".arpa"):
        return None  # tipo di servizio DNS-SD, non un nome
    # Il codice generato va cercato prima di tagliare il dominio, altrimenti
    # "amzn.dmgr.05837F86..." si ridurrebbe a un "amzn" apparentemente valido.
    if any(_looks_generated(t) for t in _TOKEN_RE.split(name) if t):
        return None
    if " " not in name and "." in name and not _IP_RE.match(name):
        name = name.split(".", 1)[0]  # nome di dominio completo: conta solo l'host
    name = name.strip(" ._-")
    low = name.lower()
    if not name or low in _GENERIC or low.startswith("("):
        return None
    if _IP_RE.match(name) or _MAC_RE.match(name):
        return None
    return name


def pick(candidates: list[tuple[str, str | None]]) -> tuple[str | None, str | None]:
    """(nome, fonte) migliori tra i candidati [(fonte, nome_grezzo)], o (None, None)."""
    best: tuple[int, str, str] | None = None
    for source, raw in candidates:
        name = clean_name(raw)
        if not name:
            continue
        if is_placeholder(name):
            source = "weak"
        rank = PRIORITY.get(source, 0)
        if best is None or rank > best[0]:
            best = (rank, name, source)
    return (best[1], best[2]) if best else (None, None)


# Nome tecnico generato da una integrazione ("shelly1-8CAAB50000A2", "plug_4A3F21"): sigla + codice esadecimale.
_TECHNICAL_RE = re.compile(r"^[a-z][a-z0-9]*[-_][0-9a-f]{6,12}$", re.IGNORECASE)
_PLATFORM_WORDS = {"android", "iphone", "ipad", "ipod", "tablet", "phone", "device", "smartphone"}


def is_placeholder(name: str | None) -> bool:
    """Nome predefinito del sistema: parola di piattaforma sola ("Android", "iPhone") o con un
    codice casuale ("Android_MGDZ1OUL"). Non e' un nome scelto: cede a qualunque altro."""
    if not name:
        return False
    # Anche un nome salvato che oggi non supererebbe la pulizia (es. un'istanza di servizio "ABC@ES").
    return name.strip().lower() in _PLATFORM_WORDS or bool(_PLACEHOLDER_RE.match(name)) or bool(_TECHNICAL_RE.match(name.strip())) or (clean_name(name) is None and not _IP_RE.match(name.strip()))


def is_better(device: dict, new_source: str) -> bool:
    """True se un nome automatico della fonte indicata puo' sostituire quello del
    dispositivo: mai su un nome scelto dall'utente (o di cui non si conosce
    l'origine ed e' diverso dall'IP), si' se il nome e' ancora l'IP o viene da
    una fonte meno affidabile."""
    name = device.get("name")
    if not name or name == device.get("ip"):
        return True
    source = device.get("name_source")
    if source == "user" or (source not in PRIORITY and not is_placeholder(name)):
        return False  # scelto a mano, o nome precedente senza origine: si presume scelto a mano
    if is_placeholder(name):
        source = "weak"  # salvato come "mdns" prima che i segnaposto avessero poco peso
    return PRIORITY[new_source] > PRIORITY[source]
