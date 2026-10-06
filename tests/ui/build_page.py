"""Renders the /ha page with invented devices into a folder (page.html + data.json) for the jsdom UI checks.
Usage (from the vedetta/ folder): python ../tests/ui/build_page.py <out_dir> [it|en]"""
import json
import logging
import re
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "vedetta"
sys.path.insert(0, str(ROOT))
try:
    import app.applog  # noqa: F401
except Exception:
    stub = types.ModuleType("app.applog")
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub
import jinja2  # noqa: E402
from app import ha_data, i18n  # noqa: E402
from app.history import History  # noqa: E402

out = Path(sys.argv[1])
lang = sys.argv[2] if len(sys.argv) > 2 else "it"
out.mkdir(parents=True, exist_ok=True)
i18n.use(lang)
env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(ROOT / "app/templates")), autoescape=True)
env.globals["static_version"] = lambda p: "1"
page = env.get_template("ha.html").render(lang=lang, languages=i18n.available(), js_strings=i18n.js_table(lang), theme="auto",
                                          transparent=False, compact=False, limit=4, request=None)
page = re.sub(r'<script src="([^"]+)"></script>',
              lambda m: "<script>" + (ROOT / "app" / m.group(1).split("?")[0].lstrip("/")).read_text(encoding="utf-8") + "</script>", page)
(out / "page.html").write_text(page, encoding="utf-8")

now = time.time()


def dev(i, name, **kw):
    d = {"id": f"d{i}", "name": name, "is_mobile": False, "ip": f"192.168.1.{i}", "port": 80, "url": f"http://192.168.1.{i}:80", "online": True,
         "uptime": 90000, "mac": f"AA:BB:CC:00:00:{i:02d}", "vendor": "TP-Link", "brand": "TP-Link", "signal_kind": "wifi", "signal_value": -55,
         "signal_band": "2.4 GHz", "signal_label": "good", "signal_color": "green", "extra": {"model": "X1"},
         "scanned_ports": [{"label": "80 · http", "confirmed": True, "category": "web"}], "scanned_at": now - 5000, "last_seen": None}
    d.update(kw)
    return d


raw = [dev(1, "Router casa"), dev(2, "Luce cucina", vendor="Shelly", brand="Shelly"), dev(3, "Telefono", is_mobile=True, vendor="Apple", brand="Apple")]
ds = ha_data.compact_all(raw)
h = History(Path(tempfile.mkdtemp()) / "t.db")
data = {"devices": {"rev": 1, "ready": True, "devices": ds},
        "summary": ha_data.build_summary(raw, {"interval_ms": 30000, "next_in_ms": 20000}, {"search": False, "rescanning": []}, {"count": 0, "devices": []}, 1),
        "logbook": {"events": []},
        "history_all": {"hours": 24, "devices": {x["id"]: ha_data.slim_history(h.presence_segments(x["id"], now - 86400, now)) for x in raw}},
        "history_7d": {x["id"]: ha_data.slim_history(h.presence_segments(x["id"], now - 7 * 86400, now)) for x in raw}}
(out / "data.json").write_text(json.dumps(data), encoding="utf-8")
print("page for", len(ds), "devices")
