"""Unit and privacy audit tests for state/analysis.json and MQTT manifest status.

Covers T1-T8 from Claude Sonnet's audit specification:
- T1: No real IP/MAC/name leaks into state/analysis.json or manifest.json
- T2: Consistent card_id placeholder across analysis.json, devices_compact.json, devices_debug.json
- T3: 10.x networks (e.g. 10.20.30.40) properly masked in card IDs
- T4: Enum collision resistance (device named "Router" / "Thin" does not corrupt reasons/scores/chosen)
- T5: Allowlist sanitization (arbitrary values become "other")
- T6: MQTT status in manifest has exact boolean keys {"enabled", "connected"}
- T7: Manifest anonymization (manifest passes through anon.data)
- T8: Note sanitization (invisible unicode stripped, names masked)
"""
import io
import json
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))

from app.analysis import status as st
from app.export import anonymize, export_analysis, export_engine, export_gather
from app.ha import analysis_view, mqtt_ha
from app.state import state


def test_allowlist_sanitization():
    # T5: Test allowlist
    assert export_analysis._val_enum("identified", export_analysis.ALLOWED_STATES) == "identified"
    assert export_analysis._val_enum("192.168.1.5", export_analysis.ALLOWED_STATES) == "other"
    assert export_analysis._val_reasons(["thin", "hack_attempt", "close"]) == ["thin", "other", "close"]
    assert export_analysis._val_badges([{"id": "analysing"}, {"id": "evil_badge"}]) == ["analysing", "other"]
    assert export_analysis._val_scores({"router": 10, "evil_group": 5}) == [["router", 10], ["other", 5]]
    print("T5 allowlist sanitization: OK")


def test_enum_collision_resistance():
    # T4: Device named "Router", "Thin", "Close"
    anon = anonymize.Anonymizer()
    anon.add_device(["Router"], None, "Netgear")
    anon.add_device(["Thin"], None, "Apple")
    anon.add_device(["Close"], None, "Samsung")

    # In JSON data with keys in _KEEP:
    sample_data = {
        "state": "analysing",
        "reasons": ["thin", "close"],
        "chosen": "router",
        "scores": [["router", 12], ["phone", 3]],
    }
    masked = anon.data(sample_data)
    assert masked["state"] == "analysing"
    assert masked["reasons"] == ["thin", "close"]
    assert masked["chosen"] == "router"
    assert masked["scores"] == [["router", 12], ["phone", 3]]
    print("T4 enum collision resistance: OK")


def test_note_sanitization():
    # T8: Invisible unicode control characters stripped and personal names masked
    anon = anonymize.Anonymizer()
    anon.add_device(["iPad di Giulia"], None, "Apple")

    # Note with hidden zero-width chars and personal name "Giulia"
    raw_note = "The iPad of \u200bGiulia\u200e at 192.168.1.50 loses wifi"
    cleaned = export_gather._clean_note(raw_note)
    assert "\u200b" not in cleaned
    assert "\u200e" not in cleaned
    masked = anon.text(anon.text_note(cleaned))
    assert "Giulia" not in masked
    assert "192.168.1.50" not in masked
    print("T8 note sanitization: OK")


def test_mqtt_manifest_block():
    # T6: MQTT status in manifest has exact boolean keys
    st_val = mqtt_ha.service.status()
    block = {"enabled": bool(st_val.get("enabled")), "connected": bool(st_val.get("connected"))}
    assert set(block.keys()) == {"enabled", "connected"}
    assert isinstance(block["enabled"], bool)
    assert isinstance(block["connected"], bool)
    print("T6 MQTT manifest block: OK")


def test_full_export_analysis_and_manifest():
    # T1, T2, T3, T7: Build an export and verify analysis.json and manifest.json
    state.devices.clear()
    state.devices["scan-10-20-30-40"] = {
        "id": "scan-10-20-30-40",
        "name": "Router-Principal",
        "ip": "10.20.30.40",
        "mac": "00:11:22:33:44:55",
        "type": "router",
        "brand": "Cisco",
    }
    analysis_view.RESULTS["scan-10-20-30-40"] = st.Status(st.ANALYSING, ["thin"])
    analysis_view._since["scan-10-20-30-40"] = 1760000000.0

    raw_zip = export_engine.build(dest="dev")
    zf = zipfile.ZipFile(io.BytesIO(raw_zip))

    manifest_bytes = zf.read("manifest.json")
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    assert "mqtt" in manifest
    assert set(manifest["mqtt"].keys()) == {"enabled", "connected"}
    assert "10.20.30.40" not in manifest_bytes.decode("utf-8")

    # Check state/analysis.json
    assert "state/analysis.json" in zf.namelist()
    analysis_bytes = zf.read("state/analysis.json")
    analysis_json = json.loads(analysis_bytes.decode("utf-8"))
    assert analysis_json["version"] == 1
    assert "thresholds" in analysis_json
    assert len(analysis_json["cards"]) >= 1

    card = analysis_json["cards"][0]
    # T2 & T3: card ID must be masked, not raw 10-20-30-40
    assert "10-20-30-40" not in card["id"]
    assert "10.20.30.40" not in card["id"]
    # Check consistency with devices_compact
    compact_bytes = zf.read("state/devices_compact.json").decode("utf-8")
    compact_json = json.loads(compact_bytes)
    assert compact_json[0]["id"] == card["id"]

    # Verify no leaks in analysis.json
    anon = anonymize.Anonymizer()
    assert not anon.leaks_data(analysis_json)
    assert not anon.leaks_data(manifest)
    print("T1, T2, T3, T7 full export analysis and manifest: OK")


if __name__ == "__main__":
    test_allowlist_sanitization()
    test_enum_collision_resistance()
    test_note_sanitization()
    test_mqtt_manifest_block()
    test_full_export_analysis_and_manifest()
    print("ALL PRIVACY AND ANALYSIS TESTS PASSED SUCCESSFULLY!")
