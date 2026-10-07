"""Check: an address that answers ARP several times appears only once."""
import logging
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vedetta"))
stub = types.ModuleType("app.applog")
stub.logger = logging.getLogger("dashboard")
sys.modules["app.applog"] = stub
from app.scan import scanner  # noqa: E402

TAB = chr(9)
text = TAB.join(["192.168.1.1", "aa:bb:cc:00:00:01", "TP-Link"]) + "\n" \
    + TAB.join(["192.168.1.9", "aa:bb:cc:00:00:09", "(Unknown)"]) + "\n" \
    + TAB.join(["192.168.1.1", "aa:bb:cc:00:00:01", "TP-Link (DUP: 2)"]) + "\n" \
    + TAB.join(["192.168.1.9", "aa:bb:cc:00:00:99", "(Unknown)"]) + "\n" \
    + "riga di intestazione senza tabulazioni\n" \
    + TAB.join(["non-un-ip", "aa:bb:cc:00:00:02", "X"]) + "\n"
hosts = scanner.parse_arp_scan(text)
assert [h["ip"] for h in hosts] == ["192.168.1.1", "192.168.1.9"], hosts
assert hosts[0]["vendor"] == "TP-Link" and hosts[1]["vendor"] is None
assert hosts[1]["mac"] == "AA:BB:CC:00:00:09"  # the first reply is kept
print("OK")
