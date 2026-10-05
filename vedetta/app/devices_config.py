import os
import tempfile

import yaml

from .paths import DATA_DIR as CONFIG_DIR
DEVICES_PATH = CONFIG_DIR / "devices.yaml"


def _save(data: dict) -> None:
    """Scrittura atomica: file temporaneo nella stessa cartella + os.replace.
    Un crash o un'interruzione a meta' scrittura lascia intatto il file
    precedente invece di un YAML troncato che farebbe perdere tutti i
    dispositivi."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CONFIG_DIR, prefix=".devices-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, DEVICES_PATH)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_devices() -> list[dict]:
    if not DEVICES_PATH.exists():
        return []
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    return data.get("devices", [])


def add_devices(new_devices: list[dict]) -> list[dict]:
    """Aggiunge dispositivi trovati con lo scanner, evitando duplicati per IP o id."""
    data = {}
    if DEVICES_PATH.exists():
        data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    existing = data.setdefault("devices", [])
    existing_ips = {d["ip"] for d in existing}
    existing_ids = {d["id"] for d in existing}

    added = []
    for nd in new_devices:
        if nd["ip"] in existing_ips:
            continue
        device_id = nd.get("id") or f"scan-{nd['ip'].replace('.', '-')}"
        base_id = device_id
        n = 2
        while device_id in existing_ids:
            device_id = f"{base_id}-{n}"
            n += 1
        entry = {"id": device_id, "ip": nd["ip"], "port": nd.get("port", 80), "adapter": nd.get("adapter", "generic")}
        if nd.get("name"):
            entry["name"] = nd["name"]
        if nd.get("scan_info"):
            entry["scan_info"] = nd["scan_info"]
        if nd.get("name_source"):
            entry["name_source"] = nd["name_source"]
        existing.append(entry)
        existing_ids.add(device_id)
        existing_ips.add(nd["ip"])
        added.append(entry)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _save(data)
    return added


def update_device(device_id: str, new_name: str, new_port: int | None = None, mobile: bool | None = None) -> dict | None:
    """mobile=None lascia decidere l'euristica sul nome (vedi probe.py); True/False
    e' una scelta esplicita dell'utente, che vince sempre sull'euristica e resta
    valida anche se il nome cambia in seguito (a differenza di un riconoscimento
    basato solo su parole chiave nel nome, che si perde appena il dispositivo ha
    un nome generico/IP invece di uno con "iPhone"/"Pixel"/ecc.)."""
    if not DEVICES_PATH.exists():
        return None
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    for d in data.get("devices", []):
        if d["id"] == device_id:
            if new_name != d.get("name"):
                d["name_source"] = "user"  # scelto a mano: le scansioni non lo toccano piu'
            d["name"] = new_name
            if new_port is not None:
                d["port"] = new_port
            if mobile is None:
                d.pop("mobile", None)
            else:
                d["mobile"] = mobile
            _save(data)
            return d
    return None


OVERRIDE_FIELDS = ("brand_user", "type_user", "wol_ok", "ha_share")


def set_override(device_id: str, field: str, value: str | None) -> dict | None:
    """Marca o tipo scelti a mano dall'utente: restano finche' non li si rimette su automatico
    (value=None) e nessuna scansione li cambia."""
    if field not in OVERRIDE_FIELDS or not DEVICES_PATH.exists():
        return None
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    for d in data.get("devices", []):
        if d["id"] == device_id:
            if value:
                d[field] = value
            else:
                d.pop(field, None)
            _save(data)
            return d
    return None


def update_ip(device_id: str, new_ip: str) -> str | None:
    """Sposta il dispositivo su un nuovo IP (stesso apparecchio che ha cambiato indirizzo).
    Ritorna il vecchio IP, None se il dispositivo non c'e' o l'IP e' gia' di un altro."""
    if not DEVICES_PATH.exists():
        return None
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    devices = data.get("devices", [])
    if any(d.get("ip") == new_ip for d in devices):
        return None
    for d in devices:
        if d["id"] == device_id:
            old = d["ip"]
            d["ip"] = new_ip
            if d.get("name") == old:  # il nome era l'IP stesso
                d["name"] = new_ip
            _save(data)
            return old
    return None


def update_auto_name(device_id: str, name: str, source: str, force: bool = False) -> bool:
    """Sostituisce un nome automatico con uno migliore (vedi naming.is_better); il
    controllo si rifa' qui sul file, per non scavalcare una rinomina fatta nel frattempo."""
    from . import naming
    if not DEVICES_PATH.exists():
        return False
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    for d in data.get("devices", []):
        if d["id"] == device_id:
            if (not force and not naming.is_better(d, source)) or d.get("name") == name or d.get("name_source") == "user":
                return False
            d["name"], d["name_source"] = name, source
            _save(data)
            return True
    return False


def update_scan_info(device_id: str, scan_info: dict) -> dict | None:
    """Salva il risultato dell'ultima scansione approfondita (sistema operativo,
    servizi, titolo pagina) cosi' resta disponibile senza dover riscansionare
    ad ogni caricamento della dashboard."""
    if not DEVICES_PATH.exists():
        return None
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    for d in data.get("devices", []):
        if d["id"] == device_id:
            if scan_info:
                d["scan_info"] = scan_info
            else:
                d.pop("scan_info", None)
            _save(data)
            return d
    return None


def remove_device(device_id: str) -> bool:
    if not DEVICES_PATH.exists():
        return False
    data = yaml.safe_load(DEVICES_PATH.read_text(encoding="utf-8")) or {}
    devices = data.get("devices", [])
    remaining = [d for d in devices if d["id"] != device_id]
    if len(remaining) == len(devices):
        return False
    data["devices"] = remaining
    _save(data)
    return True
