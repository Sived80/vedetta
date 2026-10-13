"""The ports kept from the analysis (when a device is added) are a starting point for the alerts of the first deep search: a port that the deep search finds and the analysis did not is «new»,
but a port that the analysis saw and the deep search does not is NOT told as closed (the analysis is no deep reading: a slow device, a busy moment). After a deep search both are told, as always."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import rescan  # noqa: E402

alerts = []
rescan.state.emit_alert = lambda text, *a, **k: alerts.append(text)
rescan.devices_config.update_scan_info = lambda *a, **k: None
rescan.history.save_scan = lambda *a, **k: None
device = {"id": "d1"}
port = lambda n: {"label": f"{n} · x"}


def run(previous, new_ports):
    alerts.clear()
    fields = {"ports": [port(n) for n in new_ports]}
    asyncio.run(rescan._save_scan_and_alert_ports(previous, fields, device, 1.0, "d1"))
    return list(alerts)


a = run({"ports": [port(554), port(80)]}, [80, 8000])                                   # from the analysis: no «closed» alert, the new one is told
assert len(a) == 1 and "8000" in a[0] and "554" not in a[0], a
b = run({"ports": [port(554), port(80)], "scanned_at": 5.0}, [80, 8000])                # after a deep search: both
assert len(b) == 2 and any("8000" in t for t in b) and any("554" in t for t in b), b
c = run({"http_title": "x"}, [80])                                                      # no ports before (as today): they are new
assert len(c) == 1 and "80" in c[0], c
print("TUTTO OK")
