"""Which changes of a card's identity are worth remembering (storage/history_identity.py). Pure: it compares the record of the card before
and after a check.

A change is remembered when the new value is there and differs from the old one: a name, a brand that appears or changes. A value
that goes away (a device that stops answering keeps its last data, or a check that found less) is not a change of identity. The
first record of a card after a start of the service has nothing before it: nothing is remembered. The address is a change of the
network, not of the identity: the journal says it already (alert.ip_changed)."""

FIELDS = ("name", "brand")


def _source(field: str, record: dict) -> str | None:
    if field == "brand":
        return record.get("brand_source")
    if record.get("name_generated"):
        return "generated"
    return "auto" if record.get("auto_name") else None


def between(before: dict | None, after: dict, now: float) -> list[dict]:
    if not before:
        return []
    out = []
    for field in FIELDS:
        old, new = before.get(field), after.get(field)
        if new and new != old:
            out.append({"device_id": after["id"], "ts": now, "field": field, "old": old, "new": new, "source": _source(field, after)})
    return out
