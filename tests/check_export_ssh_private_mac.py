"""Two identifiers the masked export kept (read in a real export, 19/11):
- the SSH key fingerprint of a server ("256 3f:0a:...:6a (ECDSA)"): unique to that machine, so it is masked like a MAC, one placeholder per key
  (the same key twice gives the same placeholder; the size and the kind of key stay, they say nothing about the machine);
- the first half of a PRIVATE MAC (a MAC the device made up, the "locally administered" bit on): it is not a manufacturer prefix, it is part
  of the real address, so a private MAC keeps nothing of it. A MAC with a real manufacturer prefix keeps it (it shows the brand).
And the netmask of the DHCP answer is a mask, not an address: it stays as it is."""
import json
import os
import sys
import tempfile

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export.anonymize import Anonymizer  # noqa: E402

FP1 = "3f:0a:5c:11:d2:7e:90:4b:c6:28:e1:73:05:9d:b4:6a"
FP2 = "d4:62:0b:9e:37:c1:58:fa:2d:84:6e:13:a7:50:c9:0f"
SHA = "SHA256:nThbg6kXUpJWGl7E1IGOCspRomTxdCARLviKw6E5SY8"

an = Anonymizer()
card = {"id": "a", "ssh_hostkey": "256 %s (ECDSA)" % FP1, "attrs": [{"key": "ssh_hostkey", "label": "SSH key", "value": "256 %s (ECDSA)" % FP1}]}
out = an.data(card)
text = json.dumps(out)
assert FP1 not in text.lower(), out
assert out["ssh_hostkey"].startswith("256 ") and out["ssh_hostkey"].endswith(" (ECDSA)"), out
assert out["ssh_hostkey"] == out["attrs"][0]["value"], out                       # one key, one placeholder, wherever it is written
line = an.text('scan {"ssh_hostkey": "256 %s (ECDSA)"} and %s and %s' % (FP2, FP1.upper(), SHA))
assert FP2 not in line.lower() and FP1 not in line.lower() and SHA not in line, line
assert out["ssh_hostkey"].split()[1] in line, (out, line)                         # the first key keeps its placeholder in the log too
assert an.leaks("key 256 %s" % FP2), "the check of the finished file must notice a fingerprint left readable"

an = Anonymizer()
private, real = "06:5c:31:4d:9a:e2", "b8:27:eb:12:34:56"                          # 0x06 has the "local" bit on; b8:27:eb is a maker
an.add_mac(private)
an.add_mac(real)
masked = an.text("router %s, pi %s" % (private.upper(), real))
assert "06:5C:31" not in masked and "4D:9A:E2" not in masked, masked
assert "b8:27:eb:" in masked, masked                                              # a maker's prefix stays
assert "02:00:00:" in masked.lower(), masked                                      # still read as a private MAC (the local bit stays on)

roles = {"dhcp": [{"server": "192.168.1.1", "netmask": "255.255.255.0"}]}
assert Anonymizer().data(roles)["dhcp"][0]["netmask"] == "255.255.255.0"
print("ALL OK")
