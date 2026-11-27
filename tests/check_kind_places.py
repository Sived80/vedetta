# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""1.0.4: a word that is also a place (garage, garden, pool) does not decide the kind of a device on its own: «Presa garage» is a plug in
the garage, not a garage door; the place counts for its kind only together with a word that says the device (data/device_kinds.json
"place" and "with"). The common Italian diminutives of a kind word are words of the kind («Cancelletto» is a gate). Home Assistant keeps
seeing "iot" (MQTT attribute and events "type") for all of them. Invented names only."""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data

failed = 0


def check(cond: bool, msg: str) -> None:
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


def card(name: str) -> dict:
    return {"id": "k1", "ip": "192.0.2.50", "name": name, "mac": "02:00:00:00:00:50", "online": True, "extra": {}}


def seen(name: str) -> tuple:
    device = card(name)
    return ha_data.infer_type(device), ha_data.effective_kind(device), ha_data.compact_device(device)["family"], ha_data.device_facts(device)["type"]


CASES = (
    ("Presa garage", "plug", "lights"),             # the type word wins over the place
    ("Luce garage", "light", "lights"),
    ("Cancelletto", "gate", "security"),            # the diminutive of cancello
    ("Cancellino ingresso", "gate", "security"),
    ("Cancello", "gate", "security"),
    ("Portone", "gate", "security"),
    ("Porta garage", "garage", "security"),         # the place with an opening word: the garage door
    ("Portone garage", "garage", "security"),
    ("Apertura garage", "garage", "security"),
    ("Garage door opener", "garage", "security"),
    ("Basculante", "garage", "security"),
    ("Tapparella sala", "blinds", "climate"),
    ("Tenda da sole", "awning", "climate"),
    ("Sensore temperatura", "temperature", "climate"),
    ("Presa", "plug", "lights"),
    ("Spina cucina", "plug", "lights"),
    ("Presa piscina", "plug", "lights"),
    ("Pompa piscina", "pool", "other"),
    ("Luce giardino", "light", "lights"),
    ("Irrigazione giardino", "irrigation", "other"),
)
for name, kind, family in CASES:
    got = seen(name)
    check(got == ("iot", kind, family, "iot"), "%s: kind %s, family %s, Home Assistant sees iot: %s" % (name, kind, family, got))

# a place alone says no kind
for name in ("Garage", "Giardino", "Piscina"):
    check(ha_data.effective_kind(card(name)) is None, "%s alone names a place, not a kind: %s" % (name, ha_data.effective_kind(card(name))))
# a word that only contains a kind word is not it
check(ha_data.effective_kind(card("Cancelleria")) != "gate", "a word that only starts like cancello is not a gate")

print("FAILED: %d" % failed if failed else "ALL OK")
sys.exit(1 if failed else 0)
