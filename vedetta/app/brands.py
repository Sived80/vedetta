"""Marche dei dispositivi. Due livelli, come Fing/Fingerbank: il produttore del
PREFISSO MAC (vendor: chi ha fatto la scheda/il chip) e la marca del PRODOTTO
(brand). Un Bouffalo Lab o un Espressif e' un chip dentro un prodotto di altri,
una scheda TP-Link puo' stare in un server, Proxmox genera i MAC delle VM: per
questo "vendor_roles" classifica i produttori (component, virtual, dual, brand)
e solo i brand veri valgono come marca del prodotto; per gli altri la marca
resta sconosciuta finche' una fonte del dispositivo non la dice (resolve).

Il registro IEEE da' il nome legale dell'azienda a cui
e' stato assegnato il prefisso ("Hong Kong Bouffalo Lab Limited", "Flextronics
Computing(Suzhou)Co.,Ltd."): per raggruppare e ordinare serve la marca che la
gente riconosce. Metodo come negli scanner open source (scan-m0de, KillerScan):
un elenco di nomi "amichevoli" sopra il registro, e le fonti piu' precise del
dispositivo stesso (UPnP, nome, titolo web, impronta DHCP) che hanno la
precedenza sul solo prefisso del MAC.

Le regole stanno in app/data/brands.json (fornite con l'app). Per aggiungerne o
correggerne senza toccare il codice basta creare config/brands.json con le
stesse chiavi: le regole li' vengono prima e un deploy non le cancella. Il file
si rilegge da solo quando cambia.

Le regole create dall'interfaccia stanno nello stesso file sotto "rules":
[{"id", "kind": vendor|name|software, "text", "brand"}] (testo semplice, senza
maiuscole). Nel file ci sono anche "oui_meta" e "auto_update" (aggiornamento
del database dei prefissi MAC, vedi oui_update.py)."""
import json
import logging
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path

logger = logging.getLogger("dashboard")

_DEFAULTS_PATH = Path(__file__).resolve().parent / "data" / "brands.json"
from .paths import data_path
_USER_PATH = data_path("brands.json")

_cache: dict = {"stamp": None, "rules": None}


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Regole marche non lette (%s): %s", path.name, exc)
        return {}


KINDS = ("vendor", "name", "software")
_lock = threading.Lock()


def _valid_rules(user: dict) -> list[dict]:
    """Regole da interfaccia ben formate (il file puo' essere stato toccato a mano)."""
    out = []
    for rule in user.get("rules", []) if isinstance(user.get("rules"), list) else []:
        if (isinstance(rule, dict) and rule.get("kind") in KINDS and isinstance(rule.get("text"), str)
                and isinstance(rule.get("brand"), str) and rule["text"].strip() and rule["brand"].strip()):
            out.append({"id": str(rule.get("id", "")), "kind": rule["kind"],
                        "text": rule["text"].strip(), "brand": rule["brand"].strip()})
    return out


def _write_user(data: dict) -> None:
    """Scrittura atomica di config/brands.json (file temporaneo + os.replace)."""
    _USER_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=_USER_PATH.parent, prefix=".brands-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _USER_PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    _cache["stamp"] = None  # ricarica subito, senza aspettare la risoluzione dell'mtime


def update_user(changes: dict) -> dict:
    """Unisce le chiavi date nel file utente preservando tutte le altre."""
    with _lock:
        data = _read(_USER_PATH)
        data.update(changes)
        _write_user(data)
        return data


def list_rules() -> list[dict]:
    return _valid_rules(_read(_USER_PATH))


def add_rule(kind: str, text: str, brand: str) -> dict:
    """Aggiunge la regola; se esiste gia' la coppia kind+testo ne sostituisce la
    marca. Validazione: ValueError("kind"|"text"|"brand")."""
    text, brand = (text or "").strip(), (brand or "").strip()
    if kind not in KINDS:
        raise ValueError("kind")
    if not 2 <= len(text) <= 80:
        raise ValueError("text")
    if not 1 <= len(brand) <= 60:
        raise ValueError("brand")
    with _lock:
        data = _read(_USER_PATH)
        rules = _valid_rules(data)
        for rule in rules:
            if rule["kind"] == kind and rule["text"].lower() == text.lower():
                rule["brand"], rule["text"] = brand, text
                break
        else:
            rules.append({"id": uuid.uuid4().hex[:8], "kind": kind, "text": text, "brand": brand})
        for rule in rules:  # id mancanti (file modificato a mano)
            rule["id"] = rule["id"] or uuid.uuid4().hex[:8]
        data["rules"] = rules
        _write_user(data)
        return data


def delete_rule(rule_id: str) -> bool:
    with _lock:
        data = _read(_USER_PATH)
        rules = _valid_rules(data)
        kept = [r for r in rules if r["id"] != rule_id]
        if len(kept) == len(rules):
            return False
        data["rules"] = kept
        _write_user(data)
        return True


def _stamp() -> tuple:
    out = []
    for path in (_DEFAULTS_PATH, _USER_PATH):
        try:
            out.append(path.stat().st_mtime)
        except OSError:
            out.append(None)
    return tuple(out)


def _compile(pairs: list) -> tuple[tuple[re.Pattern, str], ...]:
    compiled = []
    for pattern, brand in pairs:
        try:
            compiled.append((re.compile(pattern), brand))
        except re.error as exc:
            logger.warning("Espressione marca non valida %r: %s", pattern, exc)
    return tuple(compiled)


def _rules() -> dict:
    stamp = _stamp()
    if _cache["stamp"] == stamp and _cache["rules"] is not None:
        return _cache["rules"]
    base, user = _read(_DEFAULTS_PATH), _read(_USER_PATH)
    # Regole create dall'interfaccia ("rules"): testo semplice, mai regex.
    ui = {"vendor": [], "name": [], "software": []}
    for rule in _valid_rules(user):
        text = rule["text"].lower()
        ui[rule["kind"]].append((text if rule["kind"] == "vendor" else re.escape(text), rule["brand"]))
    # Le regole dell'utente vanno prima: la prima che corrisponde vince.
    rules = {
        "aliases": tuple((f.lower(), b) for f, b in ui["vendor"] + user.get("aliases", []) + base.get("aliases", [])),
        "name_hints": _compile(ui["name"] + user.get("name_hints", []) + base.get("name_hints", [])),
        "software_hints": _compile(ui["software"] + user.get("software_hints", []) + base.get("software_hints", [])),
        "os_family_brand": {**base.get("os_family_brand", {}), **user.get("os_family_brand", {})},
        "vendor_roles": {r: tuple(w.lower() for w in (user.get("vendor_roles", {}).get(r, []) + base.get("vendor_roles", {}).get(r, [])))
                         for r in ROLES},
        "model_hints": {k: tuple(re.compile(x) for x in user.get("model_hints", {}).get(k, []) + base.get("model_hints", {}).get(k, []))
                        for k in ("fixed", "mobile", "laptop")},
        "battery_hints": _compile(user.get("battery_hints", []) + base.get("battery_hints", [])),
        "bridge_software": tuple(w.lower() for w in base.get("bridge_software", []) + user.get("bridge_software", [])),
        "strip_words": set(base.get("strip_words", [])) | {w.lower() for w in user.get("strip_words", [])},
        "places": set(base.get("strip_leading_places", [])) | {w.lower() for w in user.get("strip_leading_places", [])},
    }
    _cache.update(stamp=stamp, rules=rules)
    return rules


def _clean(name: str) -> str:
    rules = _rules()
    words = re.sub(r"[(),.]", " ", name).split()
    while words and words[0].lower() in rules["places"]:
        words.pop(0)
    while len(words) > 1 and words[-1].lower() in rules["strip_words"]:
        words.pop()
    return " ".join(words) or name


def normalize_brand(name: str | None) -> str | None:
    """Nome legale o dichiarato -> marca riconoscibile."""
    if not name:
        return None
    low = name.lower()
    for fragment, brand in _rules()["aliases"]:
        if fragment in low:
            return brand
    return _clean(name)


def known_brand(name: str | None) -> str | None:
    """Marca solo se il nome corrisponde a una voce della tabella dei nomi; i nomi
    liberi (es. l'autore di un software) non contano."""
    low = (name or "").lower()
    for fragment, brand in _rules()["aliases"]:
        if fragment in low:
            return brand
    return None


ROLES = ("component", "virtual", "dual")


def vendor_role(vendor: str | None) -> str | None:
    """Ruolo del produttore del prefisso MAC (tabella "vendor_roles"): component
    (chip/modulo/scheda: il prodotto e' di altri), virtual (scheda virtuale di un
    hypervisor), dual (fa schede e prodotti finiti), brand (una marca vera).
    None se non c'e' un produttore. Si guarda il nome GIA' normalizzato, cosi' una
    regola dell'utente che rinomina il produttore (es. Bouffalo -> Tuya) ne cambia
    anche il ruolo."""
    if not vendor:
        return None
    low = vendor.lower()
    table = _rules()["vendor_roles"]
    for role in ROLES:
        if any(fragment in low for fragment in table[role]):
            return role
    return "brand"


def is_bridge(model: str | None) -> bool:
    """True se il modello mDNS e' un software proxy/bridge (data/brands.json, bridge_software)."""
    m = (model or "").strip().lower()
    return bool(m) and any(b in m for b in (_rules().get("bridge_software") or ()))


def match_model(texts) -> str | None:
    """Classe del modello annunciato (mobile | laptop | fixed) dalla tabella
    "model_hints"; la prima classe che corrisponde a un testo qualsiasi vince,
    con "fixed" controllata per prima (un Mac mini non e' un portatile)."""
    table = _rules()["model_hints"]
    for text in texts:
        low = (text or "").lower()
        if not low:
            continue
        for kind in ("fixed", "mobile", "laptop"):
            if any(p.search(low) for p in table[kind]):
                return kind
    return None


def battery_hint(texts) -> str | None:
    """"yes"/"no" se un testo (modello, SNMP, titolo web) e' riconosciuto dalla
    tabella "battery_hints" come apparecchio fisso a batteria (sensore, UPS)."""
    for text in texts:
        low = (text or "").lower()
        if not low:
            continue
        for pattern, answer in _rules()["battery_hints"]:
            if pattern.search(low):
                return answer
    return None


def resolve(oui_brand: str | None, *, names: list[str], upnp_manufacturer: str | None = None,
            declared: list[str] | tuple = (), web_text: str | None = None, os_family: str | None = None,
            is_gateway: bool = False) -> dict:
    """Marca del PRODOTTO con fonte e confidenza. Il prefisso MAC dice chi ha
    fatto la scheda di rete, non la marca del prodotto (Fing e Fingerbank li
    tengono separati: "vendor" della scheda, "brand/device" del prodotto), quindi e'
    l'ultima risorsa e vale solo se il produttore e' davvero una marca.
    Fonti, dalla piu' diretta: dhcp (impronta iOS/macOS) > name (nome, modello
    mDNS, hostname) > web (titolo/Server/servizi) > declared (produttore dichiarato
    via UPnP/mDNS, solo se e' una marca della tabella dei nomi) > oui.
    Per l'oui: marca se role=brand; dual solo se e' il gateway (un router ha la
    scheda della propria marca); component e virtual mai (brand=None).
    Ritorna {brand, source, confidence (high|medium|low|None), role}."""
    rules = _rules()
    role = vendor_role(oui_brand)

    def done(brand, source, confidence):
        return {"brand": brand, "source": source, "confidence": confidence, "role": role}

    if os_family in rules["os_family_brand"]:
        return done(rules["os_family_brand"][os_family], "dhcp", "high")
    for name in names:
        low = (name or "").lower()
        for pattern, brand in rules["name_hints"]:
            if pattern.search(low):
                return done(brand, "name", "high")
    if web_text:
        low = web_text.lower()
        for pattern, brand in rules["software_hints"]:
            if pattern.search(low):
                return done(brand, "web", "high")
    # Il "produttore" dichiarato (UPnP, mDNS) e' quello del servizio che risponde,
    # non sempre del dispositivo (un router con MiniDLNA dichiara l'autore del
    # software): si accetta solo se e' una marca della tabella dei nomi.
    for value in (upnp_manufacturer, *declared):
        brand = known_brand(value)
        if brand:
            return done(brand, "declared", "medium")
    if oui_brand and (role == "brand" or (role == "dual" and is_gateway)):
        return done(oui_brand, "oui", "medium" if role == "brand" else "low")
    return done(None, None, None)


def refine_brand(oui_brand: str | None, *, names: list[str], upnp_manufacturer: str | None = None,
                 web_text: str | None = None, os_family: str | None = None,
                 declared: list[str] | tuple = (), is_gateway: bool = False) -> str | None:
    """Solo la marca di resolve() (vedi li' per fonti e priorita')."""
    return resolve(oui_brand, names=names, upnp_manufacturer=upnp_manufacturer, declared=declared,
                   web_text=web_text, os_family=os_family, is_gateway=is_gateway)["brand"]
