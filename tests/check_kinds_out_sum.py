"""The points of a device type (kinds_out, they choose the icon) are ADDED up from every source. Found by the global review: the stage of the words and declared services assigned its points with «=»
where the Home Assistant integration and the signatures add with «+=», so an integration that declares the type (hue: light, 8 points) lost them when the name also said «light»."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_type_evidence as te  # noqa: E402

card = {"ip": "10.0.0.5", "name": "Living room light", "scanned_ports": [], "ha_registry": {"domains": ["hue"], "entity_domains": ["light"], "name": "Living room light"}}
words_only = dict(card, ha_registry=None)
declared_only = dict(card, name="10.0.0.5")

both, w, d = {}, {}, {}
te.type_evidence(dict(card), kinds_out=both)
te.type_evidence(dict(words_only), kinds_out=w)
te.type_evidence(dict(declared_only), kinds_out=d)
assert w.get("light", 0) > 0 and d.get("light", 0) >= te.W_DECLARED, (w, d)
assert both.get("light", 0) == w["light"] + d["light"], "the points of the integration and of the words must add up: %s = %s + %s" % (both, w, d)
print("TUTTO OK")
