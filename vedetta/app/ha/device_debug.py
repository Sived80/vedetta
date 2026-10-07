"""What debug mode shows for a device: the clues that decided its group, the candidates for its name, brand, mobile score, DHCP,
roles, scan data and the registry/mDNS memory. Built from the shared state; used by the debug and evidence API and by the exports."""
from ..recognition import identity, naming, roles
from ..scan import dhcp, mdns_listener
from ..state import state
from . import ha_data, ha_registry


def device_debug(device_id: str) -> dict | None:
    device = state.devices.get(device_id)
    if device is None:
        return None
    cfg = ha_data.config_map().get(device_id) or {}
    kinds: dict[str, int] = {}
    evidence = ha_data.type_evidence(device, cfg.get("adapter"), kinds)
    scores = ha_data._aggregate(evidence)
    # for each (category, family) only the highest hint counts: the others are "repetitions" of the same fact
    top: dict = {}
    for e in evidence:
        top[(e["group"], e["family"])] = max(top.get((e["group"], e["family"]), 0), e["pts"])
    shown = [{**e, "counted": e["pts"] == top[(e["group"], e["family"])]} for e in evidence]
    shown.sort(key=lambda e: (e["group"], -e["pts"]))
    scan = cfg.get("scan_info") or {}
    extra = device.get("extra") or {}
    mac = (device.get("mac") or "").lower()
    entry = dhcp.seen.get(mac) or {}

    def cand(source: str, raw):
        return {"source": source, "raw": raw, "cleaned": naming.clean_name(raw) if raw else None} if raw else None
    candidates = [c for c in (
        cand("adapter", scan.get("api_name")), cand("mdns", scan.get("mdns_name")), cand("upnp", scan.get("upnp_name")),
        cand("dhcp", entry.get("hostname")), cand("netbios", scan.get("netbios_name")), cand("onvif", scan.get("onvif_name")),
        cand("tls", naming.cn_host(scan.get("tls_subject")) if scan.get("tls_subject") else None),
        cand("web", scan.get("http_title"))) if c]
    return {
        "type": {"chosen": ha_data.effective_type(device, cfg), "manual": cfg.get("type_user"),
                 "scores": dict(sorted(scores.items(), key=lambda kv: -kv[1])),
                 "kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
                 "evidence": shown, "margin_below": ha_data.MARGIN_BELOW,
                 "min_score": ha_data.MIN_TYPE_SCORE},
        "name": {"shown": device.get("name"), "source": cfg.get("name_source"), "candidates": candidates,
                 "placeholder": naming.is_placeholder(device.get("name"))},
        "brand": {"brand": device.get("brand"), "manual": cfg.get("brand_user"), "source": device.get("brand_source"),
                  "evidence": device.get("brand_evidence"), "confidence": device.get("brand_confidence"),
                  "declared": device.get("brand_declared"), "vendor": device.get("vendor"), "vendor_role": device.get("vendor_role")},
        "mobile": {"is_mobile": device.get("is_mobile"), "mode": cfg.get("mobile"), "private_mac": identity.is_private_mac(device.get("mac")),
                   "dhcp_os_family": dhcp.os_family(device.get("mac")), "churn_7d": identity.presence_churn(device_id),
                   "score": device.get("mobile_score"), "reason": device.get("mobile_reason"), "private_macs_7d": identity.presence_mac_changes(device_id),
                   "battery": device.get("battery"), "battery_source": device.get("battery_source")},
        "dhcp": {k: v for k, v in entry.items() if k != "seen"},
        "roles": {"roles": roles.roles_for(device.get("ip")), "upnp_types": roles.upnp_types(device.get("ip"))},
        "scan": {k: scan.get(k) for k in ("scanned_at", "deep_empty_at", "slow_scan", "full_ports_at", "services_at", "mdns_model", "mdns_manufacturer",
                                          "mdns_services", "http_server", "http_title", "tls_subject", "ssh_hostkey") if scan.get(k)},
        "extra_keys": sorted(extra),
        "wol": {"ok": bool(cfg.get("wol_ok"))},
        "ha_registry": ha_registry.lookup(device.get("mac"), device.get("ip")),
        "mdns_memory": mdns_listener.lookup(device.get("mac"), device.get("ip")),
    }
