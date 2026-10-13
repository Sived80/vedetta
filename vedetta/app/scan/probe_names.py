"""probe_names: moved out of probe.py (see tools/split_module.py)."""
from dataclasses import dataclass

from ..ha import ha_registry
from .probe_record import Facts, Product
from ..i18n import t_or as i18n_t_or
from ..recognition import naming
from ..recognition import roles
from ..formatters import truncate_name
from .. import i18n
from ..ha import ha_data
from ..recognition import roles as _roles


# "Declared" models that are actually the service type, not a model.
_GENERIC_MODELS = {"mediarenderer", "mediaserver", "basic", "dial", "device", "root"}


# (what scan_info announces, the key of `extra`, only when it differs from the name of the device): in this order, which is the order of the keys of `extra`
_ANNOUNCED_EXTRAS = (("mdns_name", "mdns", True), ("netbios_name", "netbios", True), ("upnp_name", "upnp_name", True),
                     ("upnp_model", "upnp_model", False), ("mdns_model", "mdns_model", False))


def _add_announced_name_extras(extra, scan_info, device):
    for source, key, must_differ in _ANNOUNCED_EXTRAS:
        value = scan_info.get(source)
        if value and key not in extra and not (must_differ and value == device.get("name")):
            extra[key] = value


def _add_declared_service_extras(extra, scan_info):
    key = None            # set below on some paths only
    if scan_info.get("snmp_descr") and "snmp" not in extra:
        extra["snmp"] = scan_info["snmp_descr"]
    for key in ("upnp_manufacturer", "onvif_name", "onvif_hardware", "onvif_manufacturer", "rtsp_server",
                "api_vendor", "api_model", "api_fw", "tls_subject", "tls_issuer", "ssh_hostkey", "mdns_services", "igmp_groups",
                "http_server"):
        if scan_info.get(key) and key not in extra:
            extra[key] = scan_info[key]
    return key


@dataclass
class NameState:
    """The name of the device while the stages of probe_device decide it: the name it has, whether that is a leftover placeholder, whether the name that Home Assistant gave it is stale, the name to
    keep for good when it is found automatically, and what the card will show."""
    base_name: str | None
    placeholder: bool
    ha_stale: bool
    auto_name: tuple | None = None       # (name, source, followed from Home Assistant): saved, so the name stays when the source goes silent
    display_name: str | None = None
    kept_placeholder: str | None = None
    generated: bool = False              # built by the app (brand + type...): must not count as a hint for the type


def choose_automatic_name(f: Facts, names: NameState) -> None:
    """Which automatic name the device gets: an upgrade of the one it has, else the best candidate when it needs a name."""
    candidates = _name_candidates(f)
    # A name found automatically earlier is replaced as soon as a better one is available (same ranking as when it was chosen)
    upgrade = None if (not names.base_name or names.base_name == f.ip or names.placeholder) else naming.upgrade(
        {"name": names.base_name, "ip": f.ip, "name_source": f.device.get("name_source")}, candidates)
    if upgrade:
        names.base_name, names.auto_name = upgrade[0], (upgrade[0], upgrade[1], False)
    elif _needs_name(names.base_name, f.ip, names.placeholder):
        _name_from_candidates(f, names, candidates)


def _name_candidates(f: Facts) -> list:
    return [
        ("adapter", f.scan_info.get("api_name")), ("mdns", f.scan_info.get("mdns_name")),
        ("upnp", f.scan_info.get("upnp_name")), ("upnp", (roles.snapshot().get("names") or {}).get(f.ip)),
        ("dhcp", f.dhcp_name), ("netbios", f.scan_info.get("netbios_name")), ("onvif", f.scan_info.get("onvif_name")),
        ("tls", naming.cn_host(f.scan_info.get("tls_subject"))), ("web", naming.title_name(f.scan_info.get("http_title"))),
    ]


def _name_from_candidates(f: Facts, names: NameState, candidates: list) -> None:
    found, src = naming.pick(candidates)
    if found and not (names.placeholder and naming.is_placeholder(found)):
        was_ip = not names.base_name or names.base_name == f.ip
        names.base_name = found
        if names.placeholder or was_ip:   # it is saved: the name stays even when the source (e.g. a sleeping phone) goes silent
            names.auto_name = (found, src, names.ha_stale)
    elif names.ha_stale:
        names.base_name = None   # no other source: better the default name than one from HA referring to another device


def prefer_home_assistant_name(f: Facts, names: NameState) -> None:
    """Home Assistant: the name the user gave there (or the integration's one) wins over weaker sources and over placeholder names, never over a name chosen in Vedetta."""
    ha_name, ha_src = ha_registry.choose_name(f.ha_card)
    # If the saved name was already taken from HA and it changed in HA, the change is followed (even with the same weight).
    from_ha = f.device.get("name_source") in ("ha", "ha_user")
    if _ha_name_applies(f, names, ha_name, ha_src, from_ha):
        names.base_name = ha_name
        names.auto_name = (ha_name, ha_src, from_ha)
    # Leftover placeholder name ("Android", "iPhone"): it is not a name, the default name is tried first.
    names.kept_placeholder = _kept_placeholder(names.base_name, f.device)
    names.display_name = f.ip if names.kept_placeholder else (truncate_name(names.base_name) or f.ip)
    if f.dhcp_name and f.dhcp_name != names.display_name and "dhcp" not in f.extra:
        f.extra["dhcp"] = f.dhcp_name


def _ha_name_applies(f: Facts, names: NameState, ha_name, ha_src, from_ha: bool) -> bool:
    """The Home Assistant name replaces the current one: it exists, the name was not chosen in the app, it is a different name, and it is
    either the one already followed from HA or a better source than the current name."""
    if not ha_name or f.device.get("name_source") == "user" or ha_name == names.base_name:
        return False
    return bool(from_ha or naming.is_better({"name": names.base_name, "ip": f.ip, "name_source": f.device.get("name_source")}, ha_src))


def name_from_brand_and_model(f: Facts, names: NameState, ident: dict) -> Product:
    """No declared name: instead of the IP, "brand model" but only if BOTH are certain (brand confirmed and model declared by the device). It is not saved: a name chosen
    by the user, or a better automatic one, always prevails (naming.is_better). Returns what the card says the device is (extra attributes, vendor, brand)."""
    vendor, brand = ident["vendor"], ident["brand"]
    if names.display_name == f.ip and brand and ident.get("brand_evidence") == "confirmed":
        model = _declared_model(brand, f.scan_info, f.ha_card)
        if model:
            names.display_name = truncate_name(model if model.lower().startswith(brand.lower()) else f'{brand} {model}') or f.ip
    extra = {**_brand_vendor_head(brand, vendor, f.extra), **f.extra}
    if f.ha_card:
        _add_ha_extras(extra, f.ha_card)
    return Product(extra, vendor, brand)


def name_from_brand_and_type(f: Facts, names: NameState, product: Product, ident: dict, is_mobile) -> None:
    """Still no name: brand + device type ("Milesight telecamera"), only if the brand is known and the type is understood; otherwise the address stays. Never saved:
    any better name (declared by the device or chosen by the user) prevails."""
    if names.display_name != f.ip:
        return
    probe_dev = {"ip": f.ip, "brand": product.brand, "vendor": product.vendor, "vendor_role": ident["vendor_role"],
                 "extra": product.extra, "scanned_ports": f.scanned_ports, "is_mobile": is_mobile, "ha_registry": f.ha_card}
    kind = ha_data.best_kind(probe_dev)
    label = i18n.t_or("kind." + kind, "") if kind else ""
    if not label:   # no precise type: the category name ("Apple telefono")
        label = i18n.t_or("group." + ha_data.infer_type(probe_dev), "")
    if label and ha_data.kind_is_product(kind):
        names.display_name = label  # "Home Assistant", "Raspberry Pi": the type is already the product
        names.generated = True
    elif product.brand and (ident["brand_source"] != "name" or ident["brand_evidence"] == "confirmed"):
        names.display_name = truncate_name(f"{product.brand} {label}".strip()) or f.ip  # a brand inferred only from a name is not enough
        names.generated = names.display_name != f.ip


def name_from_network_role(f: Facts, names: NameState) -> None:
    """Still no name: the role the device plays on the network (detected via DNS, DHCP, UPnP, repeater) tells what it is better than the address ("Server DNS")."""
    if names.display_name != f.ip or names.kept_placeholder:
        return
    found_roles = _roles.roles_for(f.ip)
    for role in ("gateway", "repeater", "ap", "dhcp", "dns"):
        if role in found_roles:
            label = i18n_t_or("rolename." + role, "")
            if label:
                names.display_name = label
                names.generated = True
            break


def _needs_name(base_name, ip, placeholder) -> bool:
    """No name, only the IP, or a leftover placeholder: the device can take an automatic one."""
    return not base_name or base_name == ip or placeholder


def _kept_placeholder(base_name, device):
    """The current name when it is a leftover placeholder ("Android", "iPhone") that was not chosen in the app, else None."""
    return base_name if (device.get("name_source") != "user" and naming.is_placeholder(base_name)) else None


def _declared_model(brand, scan_info, ha_card):
    """The first model the device (or Home Assistant) declares that says something: not a generic word, not the brand itself."""
    return next((m for m in (scan_info.get("api_model"), scan_info.get("upnp_model"), scan_info.get("mdns_model"), (ha_card or {}).get("model"))
                 if m and m.lower() not in _GENERIC_MODELS and m.lower() != brand.lower()), None)


def _brand_vendor_head(brand, vendor, extra):
    """Product brand and, if different, the board maker (chip): the ones `extra` does not hold yet."""
    return {k: v for k, v in (("brand", brand), ("vendor", vendor if vendor != brand else None)) if v and k not in extra}


def _add_ha_extras(extra, ha_card):
    """Home Assistant: area, model and integration (additional attributes)."""
    for k, val in (("ha_area", ha_card.get("area")), ("ha_model", ha_card.get("model")),
                   ("ha_integration", ", ".join(ha_card.get("domains") or []))):
        if val:
            extra[k] = val

