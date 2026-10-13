"""probe_record: the records that the stages of probe_device pass to each other (what is known about the device, how it is reached, the brand stage, the name, the product)
and the builder of the final card record. Kept apart from probe.py so that the stages stay a short list."""
from dataclasses import dataclass
from typing import NamedTuple

from ..formatters import quantize_uptime, truncate_name
from .probe_web import _web_open, _web_url


@dataclass
class Facts:
    """What is known about ONE device once the adapter, the ARP table, the saved scan and the memories (Bonjour, DHCP, Home Assistant) have been read: the inputs of every
    later decision (names, brand, mobile). The decisions read it; only the steps of the names add their entries to `extra`."""
    device: dict
    ip: str
    port: int
    result: dict
    mac: str | None
    extra: dict
    scan_info: dict
    scanned_ports: list
    identity_mac: str | None
    dhcp_name: str | None
    dhcp_class: str | None
    ha_card: dict | None
    key: str | None            # the last of the declared-service keys looked at (kept as it always was: the model step receives it)


class Signal(NamedTuple):
    """How the device is reached: Wi-Fi or cable, the value and its label and colour for the card."""
    kind: str | None
    value: object
    label: str | None
    color: str | None


class Brand(NamedTuple):
    """The outcome of the brand stage: who makes it (with how sure we are), what kind of model, the battery."""
    ident: dict
    model_class: str | None
    battery: object
    battery_source: str | None


class Naming(NamedTuple):
    """The name decided for the card and how it came about."""
    display: str
    kept_placeholder: str | None
    generated: bool
    auto: tuple | None


class Product(NamedTuple):
    """What the card says the device is: the extra attributes, the vendor of the board and the product brand."""
    extra: dict
    vendor: str | None
    brand: str | None


def _build_probe_record(f: Facts, signal: Signal, brand_stage: Brand, name: Naming, product: Product, assessment, is_mobile) -> dict:
    display_name = name.display
    if display_name == f.ip and name.kept_placeholder:
        display_name = truncate_name(name.kept_placeholder) or f.ip
    ident = brand_stage.ident
    return {
        "ha_registry": f.ha_card,
        "name_generated": name.generated,
        "auto_name": name.auto,
        "id": f.device["id"],
        "name": display_name,
        "is_mobile": is_mobile,
        "mobile_score": assessment["score"] if assessment else None,       # for the evidence card
        "mobile_reason": assessment["reason"] if assessment else None,
        "ip": f.ip,
        "port": f.port,
        "url": _web_url(f.ip, f.port, f.scanned_ports),
        "web_open": _web_open(f.scanned_ports),
        "online": f.result.get("online", False),
        "uptime": quantize_uptime(f.result.get("uptime_seconds")),
        "mac": f.mac,
        "vendor": product.vendor,
        "vendor_role": ident["vendor_role"],
        "brand": product.brand,
        "brand_source": ident["brand_source"],
        "brand_confidence": ident["brand_confidence"],
        "brand_evidence": ident["brand_evidence"],
        "brand_declared": ident["brand_declared"],
        "battery": brand_stage.battery,
        "battery_source": brand_stage.battery_source,
        "signal_kind": signal.kind,
        "signal_value": signal.value,
        "signal_band": f.result.get("signal_band"),
        "signal_label": signal.label,
        "signal_color": signal.color,
        "extra": product.extra,
        "scanned_ports": f.scanned_ports,
        "scanned_at": f.scan_info.get("scanned_at"),
        "deep_empty_at": f.scan_info.get("deep_empty_at"),
    }
