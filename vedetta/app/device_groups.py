# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The groups of devices on the page and, inside the smart home group, the families.

The page shows the ten groups Home Assistant knows (MQTT attribute and model "type", events "type"): the automations and the blueprints
keep working. Inside "iot" (the smart home group) each card has a family (lights, climate, security...), and inside "printer" one of two
(printers, 3D printers), worked out here from its finer kind (data/device_kinds.json): a second level on the page only, Home Assistant
never sees it."""

# Order in which the page shows the groups when the person has not chosen one (setting "group_order").
TYPE_ORDER = ("router", "server", "pc", "phone", "media", "audio", "iot", "printer", "camera", "generic")

# The groups of data/device_kinds.json that are scored as "iot" (one smart home group); each one is also a family.
HOME_GROUPS = ("climate", "appliance", "energy", "security", "cover", "water")

# The families of the smart home group, in the order the page shows them: the summaries of the Home dashboard of Home Assistant (lights,
# climate, security, energy: the same devices under the same headings in both places), "access" right after security (gates, garage doors,
# doors: Home Assistant shows them in its security summary, the person wanted them apart, 27/11), then appliances and "other", which takes
# any smart home kind not listed (a module, a board, a pump, a kind added to the table later) and a card with no kind at all. The gateways
# (hub: Zigbee, Z-Wave, Thread, Bluetooth bridges and proxies) are not here: they are network (group "router").
FAMILIES = ("lights", "climate", "security", "access", "energy", "appliance", "other")
OTHER_FAMILY = "other"
# Lights: Home Assistant has only lights, plugs and relays are here too. Climate: the temperature and humidity sensors of the rooms and the
# window coverings (cover device classes awning, blind, curtain, shade, shutter); access: the garage doors and the gates (garage, gate).
_FAMILY_OF_KIND = {"light": "lights", "ledstrip": "lights", "plug": "lights", "dimmer": "lights", "switch": "lights",
                   "temperature": "climate", "humidity": "climate", "garage": "access", "gate": "access", "printer3d": "printer3d"}
_FAMILY_OF_GROUP = {"climate": "climate", "appliance": "appliance", "energy": "energy", "security": "security", "cover": "climate",
                    "printer": "printers"}

# The printer group has two families on the page (1.1.1): the printers of paper, with the scanners, and the 3D printers.
PRINTER_FAMILIES = ("printers", "printer3d")
# The groups whose cards the page shows under the subtitles of their families, and the family of a card whose kind gives none.
GROUP_FAMILIES = {"iot": FAMILIES, "printer": PRINTER_FAMILIES}
DEFAULT_FAMILY = {"iot": OTHER_FAMILY, "printer": "printers"}
ALL_FAMILIES = FAMILIES + PRINTER_FAMILIES
# The families saved before 1.0.4 (family_user, and the types of the debug build with 16 groups): "cover" goes to the climate or access
# family its kind says (None here), climate when the kind says neither.
_OLD_FAMILIES = {"sensors": "climate", "hubs": OTHER_FAMILY, "water": OTHER_FAMILY, "cover": None}


def ha_group(group: str | None) -> str | None:
    """The group as Home Assistant knows it: a smart home group saved by the debug build with 16 groups (climate...) is "iot"."""
    return "iot" if group in HOME_GROUPS else group


def family_of(kind: str | None, kind_group: str | None) -> str:
    """The family of a smart home or printer card from its finer kind and the group of that kind in data/device_kinds.json."""
    return _FAMILY_OF_KIND.get(kind) or _FAMILY_OF_GROUP.get(kind_group) or OTHER_FAMILY


def chosen_family(value, auto: str, group: str = "iot") -> str | None:
    """A family chosen by hand (or a smart home type of the debug build with 16 groups) as one of the families of the card's group; auto =
    the family the kind gives, for an old "cover". None when the value is no family of that group: a family saved while the card was in
    another group is not used."""
    if value in GROUP_FAMILIES.get(group, ()):
        return value
    if group != "iot" or not isinstance(value, str) or value not in _OLD_FAMILIES:
        return None
    return _OLD_FAMILIES[value] or (auto if auto in ("climate", "access") else "climate")


def valid_order(value) -> bool:
    """A chosen order: a list of known groups, each at most once ([] = the default order)."""
    return isinstance(value, list) and all(isinstance(g, str) and g in TYPE_ORDER for g in value) and len(set(value)) == len(value)


def full_order(value) -> list[str]:
    """The chosen order made whole: the unknown groups (such as "climate", saved by the debug build with 16 groups) and the repeats are
    left out, the missing ones follow in the default order ([] stays [], the default order)."""
    if not isinstance(value, list) or not value:
        return []
    known = [g for i, g in enumerate(value) if isinstance(g, str) and g in TYPE_ORDER and g not in value[:i]]
    return known + [g for g in TYPE_ORDER if g not in known] if known else []
