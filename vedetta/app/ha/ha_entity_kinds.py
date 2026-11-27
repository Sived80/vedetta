"""The kind of a device as Home Assistant declares it: the domains and device classes of its entities (ha_registry "entity_classes")
turned into a kind of data/device_kinds.json by data/ha_entity_kinds.json. Pure: no state, the table is read once."""
from functools import lru_cache
from typing import NamedTuple

from .. import datafile
from .ha_type_text import W_DECLARED, W_SERVICE, W_WORD

_WEIGHTS = {"declared": W_DECLARED, "service": W_SERVICE, "word": W_WORD}


class EntityKind(NamedTuple):
    """The kind the entities declare, its points, the finer kinds a word may name, and the signature that decided."""
    kind: str
    pts: int
    finer: tuple
    signature: str


@lru_cache(maxsize=1)
def _tiers() -> tuple:
    """The tiers of the table as ((points, ((key, kind, finer), ...)), ...), in the order of the file ([] when it cannot be read: told once in the log)."""
    rows = datafile.read(datafile.DATA_DIR / "ha_entity_kinds.json", "tiers", what="Table of Home Assistant entity kinds", default=[])
    return tuple((_WEIGHTS.get(tier.get("weight"), W_WORD), tuple((key, row["kind"], tuple(row.get("finer") or ())) for key, row in (tier.get("kinds") or {}).items()))
                 for tier in rows)


def _matches(key: str, signatures: set, domains: set) -> bool:
    """A "domain.class" key matches that signature; a key without a dot matches every entity of the domain."""
    return key in signatures if "." in key else key in domains


def declared_kind(signatures) -> EntityKind | None:
    """The kind of the first tier with a matching signature (inside a tier, the first key of the file); None when no signature decides."""
    sigs = set(signatures or [])
    domains = {s.split(".")[0] for s in sigs}
    for pts, rows in _tiers():
        for key, kind, finer in rows:
            if _matches(key, sigs, domains):
                return EntityKind(kind, pts, finer, key)
    return None
