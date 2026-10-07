"""Check of the ignored-devices list (no network, temporary file)."""
import sys, tempfile, types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vedetta"))
from app.storage import blocklist
from app.scan import dhcp  # noqa: E402

blocklist.PATH = Path(tempfile.mkdtemp()) / "ignored.json"
blocklist._cache["stamp"] = None

assert blocklist.list_items() == [] and not blocklist.matches(mac="AA:BB:CC:DD:EE:01", ip="10.0.0.5")
blocklist.add("mac", "aa:bb:cc:dd:ee:01")
blocklist.add("mac", "AA:BB:CC:DD:EE:01")           # duplicate: ignored
blocklist.add("ip", "10.0.0.9")
blocklist.add("name", "iPhone-di-Tizio")
assert len(blocklist.list_items()) == 3
assert blocklist.matches(mac="AA:BB:CC:DD:EE:01") and blocklist.matches(ip="10.0.0.9")
assert blocklist.matches(name="iphone-di-tizio")                       # case-insensitive name
dhcp.seen["02:11:22:33:44:55"] = {"hostname": "iPhone-di-Tizio"}
assert blocklist.matches(mac="02:11:22:33:44:55", ip="10.0.0.77")    # new private MAC, but same DHCP name
assert not blocklist.matches(mac="AA:BB:CC:DD:EE:02", ip="10.0.0.5", name="Cucina")

# how what to ignore is chosen
assert blocklist.choose("10.0.0.5", "00:11:22:33:44:55", "NAS")[0] == "mac"                 # stable MAC
assert blocklist.choose("10.0.0.5", "02:11:22:33:44:55", "iPhone-di-Tizio") == ("name", "iPhone-di-Tizio")  # private + name
assert blocklist.choose("10.0.0.5", None, None) == ("ip", "10.0.0.5")

# restore
first = blocklist.list_items()[0]["id"]
assert blocklist.remove(first) and not blocklist.remove("zzzz")
assert not blocklist.matches(mac="AA:BB:CC:DD:EE:01")
for bad in [("mac", "x"), ("foo", "abcdef")]:
    try:
        blocklist.add(*bad)
        raise SystemExit("doveva fallire")
    except ValueError:
        pass
print("OK")
