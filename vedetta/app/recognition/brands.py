"""Device brands. Two levels, like Fing/Fingerbank: the manufacturer of the MAC
PREFIX (vendor: who made the board/chip) and the brand of the PRODUCT
(brand). A Bouffalo Lab or an Espressif is a chip inside someone else's product,
a TP-Link board can sit in a server, Proxmox generates the MACs of VMs: for
this reason "vendor_roles" classifies manufacturers (component, virtual, dual, brand)
and only real brands count as the product brand; for the others the brand
stays unknown until a source on the device itself states it (resolve).

The IEEE registry gives the legal name of the company the prefix
was assigned to ("Hong Kong Bouffalo Lab Limited", "Flextronics
Computing(Suzhou)Co.,Ltd."): to group and sort, the brand
people recognise is needed. Method as in open source scanners (scan-m0de, KillerScan):
a list of "friendly" names on top of the registry, and the more precise sources of the
device itself (UPnP, name, web title, DHCP fingerprint) which take
precedence over the MAC prefix alone.

The rules live in app/data/brands.json (shipped with the app). To add or
fix some without touching the code, just create config/brands.json with the
same keys: the rules there come first and a deploy does not delete them. The file
is re-read by itself when it changes.

Rules created from the interface live in the same file under "rules":
[{"id", "kind": vendor|name|software, "text", "brand"}] (plain text, case-
insensitive). The file also holds "oui_meta" and "auto_update" (update
of the MAC prefix database, see oui_update.py)."""
from ..atomic import write_atomic
import json
import logging
import re
import threading
import uuid
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("dashboard")

_DEFAULTS_PATH = Path(__file__).resolve().parent.parent / "data" / "brands.json"
from ..paths import data_path
_USER_PATH = data_path("brands.json")

_cache: dict = {"stamp": None, "rules": None}
_shipped_missing_told: list = []      # the shipped file is reported once, not at every change of the user's file


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if path == _DEFAULTS_PATH and not _shipped_missing_told:      # the user's file may not exist; the one shipped with the app must
            _shipped_missing_told.append(path)
            logger.warning("Brand rules file %s is missing: no brand is recognised from the shipped rules", path.name)
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Regole marche non lette (%s): %s", path.name, exc)
        return {}


KINDS = ("vendor", "name", "software")
_lock = threading.Lock()


def _valid_rules(user: dict) -> list[dict]:
    """Well-formed interface rules (the file may have been edited by hand)."""
    out = []
    for rule in user.get("rules", []) if isinstance(user.get("rules"), list) else []:
        if (isinstance(rule, dict) and rule.get("kind") in KINDS and isinstance(rule.get("text"), str)
                and isinstance(rule.get("brand"), str) and rule["text"].strip() and rule["brand"].strip()):
            out.append({"id": str(rule.get("id", "")), "kind": rule["kind"],
                        "text": rule["text"].strip(), "brand": rule["brand"].strip()})
    return out


def _write_user(data: dict) -> None:
    """Atomic write of config/brands.json (temporary file + os.replace)."""
    write_atomic(_USER_PATH, lambda f: json.dump(data, f, ensure_ascii=False, indent=2), ".brands-")
    _cache["stamp"] = None  # reload immediately, without waiting for the mtime resolution


def update_user(changes: dict) -> dict:
    """Merges the given keys into the user file preserving all the others."""
    with _lock:
        data = _read(_USER_PATH)
        data.update(changes)
        _write_user(data)
        return data


def list_rules() -> list[dict]:
    return _valid_rules(_read(_USER_PATH))


def add_rule(kind: str, text: str, brand: str) -> dict:
    """Adds the rule; if the kind+text pair already exists it replaces its
    brand. Validation: ValueError("kind"|"text"|"brand")."""
    text, brand = _checked_rule(kind, text, brand)
    with _lock:
        data = _read(_USER_PATH)
        rules = _valid_rules(data)
        _upsert_rule(rules, kind, text, brand)
        for rule in rules:  # missing ids (file edited by hand)
            rule["id"] = rule["id"] or uuid.uuid4().hex[:8]
        data["rules"] = rules
        _write_user(data)
        return data


def _checked_rule(kind: str, text: str, brand: str) -> tuple[str, str]:
    """Stripped (text, brand) of a rule from the interface. ValueError("kind"|"text"|"brand") if invalid."""
    text, brand = (text or "").strip(), (brand or "").strip()
    if kind not in KINDS:
        raise ValueError("kind")
    if not 2 <= len(text) <= 80:
        raise ValueError("text")
    if not 1 <= len(brand) <= 60:
        raise ValueError("brand")
    return text, brand


def _upsert_rule(rules: list[dict], kind: str, text: str, brand: str) -> None:
    """Replaces the brand (and the spelling of the text) of the rule with the same kind and text, ignoring case; otherwise appends a new rule."""
    for rule in rules:
        if rule["kind"] == kind and rule["text"].lower() == text.lower():
            rule["brand"], rule["text"] = brand, text
            return
    rules.append({"id": uuid.uuid4().hex[:8], "kind": kind, "text": text, "brand": brand})


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


def _rules() -> dict:
    stamp = _stamp()
    if _cache["stamp"] == stamp and _cache["rules"] is not None:
        return _cache["rules"]
    base, user = _read(_DEFAULTS_PATH), _read(_USER_PATH)
    rules = _merge_rules(base, user)
    _cache.update(stamp=stamp, rules=rules)
    return rules


def _stamp() -> tuple:
    out = []
    for path in (_DEFAULTS_PATH, _USER_PATH):
        try:
            out.append(path.stat().st_mtime)
        except OSError:
            out.append(None)
    return tuple(out)


def _merge_rules(base: dict, user: dict) -> dict:
    """The lookup tables from the shipped rules and the user's file. User rules come first: the first one that matches wins."""
    ui = _interface_rules(user)
    return {
        "aliases": tuple((f.lower(), b) for f, b in ui["vendor"] + user.get("aliases", []) + base.get("aliases", [])),
        "name_hints": _compile(ui["name"] + user.get("name_hints", []) + base.get("name_hints", [])),
        "software_hints": _compile(ui["software"] + user.get("software_hints", []) + base.get("software_hints", [])),
        "os_family_brand": {**base.get("os_family_brand", {}), **user.get("os_family_brand", {})},
        "vendor_roles": _role_words(base, user),
        "model_hints": _model_patterns(base, user),
        "battery_hints": _compile(user.get("battery_hints", []) + base.get("battery_hints", [])),
        "bridge_software": tuple(w.lower() for w in base.get("bridge_software", []) + user.get("bridge_software", [])),
        "phone_only": tuple(w.lower() for w in base.get("phone_only_brands", []) + user.get("phone_only_brands", [])),
        "strip_words": set(base.get("strip_words", [])) | {w.lower() for w in user.get("strip_words", [])},
        "places": set(base.get("strip_leading_places", [])) | {w.lower() for w in user.get("strip_leading_places", [])},
    }


def _compile(pairs: list) -> tuple[tuple[re.Pattern, str], ...]:
    compiled = []
    for pattern, brand in pairs:
        try:
            compiled.append((re.compile(pattern), brand))
        except re.error as exc:
            logger.warning("Espressione marca non valida %r: %s", pattern, exc)
    return tuple(compiled)


def _interface_rules(user: dict) -> dict[str, list]:
    """Rules created from the interface ("rules"), by kind: plain text, never regex (vendor text is lower case, name and software are escaped)."""
    ui = {"vendor": [], "name": [], "software": []}
    for rule in _valid_rules(user):
        text = rule["text"].lower()
        ui[rule["kind"]].append((text if rule["kind"] == "vendor" else re.escape(text), rule["brand"]))
    return ui


def _role_words(base: dict, user: dict) -> dict:
    """Lower-case manufacturer words per role; the user's come first."""
    return {r: tuple(w.lower() for w in (user.get("vendor_roles", {}).get(r, []) + base.get("vendor_roles", {}).get(r, [])))
            for r in ROLES}


def _model_patterns(base: dict, user: dict) -> dict:
    """Compiled model patterns per class (fixed, mobile, laptop); the user's come first."""
    return {k: tuple(re.compile(x) for x in user.get("model_hints", {}).get(k, []) + base.get("model_hints", {}).get(k, []))
            for k in ("fixed", "mobile", "laptop")}


def normalize_brand(name: str | None) -> str | None:
    """Legal or declared name -> recognisable brand."""
    if not name:
        return None
    low = name.lower()
    for fragment, brand in _rules()["aliases"]:
        if fragment in low:
            return brand
    return _clean(name)


def _clean(name: str) -> str:
    rules = _rules()
    words = re.sub(r"[(),.]", " ", name).split()
    while words and words[0].lower() in rules["places"]:
        words.pop(0)
    while len(words) > 1 and words[-1].lower() in rules["strip_words"]:
        words.pop()
    return " ".join(words) or name


def is_phone_only(brand: str | None) -> bool:
    """True for a maker that only sells phones (data/brands.json, "phone_only_brands"): its brand alone says "phone"."""
    low = (brand or "").lower()
    return bool(low) and any(w in low for w in _rules()["phone_only"])


def mobile_name_words() -> tuple:
    """Words that in a device name say "phone or tablet" (data/brands.json and the user's file, "mobile_name_words"); read again when one of the files changes."""
    return _mobile_name_words(_stamp())


@lru_cache(maxsize=4)
def _mobile_name_words(stamp: tuple) -> tuple:
    base, user = _read(_DEFAULTS_PATH), _read(_USER_PATH)
    return tuple(w.lower() for w in base.get("mobile_name_words", []) + user.get("mobile_name_words", []))


def known_brand(name: str | None) -> str | None:
    """Brand only if the name matches an entry in the names table; free
    names (e.g. the author of a piece of software) do not count."""
    low = (name or "").lower()
    return next((brand for fragment, brand in _rules()["aliases"] if fragment in low), None)


ROLES = ("component", "virtual", "dual")


def vendor_role(vendor: str | None) -> str | None:
    """Role of the MAC prefix manufacturer ("vendor_roles" table): component
    (chip/module/board: the product belongs to others), virtual (virtual board of a
    hypervisor), dual (makes boards and finished products), brand (a real brand).
    None if there is no manufacturer. The ALREADY normalised name is used, so a
    user rule that renames the manufacturer (e.g. Bouffalo -> Tuya) changes
    its role too."""
    if not vendor:
        return None
    low = vendor.lower()
    table = _rules()["vendor_roles"]
    return next((role for role in ROLES if any(fragment in low for fragment in table[role])), "brand")


def is_bridge(model: str | None) -> bool:
    """True if the mDNS model is a proxy/bridge software (data/brands.json, bridge_software)."""
    m = (model or "").strip().lower()
    return bool(m) and any(b in m for b in (_rules().get("bridge_software") or ()))


def match_model(texts) -> str | None:
    """Class of the announced model (mobile | laptop | fixed) from the
    "model_hints" table; the first class that matches any text wins,
    with "fixed" checked first (a Mac mini is not a laptop)."""
    table = _rules()["model_hints"]
    hints = []
    for kind in ("fixed", "mobile", "laptop"):
        hints += [(p, kind) for p in table[kind]]
    return _first_match(texts, hints)


def battery_hint(texts) -> str | None:
    """"yes"/"no" if a text (model, SNMP, web title) is recognised by the
    "battery_hints" table as a fixed battery-powered device (sensor, UPS)."""
    return _first_match(texts, _rules()["battery_hints"])


def resolve(oui_brand: str | None, *, names: list[str], upnp_manufacturer: str | None = None,
            declared: list[str] | tuple = (), web_text: str | None = None, os_family: str | None = None,
            is_gateway: bool = False) -> dict:
    """PRODUCT brand with source and confidence. The MAC prefix says who
    made the network board, not the product brand (Fing and Fingerbank keep
    them separate: "vendor" of the board, "brand/device" of the product), so it is
    the last resort and counts only if the manufacturer is truly a brand.
    Sources, from the most direct: dhcp (iOS/macOS fingerprint) > name (name, mDNS
    model, hostname) > web (title/Server/services) > declared (manufacturer declared
    via UPnP/mDNS, only if it is a brand in the names table) > oui.
    For oui: brand if role=brand; dual only if it is the gateway (a router has the
    board of its own brand); component and virtual never (brand=None).
    Returns {brand, source, confidence (high|medium|low|None), role}."""
    rules = _rules()
    role = vendor_role(oui_brand)
    if os_family in rules["os_family_brand"]:
        return _verdict(role, rules["os_family_brand"][os_family], "dhcp", "high")
    brand = _first_match(names, rules["name_hints"], _NO_HINT)
    if brand is not _NO_HINT:
        return _verdict(role, brand, "name", "high")
    brand = _first_match([web_text], rules["software_hints"], _NO_HINT)
    if brand is not _NO_HINT:
        return _verdict(role, brand, "web", "high")
    # The declared "manufacturer" (UPnP, mDNS) is that of the responding service,
    # not always of the device (a router with MiniDLNA declares the author of the
    # software): accepted only if it is a brand in the names table.
    brand = _declared_brand((upnp_manufacturer, *declared))
    if brand:
        return _verdict(role, brand, "declared", "medium")
    if _oui_counts(oui_brand, role, is_gateway):
        return _verdict(role, oui_brand, "oui", "medium" if role == "brand" else "low")
    return _verdict(role, None, None, None)


def _verdict(role: str | None, brand: str | None, source: str | None, confidence: str | None) -> dict:
    return {"brand": brand, "source": source, "confidence": confidence, "role": role}


_NO_HINT = object()


def _first_match(texts, hints, default=None):
    """The answer of the first hint, [(pattern, answer)], whose pattern matches a text (lower-cased; None and empty texts are skipped); `default` if nothing matches (an empty answer is still an answer)."""
    for text in texts:
        low = (text or "").lower()
        if not low:
            continue
        for pattern, answer in hints:
            if pattern.search(low):
                return answer
    return default


def _declared_brand(values) -> str | None:
    """First declared manufacturer that is a brand in the names table."""
    for value in values:
        brand = known_brand(value)
        if brand:
            return brand
    return None


def _oui_counts(oui_brand: str | None, role: str | None, is_gateway: bool) -> bool:
    """The MAC manufacturer is accepted as the product brand: a real brand, or a "dual" one on the gateway."""
    return bool(oui_brand) and (role == "brand" or (role == "dual" and is_gateway))


def refine_brand(oui_brand: str | None, *, names: list[str], upnp_manufacturer: str | None = None,
                 web_text: str | None = None, os_family: str | None = None,
                 declared: list[str] | tuple = (), is_gateway: bool = False) -> str | None:
    """Only the brand from resolve() (see there for sources and priority)."""
    return resolve(oui_brand, names=names, upnp_manufacturer=upnp_manufacturer, declared=declared,
                   web_text=web_text, os_family=os_family, is_gateway=is_gateway)["brand"]
