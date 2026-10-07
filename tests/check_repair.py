"""The check says WHICH values are still readable, and the repair replaces them with the same placeholders the masking uses:
what cannot be replaced is left to the person. leaks() (the kinds) is exactly what leak_items() finds."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import anonymize  # noqa: E402

a = anonymize.Anonymizer()
a.add_ip("192.168.50.10")
a.add_mac("f0:18:98:aa:bb:cc")
a.add_device(["Giulia's iPad", "giulia-ipad"], "phone")

# something the masking missed (a MAC glued to other text, a mail in an odd place): the check says which values
raw = "owner a.b@example.com mac F0:18:98:AA:BB:CC ip 192.168.50.10 giulia-ipad password=hunter22 and 8.8.8.8 and 93.184.216.34"
items = a.leak_items(raw)
kinds = {k for k, _ in items}
assert kinds == {"email address", "MAC address", "home network address", "name", "password or token", "public address"}, kinds
vals = {v for _, v in items}
assert {"a.b@example.com", "F0:18:98:AA:BB:CC", "192.168.50.10", "hunter22", "93.184.216.34"} <= vals and "8.8.8.8" not in vals, vals
assert a.leaks(raw) == sorted(kinds)                                   # the kinds are what the items say, nothing else
assert a.leak_items(a.text(raw)) == []                                 # masked text is clean

fixed, n, left = a.repair(raw)
assert left == [] and n == len(items), (left, n, fixed)
for real in ("a.b@example.com", "F0:18:98:AA", "192.168.50.10", "giulia-ipad", "hunter22", "93.184.216.34"):
    assert real not in fixed, real
assert "8.8.8.8" in fixed and "iPad-1" in fixed and "email-1@masked.invalid" in fixed and "***" in fixed and "10.0.0.10" in fixed, fixed
assert a.repair(fixed) == (fixed, 0, [])                               # clean text: nothing to do

# JSON: the fields that describe the device stay, the rest is repaired, and the path says where something was left
obj = {"vendor": "Philips", "note": "mail me a.b@example.com", "list": [{"owner": "192.168.50.10"}], "token": "abc12345"}
new, n, left = a.repair_data(obj)
assert new["vendor"] == "Philips" and "a.b@" not in new["note"] and new["list"][0]["owner"] == "10.0.0.10" and n >= 2 and left == [], (new, n, left)

# what cannot be replaced safely stays in the list (here the replacement itself would still be readable)
class Stubborn(anonymize.Anonymizer):
    def fix_value(self, kind, value):
        return None if value == "a.b@example.com" else super().fix_value(kind, value)
s = Stubborn()
text, n, left = s.repair("mail a.b@example.com")
assert text == "mail a.b@example.com" and n == 0 and left == [("email address", "a.b@example.com")], (text, n, left)
print("TUTTO OK")
