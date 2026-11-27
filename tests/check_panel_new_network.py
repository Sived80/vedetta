# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""A network behind the router just added, with Ports on, before its devices are found again (no card yet): the panel «Networks» must not
say that it does not answer and offer the firewall rule ("How to turn it on"), as it did on the debug copy of 1.0.0 right after a network
was deleted and added again. Nothing is known against it: Ports is on. With cards that are all offline the firewall help stays.
Invented private addresses only.
    python tests/check_panel_new_network.py"""
import ipaddress
import os
import sys
import tempfile
import time

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.networks import panel  # noqa: E402
from app.networks.model import Network  # noqa: E402

failed = 0


def check(cond, msg):
    global failed
    print(("ok: " if cond else "FAILED: ") + msg)
    failed += 0 if cond else 1


now = time.time()
net = Network("iot", ipaddress.ip_network("10.61.0.0/24"), frozenset({"routed"}), "ports", "confirmed", name="IoT", vlan=20)


def seen(cards, last):
    return panel.Seen(cards=tuple(cards), last=last, host={}, trackers=(), mdns=(), own_ip="10.60.0.5", iface="eth0", now=now)


empty = panel.describe(net, seen([], {}), "IoT", False)
check(empty["caps"]["port"]["state"] == "on", f"no card yet: Ports is on, no firewall help: {empty['caps']['port']}")
check(empty["caps"]["deep"]["state"] == "on", "the model follows the ports: on as well")

cards = [("scan-10-61-0-7", "10.61.0.7", None), ("scan-10-61-0-8", "10.61.0.8", None)]
silent = panel.describe(net, seen(cards, {c[0]: (False, now - 600) for c in cards}), "IoT", False)
check(silent["caps"]["port"]["state"] == "how", "cards known and all offline: the firewall help stays")

alive = panel.describe(net, seen(cards, {cards[0][0]: (True, now)}), "IoT", False)
check(alive["caps"]["port"]["state"] == "on", "a card on: Ports is on")

tried = panel.describe(net, seen([], {}), "IoT", False, answers=False)
check(tried["caps"]["port"]["state"] == "how", "the try of «try and add» said nobody answers: the firewall help, as before")

print("ALL OK" if not failed else f"{failed} FAILED")
sys.exit(1 if failed else 0)
