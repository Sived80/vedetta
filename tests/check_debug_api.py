"""Debug endpoint: why a device has that type, name and brand."""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import devices_config, ha_data, i18n, probe, roles, routes_ha  # noqa: E402
from app.state import state  # noqa: E402

i18n.use("it")
tmp = Path(tempfile.mkdtemp())
devices_config.DEVICES_PATH = tmp / "devices.yaml"
devices_config.CONFIG_DIR = tmp
devices_config.add_devices([{"ip": "10.0.0.190", "name": "10.0.0.190", "adapter": "generic", "port": 80,
                             "scan_info": {"http_title": "Login", "ports": [{"label": "554 · rtsp", "confirmed": False, "category": "media"}]}}])
did = devices_config.load_devices()[0]["id"]
roles.roles_for = lambda ip: []
roles.upnp_types = lambda ip: []
probe.ADAPTERS = {}
cfg = devices_config.load_devices()[0]
state.devices[did] = asyncio.run(probe.probe_device({**cfg, "last_mac": "1C:C3:16:00:00:AA"}))
out = asyncio.run(routes_ha.api_ha_device_debug(did))
assert out["type"]["chosen"] == "media" and "media" in out["type"]["scores"] and out["type"]["min_score"] == ha_data.MIN_TYPE_SCORE
assert out["brand"]["brand"] == "Milesight" and out["brand"]["evidence"] == "confirmed"
assert out["name"]["shown"] == "Milesight telecamera" and out["name"]["placeholder"] is False
assert any(c["source"] == "web" for c in out["name"]["candidates"]) or out["name"]["candidates"] == []
assert out["mobile"]["is_mobile"] is False and set(out) >= {"type", "name", "brand", "mobile", "dhcp", "roles", "scan", "wol"}
print("TUTTO OK")

# ---- export: zip with data and state, without credentials
import io, json, sqlite3, zipfile  # noqa: E402
from app import export  # noqa: E402

data_dir = Path(tempfile.mkdtemp())
(data_dir / "settings.json").write_text(json.dumps({"poll_interval": 30, "mqtt_user": "u", "mqtt_password": "SEGRETO"}), encoding="utf-8")
(data_dir / "devices.yaml").write_text("devices: []\n", encoding="utf-8")
(data_dir / "api_token.json").write_text('{"x": 1}', encoding="utf-8")   # suspicious name: excluded
(data_dir / "journal.jsonl").write_bytes(b"x" * 10 + b"\n")
con = sqlite3.connect(data_dir / "vedetta.db"); con.execute("create table t(a)"); con.execute("insert into t values (1)"); con.commit(); con.close()
export.paths.DATA_DIR = data_dir
resp = asyncio.run(routes_ha.api_export(plain=True))
assert resp.media_type == "application/zip" and "vedetta-analisi-" in resp.headers["content-disposition"]
z = zipfile.ZipFile(io.BytesIO(resp.body))
names = set(z.namelist())
assert {"manifest.json", "data/settings.json", "data/devices.yaml", "data/vedetta.db", "state/devices_debug.json", "state/roles.json"} <= names, names
assert "data/api_token.json" not in names
settings_text = z.read("data/settings.json").decode() + z.read("state/settings.json").decode()
assert "SEGRETO" not in settings_text and "***" in settings_text
db_copy = Path(tempfile.mkdtemp()) / "c.db"; db_copy.write_bytes(z.read("data/vedetta.db"))
assert sqlite3.connect(db_copy).execute("select a from t").fetchone() == (1,)
dbg = json.loads(z.read("state/devices_debug.json"))
assert did in dbg and dbg[did]["debug"]["brand"]["brand"] == "Milesight"
# what explains the decisions, without any address: the numbers behind "phone", the evidence card, the hour and the pending deep searches
mob = dbg[did]["debug"]["mobile"]
assert {"score", "reason", "private_macs_7d", "churn_7d"} <= set(mob) and isinstance(mob["private_macs_7d"], int), mob
assert "state/evidence.json" in names
evi = json.loads(z.read("state/evidence.json"))
assert set(evi[did]) == {"name", "brand", "group"} and 0 <= evi[did]["brand"]["certainty"] <= 100, evi[did]
man = json.loads(z.read("manifest.json"))
assert set(man["time"]) == {"utc_offset", "from_home_assistant", "night_hour"} and man["time"]["night_hour"] == 3 and man["time"]["utc_offset"][0] in "+-", man["time"]
assert man["time"]["utc_offset"] and "/" not in str(man["time"]), "the offset, not the name of the zone"
assert set(man["deep_search"]) == {"never_analysed", "devices"}, man["deep_search"]
assert "phone_merge" in man and (man["phone_merge"] is None or set(man["phone_merge"]) >= {"merged", "merged_total"}), man.get("phone_merge")
print("TUTTO OK (esportazione)")
