# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The quality of a link (analysis/quality.py): median and MAD (robust: Wi-Fi spikes do not move them), the robust z of the last value,
the trend of the last 6 hours against the 18 before, the changes in 24 hours (a hole of Vedetta off is no change) and the longest
outage; the route answers for a card and 404 for an unknown one.
    python tests/check_quality.py"""
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.analysis import quality as q  # noqa: E402

H = 3600
NOW = 1_000_000.0

# 1) robust centre: ten spikes of 900 ms among 100 values of ~5 ms do not move the median nor the MAD much
vals = [5.0 + (i % 3) * 0.5 for i in range(100)] + [900.0] * 10
assert q.median(vals) == 5.5 and q.mad(vals, 5.5) == 0.5
assert q.level(5.5, vals) == ("normal", 0.0)
assert q.level(9.0, vals)[0] == "anomalous" and q.level(7.5, vals)[0] == "high"
assert q.level(5.0, vals[:5]) == ("unknown", None) and q.level(None, vals) == ("unknown", None)
assert q.level(3.0, [3.0] * 20) == ("normal", None) and q.level(9.0, [3.0] * 20) == ("high", None)      # MAD 0

# 2) trend: 6 hours against the 18 before
pts = [(NOW - 20 * H + i * 600, 10.0) for i in range(60)] + [(NOW - 5 * H + i * 600, 14.0) for i in range(20)]
assert q.trend(pts, NOW) == ("rising", 40)
assert q.trend([(NOW - H, 10.0)], NOW) == ("unknown", None)
flat = [(NOW - 20 * H + i * 600, 10.0) for i in range(120)]
assert q.trend(flat, NOW)[0] == "stable"

# 3) changes in 24 hours and the longest outage; a hole (Vedetta off) between two segments is not a change
segs = [{"from": NOW - 30 * H, "to": NOW - 10 * H, "online": True},
        {"from": NOW - 10 * H, "to": NOW - 7 * H, "online": False},
        {"from": NOW - 7 * H, "to": NOW - 5 * H, "online": True},
        {"from": NOW - 4 * H, "to": NOW, "online": False}]                     # 1 hour of hole before this one
assert q.changes(segs, NOW - 24 * H) == 2, q.changes(segs, NOW - 24 * H)
assert q.longest_outage(segs) == 4 * H and q.longest_outage(segs[:1]) is None
r = q.quality(pts, segs, NOW)
assert r["samples"] == 80 and r["median_ms"] == 10.0 and r["trend"] == "rising" and r["changes_24h"] == 2 and r["longest_outage_s"] == 4 * H, r
assert q.quality([], [], NOW)["level"] == "unknown"

# 4) the route
from fastapi.testclient import TestClient  # noqa: E402
from app import main  # noqa: E402
from app.state import state  # noqa: E402
state.devices["nas"] = {"id": "nas", "ip": "10.0.0.5", "online": True}
client = TestClient(main.app)
r = client.get("/api/ha/quality/nas")
assert r.status_code == 200 and r.json()["level"] == "unknown" and r.json()["samples"] == 0, r.text
assert client.get("/api/ha/quality/ghost").status_code == 404
print("check_quality: ok")
