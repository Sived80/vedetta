"""Accented letters do not change a word: "umidità" in a Home Assistant name is the word "umidita" of data/device_kinds.json, and an accented word
in the tables ("qualità") matches the name written with or without the accent. The tokenizer kept only a-z, so "umidità" became "umidit" and matched nothing."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_data  # noqa: E402
from app.ha import ha_type_evidence as te  # noqa: E402


def kinds_of(name: str) -> dict:
    out: dict = {}
    te.type_evidence({"ip": "192.0.2.21", "mac": "02:00:00:00:00:21", "name": name, "scanned_ports": []}, kinds_out=out)
    return out


# device side: the accent in the name of the device
assert kinds_of("Sensore umidita bagno").get("humidity"), "the plain word is a humidity sensor"
assert kinds_of("Sensore umidità bagno").get("humidity"), "the accented word must be the same word: %s" % kinds_of("Sensore umidità bagno")
assert kinds_of("SENSORE UMIDITÀ").get("humidity"), "upper case accented"
assert ha_data.best_kind({"ip": "192.0.2.22", "mac": "02:00:00:00:00:22", "name": "Umidità cantina", "scanned_ports": []}) == "humidity"

# data side: an accented word in the table matches both spellings
kd = te._build_kind({"id": "x_test", "group": "iot", "icon": "help", "words": ["qualità aria", "velocità", "umidità"], "tokens": ["càldo"]})
assert "qualita aria" in kd["subs"] and "velocita" in kd["subs"], kd["subs"]
assert "umidita" in kd["toks"] and "caldo" in kd["toks"], kd["toks"]
for name in ("Qualità aria salotto", "qualita aria salotto"):
    text, tokens, _ports = te._blob({"name": name})
    assert any(s in text for s in kd["subs"]), (name, text)
print("ALL OK")
