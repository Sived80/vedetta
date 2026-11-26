"""The groups of devices shown on the page, in their default order, and the group Home Assistant sees.

Since 1.0.4 the smart home kinds of data/device_kinds.json have their own groups on the page (climate, appliance, energy, security,
cover, water). Home Assistant keeps seeing them as "iot" (MQTT attribute and model "type", events "type"): the automations and the
blueprints written before keep working."""

# Order in which the page shows the groups when the person has not chosen one (setting "group_order").
TYPE_ORDER = ("router", "server", "pc", "phone", "media", "audio", "iot", "climate", "appliance", "energy", "security", "cover", "water",
              "printer", "camera", "generic")

# The groups that Home Assistant sees as "iot".
HOME_GROUPS = ("climate", "appliance", "energy", "security", "cover", "water")


def ha_group(group: str | None) -> str | None:
    """The group as Home Assistant knows it (MQTT, events): a smart home group is "iot", any other stays as it is."""
    return "iot" if group in HOME_GROUPS else group


def valid_order(value) -> bool:
    """A chosen order: a list of known groups, each at most once ([] = the default order)."""
    return isinstance(value, list) and all(isinstance(g, str) and g in TYPE_ORDER for g in value) and len(set(value)) == len(value)


def full_order(value) -> list[str]:
    """The chosen order made whole: the unknown groups and the repeats are left out, the missing ones follow in the default order
    ([] stays [], the default order)."""
    if not isinstance(value, list) or not value:
        return []
    known = [g for i, g in enumerate(value) if isinstance(g, str) and g in TYPE_ORDER and g not in value[:i]]
    return known + [g for g in TYPE_ORDER if g not in known] if known else []
