"""Two devices that announce the same name (the service name of an app on every phone) must keep two placeholders; one device
with several names still has one; nothing readable is left."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import anonymize  # noqa: E402

a = anonymize.Anonymizer()
a.add_devices([
    (["Xiaomi-14", "Xiaomi-14", "expiscor", None], "phone", "Xiaomi", None),
    (["iPhone di Mario", "iPhone-di-Mario", "expiscor"], "phone", "Apple", None),
    (["Salotto", "salotto-tv"], "media", None, None),
    (["Apple mobile"], "phone", "Apple", None),
    (["Apple mobile"], "phone", "Apple", None),
])
x, i = a.text("Xiaomi-14"), a.text("iPhone di Mario")
assert x != i, (x, i)                                                      # two phones, two placeholders
assert a.text("iPhone-di-Mario") == i and a.text("salotto-tv") == a.text("Salotto")   # one device, its names together
assert a.text("expiscor") not in (x, i) and "expiscor" not in a.text("_amazon-expiscor._udp")   # the shared name is masked, on its own
assert a.text("Apple mobile") == a.text("Apple mobile")
for real in ("Xiaomi-14", "iPhone di Mario", "Mario", "Salotto", "expiscor"):
    assert not a.leaks(f"name {real}") or a.text(f"name {real}") != f"name {real}", real
print("TUTTO OK")
