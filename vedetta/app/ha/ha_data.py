"""Data for the Home Assistant-style dashboard (/ha): inferred device type,
compact format for the UI, summary, event log.

The calculation functions are pure (they take dicts and return
dicts): they can be tested on their own (tests/check_ha_api.py) without starting the
service. The HTTP calls live in routes/ha.py."""
from typing import NamedTuple
from pathlib import Path

from ..recognition import brand_logo
from ..storage import devices_config
from .. import i18n
from . import identity_shift
from ..storage.history import History, history
from .ha_type_evidence import MARGIN_BELOW, MIN_TYPE_SCORE, TYPE_ORDER, W_BRAND, W_DECLARED, W_PLATFORM_MAX, W_PORTS_MAX, W_PORT_GUESS, W_ROLE, W_SERVICE, W_WORD, _FAMILY_PORT, _FAMILY_SERVICE, _FAMILY_UPNP, _MDNS_TYPE, _MERGED_GROUPS, _MODEL_WORDS, _PC_PORTS, _PLATFORM_KINDS, _PORT_RE, _PORT_SHARED, _PORT_TYPE, _TOKEN_RE, _UPNP_TYPE, _aggregate, _blob, _blob_extra_texts, _blob_name_parts, _blob_port_labels, _build_kind, _declared_services, _declares_onvif, _ha_integrations, _ha_table_cache, _has_network_role, _kinds, _kinds_cache, _model_text, _read_kind_rows, _split_words, _word_pts, type_evidence, type_scores  # noqa: F401


def icon_for(device: dict, adapter: str | None = None, kind: str | None = None) -> str | None:
    """Name of the MDI icon best suited to the device: the one of the type (data/device_kinds.json)
    with the most points within the chosen category; None = the category icon."""
    group = kind or infer_type(device, adapter)
    kinds_out: dict[str, int] = {}
    type_scores(device, adapter, kinds_out)
    best, best_pts = None, 0
    for kd in _kinds():
        if kd["group"] != group:
            continue
        pts = kinds_out.get(kd["id"], 0)
        if pts > best_pts:
            best, best_pts = kd["icon"], pts
    return best


def kind_is_product(kind_id: str | None) -> bool:
    """True for the types that are a specific product (Home Assistant, Raspberry Pi): the name
    is the type itself, without a brand in front."""
    return any(kd["id"] == kind_id and kd.get("product") for kd in _kinds())


def best_kind(device: dict, adapter: str | None = None) -> str | None:
    """Id of the device type (data/device_kinds.json) with the most points, in the chosen category."""
    group = infer_type(device, adapter)
    kinds_out: dict[str, int] = {}
    type_scores(device, adapter, kinds_out)
    best, best_pts = None, 0
    for kd in _kinds():
        if kd["group"] == group and kinds_out.get(kd["id"], 0) > best_pts:
            best, best_pts = kd["id"], kinds_out[kd["id"]]
    return best


def infer_type(device: dict, adapter: str | None = None) -> str:
    """Device category by score (type_scores). The is_mobile flag (user choice
    or the probe "mobile" score) wins over everything."""
    if device.get("is_mobile"):
        return "phone"
    scores = type_scores(device, adapter)
    if not scores:
        return "generic"
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], TYPE_ORDER.index(kv[0]) if kv[0] in TYPE_ORDER else 99))
    best = ranked[0]
    if best[1] < MIN_TYPE_SCORE:
        return "generic"
    # Two tied categories with weak clues: no random pick (like Nmap when the two best are close).
    if len(ranked) > 1 and best[1] < MARGIN_BELOW and ranked[1][1] >= MIN_TYPE_SCORE and best[1] - ranked[1][1] < 1:
        return "generic"
    return best[0]


def effective_type(device: dict, cfg: dict | None = None) -> str:
    """Category chosen by hand (cfg["type_user"]) or the scored one."""
    cfg = cfg or {}
    chosen = cfg.get("type_user")
    if chosen in TYPE_ORDER or chosen == "generic":
        return chosen
    return infer_type(device, cfg.get("adapter"))


# ---- configuration (adapter, "mobile" choice) with file cache ----
_cfg_cache: dict = {"mtime": None, "map": {}}


def config_map() -> dict[str, dict]:
    """{id: configuration} from devices.yaml, re-read only if the file changes
    (needed to know the adapter and manual choice of each device without
    reading the disk on every event)."""
    try:
        mtime = devices_config.DEVICES_PATH.stat().st_mtime
    except OSError:
        return {}
    if _cfg_cache["mtime"] != mtime:
        try:
            _cfg_cache["map"] = {d["id"]: d for d in devices_config.load_devices()}
            _cfg_cache["mtime"] = mtime
        except Exception:
            return _cfg_cache["map"]
    return _cfg_cache["map"]


def compact_device(device: dict, cfg: dict | None = None) -> dict:
    """Device from the shared state -> compact format for the /ha UI.
    Texts and field names in the current language (i18n.use)."""
    cfg = cfg or {}
    logo = brand_logo.logo_for(device.get("brand"))
    extra = device.get("extra") or {}
    _t = effective_type(device, cfg)
    online = bool(device.get("online"))
    return {
        "id": device["id"],
        "name": device.get("name") or device.get("ip"),
        "ip": device.get("ip"),
        "port": device.get("port", 80),
        "mac": device.get("mac"),
        # Two levels: vendor = MAC manufacturer (chip/board), brand = product
        # brand (None if unknown); brand_source/confidence say where it comes from.
        "vendor": device.get("vendor"),
        "vendor_role": device.get("vendor_role"),
        "brand": device.get("brand"),
        "brand_source": device.get("brand_source"),
        "brand_confidence": device.get("brand_confidence"),
        "brand_evidence": device.get("brand_evidence"),
        "brand_declared": device.get("brand_declared"),
        **_logo_fields(logo),
        # battery: "yes" | "no" | None (unknown), with the source; a battery-powered
        # network device (sensor) is not "mobile".
        "battery": device.get("battery"),
        "battery_source": device.get("battery_source"),
        "type": _t,
        "icon": icon_for(device, cfg.get("adapter"), _t),
        "is_mobile": bool(device.get("is_mobile")),
        "mobile_mode": _mobile_mode(cfg.get("mobile")),
        "name_source": cfg.get("name_source"),
        "wol_ok": bool(cfg.get("wol_ok")),
        "ha_share": bool(cfg.get("ha_share")),
        "type_user": cfg.get("type_user"),
        "brand_user": cfg.get("brand_user"),
        "focus": bool(cfg.get("focus")),
        "focus_note": cfg.get("focus_note"),
        "online": online,
        "last_seen": None if online else device.get("last_seen"),
        "uptime": device.get("uptime"),
        "signal": _signal(device),
        "latency_ms": device.get("latency_ms"),
        "latency_color": device.get("latency_color"),
        "ports": _port_rows(device),
        "url": device.get("url"),
        "title": extra.get("title"),
        "scanned_at": device.get("scanned_at"),
        "web_open": device.get("web_open"),
        "deep_empty_at": device.get("deep_empty_at"),
        "attrs": _extra_attrs(extra) + identity_shift.attrs_for(device["id"], i18n.t),
    }


def _signal(device: dict) -> dict | None:
    kind, value = device.get("signal_kind"), device.get("signal_value")
    if kind not in ("wifi", "lan") or value is None:
        return None
    quality = device.get("signal_label")
    band = device.get("signal_band")
    if kind == "wifi":
        display = f"{value} dBm" + (f" · {band}" if band else "")
    else:
        display = str(value)
    return {
        "kind": kind, "value": value, "band": band, "display": display,
        "quality": quality, "text": i18n.t("signal." + quality) if quality else None,
        "color": device.get("signal_color"),
    }


def _logo_fields(logo: dict | None) -> dict:
    """Logo of the brand shown now (None if it has none): worked out every time, never stored."""
    return {"logo": logo and logo["id"], "logo_color": logo and logo["color"]}


def _mobile_mode(mobile_cfg) -> str:
    """"auto" = the name/scans decide; "yes"/"no" = choice made by hand."""
    return "auto" if mobile_cfg is None else ("yes" if mobile_cfg else "no")


def _port_rows(device: dict) -> list[dict]:
    return [{"label": p.get("label"), "category": p.get("category") or "other", "confirmed": bool(p.get("confirmed"))}
            for p in device.get("scanned_ports") or []]


def _extra_attrs(extra: dict) -> list[dict]:
    """The extra facts of the device as labelled rows (vendor and brand are shown elsewhere)."""
    return [{"key": k, "label": i18n.t_or("extra." + k, k), "value": str(v)}
            for k, v in extra.items() if k not in ("vendor", "brand") and v not in (None, "")]


def compact_all(devices: list[dict]) -> list[dict]:
    cfg = config_map()
    return [compact_device(d, cfg.get(d["id"])) for d in devices]


def build_summary(devices: list[dict], poll: dict, activity: dict, new_devices: dict, rev: int = 0) -> dict:
    """Counts, brands, types and search status. Takes the devices
    from the shared state (not compact): it is pure, with no disk access."""
    return _assemble_summary(devices, rev, _tally_brands_and_types(devices), poll, new_devices, activity)


class _Tally(NamedTuple):
    """What is counted from the devices: how many are online, the mobile ones, the devices per brand, per chip manufacturer (of those with no known brand) and per type."""
    online: int
    mobile: list
    brands: dict
    chips: dict
    types: dict


def _tally_brands_and_types(devices) -> _Tally:
    online = sum(1 for d in devices if d.get("online"))
    mobile = [d for d in devices if d.get("is_mobile")]
    brands: dict[str | None, int] = {}
    chips: dict[str, int] = {}  # MAC manufacturer of devices with no known brand
    types: dict[str, int] = {}
    cfg = config_map()
    for d in devices:
        brand = d.get("brand") or None  # the PRODUCT brand, never the board manufacturer
        brands[brand] = brands.get(brand, 0) + 1
        if brand is None:
            chip = d.get("vendor") or None
            if chip:
                chips[chip] = chips.get(chip, 0) + 1
        kind = effective_type(d, cfg.get(d["id"]))
        types[kind] = types.get(kind, 0) + 1
    return _Tally(online, mobile, brands, chips, types)


def _assemble_summary(devices, rev, tally: _Tally, poll, new_devices, activity) -> dict:
    brand_list = _brand_list(tally.brands)
    total = len(devices)
    online, mobile = tally.online, tally.mobile
    return {
        "rev": rev,
        "total": total,
        "online": online,
        "offline": total - online,
        "online_pct": round(100 * online / total, 1) if total else None,
        "mobile": len(mobile),
        "mobile_online": sum(1 for d in mobile if d.get("online")),
        "brands": brand_list,
        "unknown_chips": _unknown_chips(tally.chips),
        "battery": sum(1 for d in devices if d.get("battery") == "yes"),
        "types": {k: tally.types[k] for k in TYPE_ORDER if k in tally.types},
        # Average response time of the online devices that measured it.
        "latency_avg_ms": _avg_latency(devices),
        "poll": _poll_summary(poll),
        "activity": {"search": bool(activity.get("search")), "rescanning": list(activity.get("rescanning") or [])},
        "new_devices": {"count": new_devices.get("count", 0), "devices": new_devices.get("devices", [])},
    }


def _avg_latency(devices: list[dict]) -> int | None:
    vals = [d["latency_ms"] for d in devices if d.get("online") and d.get("latency_ms") is not None]
    return round(sum(vals) / len(vals)) if vals else None


def _brand_list(brands: dict) -> list[dict]:
    """Brands with their count, the most frequent first; on a tie the known ones before the unknown (None), then alphabetical."""
    return sorted(
        ({"brand": b, "count": n} for b, n in brands.items()),
        key=lambda r: (-r["count"], r["brand"] is None, (r["brand"] or "").lower()),
    )


def _unknown_chips(chips: dict) -> list[dict]:
    """MAC manufacturers of the devices with no known brand, the most frequent first, then alphabetical."""
    return sorted(({"vendor": v, "count": n} for v, n in chips.items()), key=lambda r: (-r["count"], r["vendor"].lower()))


def _poll_summary(poll: dict) -> dict:
    return {
        "interval_ms": poll.get("interval_ms"), "next_in_ms": poll.get("next_in_ms"),
        "paused": bool(poll.get("paused")), "paused_in_ms": poll.get("paused_in_ms"),
        "paused_total_ms": poll.get("paused_total_ms"),
    }


# ---- event log (logbook) ----
def recent_presence(limit: int, hist: History = history) -> list[dict]:
    """Latest online/offline events from the history, most recent first.
    Reads presence_events without touching storage/history.py (same connection and the
    same lock as the other methods)."""
    limit = max(1, min(int(limit), 200))
    with hist._lock:
        rows = hist._db.execute(
            "SELECT id, device_id, ip, online, ts FROM presence_events ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"id": r["id"], "device_id": r["device_id"], "ip": r["ip"], "online": bool(r["online"]), "ts": r["ts"]}
            for r in rows]


def logbook_entries(rows: list[dict], devices: dict[str, dict], cfg: dict[str, dict] | None = None) -> list[dict]:
    """Raw events + name and type of the device (if it is no longer in the
    configuration the last known IP remains) + sentence in the current language."""
    cfg = cfg or {}
    out = []
    for r in rows:
        d = devices.get(r["device_id"])
        out.append({
            "id": r["id"],
            "device_id": r["device_id"],
            "name": (d.get("name") if d else None) or r.get("ip") or r["device_id"],
            "ip": r.get("ip"),
            "type": effective_type(d, cfg.get(r["device_id"])) if d else "generic",
            "dev_icon": icon_for(d, (cfg.get(r["device_id"]) or {}).get("adapter")) if d else None,
            "known": d is not None,
            "online": r["online"],
            "ts": r["ts"],
            "message": i18n.t("ha.logbook.online" if r["online"] else "ha.logbook.offline"),
        })
    return out


def slim_history(window: dict) -> dict:
    """Window of history.presence_segments with times as whole seconds:
    fewer bytes in the responses that cover all devices."""
    return {
        "from": int(window["from"]), "to": int(window["to"]),
        "segments": [{"from": int(s["from"]), "to": int(s["to"]), "online": s["online"]} for s in window["segments"]],
        "online_pct": window["online_pct"],
    }
