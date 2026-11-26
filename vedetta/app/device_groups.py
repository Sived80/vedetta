"""The groups of devices on the page and, inside the smart home group, the families.

The page shows the ten groups Home Assistant knows (MQTT attribute and model "type", events "type"): the automations and the blueprints
keep working. Inside "iot" (the smart home group) each card has a family (lights, sensors, climate...), worked out here from its finer
kind (data/device_kinds.json): a second level on the page only, Home Assistant never sees it."""

# Order in which the page shows the groups when the person has not chosen one (setting "group_order").
TYPE_ORDER = ("router", "server", "pc", "phone", "media", "audio", "iot", "printer", "camera", "generic")

# The groups of data/device_kinds.json that are scored as "iot" (one smart home group); each one is also a family.
HOME_GROUPS = ("climate", "appliance", "energy", "security", "cover", "water")

# The families of the smart home group, in the order the page shows them; "hubs" takes any smart home kind not listed (a hub, a module,
# a board, a kind added to the table later) and a card with no kind at all: most often a relay or a board that names nothing.
FAMILIES = ("lights", "sensors", "climate", "appliance", "energy", "security", "cover", "water", "hubs")
OTHER_FAMILY = "hubs"
_FAMILY_OF_KIND = {"light": "lights", "ledstrip": "lights", "plug": "lights", "dimmer": "lights", "switch": "lights",
                   "temperature": "sensors", "humidity": "sensors", "airquality": "sensors"}


def ha_group(group: str | None) -> str | None:
    """The group as Home Assistant knows it: a smart home group saved by the debug build with 16 groups (climate...) is "iot"."""
    return "iot" if group in HOME_GROUPS else group


def family_of(kind: str | None, kind_group: str | None) -> str:
    """The family of a smart home card from its finer kind and the group of that kind in data/device_kinds.json."""
    if kind in _FAMILY_OF_KIND:
        return _FAMILY_OF_KIND[kind]
    return kind_group if kind_group in HOME_GROUPS else OTHER_FAMILY


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
