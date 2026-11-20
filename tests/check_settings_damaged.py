"""A damaged settings.json is never lost in silence (storage/settings.py): the readers used to fall back to the defaults, and the next
save wrote the defaults over the file, MQTT included. Now the damaged file is copied aside once as settings.json.broken-<time>, the
log says so, damaged() tells the start-up journal, and a save goes on from the defaults. When the copy itself fails, nothing is
saved over the file. A missing file is a new install, not a damage.
    python tests/check_settings_damaged.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.storage import settings  # noqa: E402

folder = settings.SETTINGS_PATH.parent


def copies():
    return sorted(p.name for p in folder.glob("settings.json.broken-*"))


def reset(text):
    for p in folder.glob("settings.json*"):
        p.unlink()
    settings._damaged.clear()
    if text is not None:
        settings.SETTINGS_PATH.write_text(text, encoding="utf-8")


# 1) missing file: defaults, no copy, no damage
reset(None)
assert settings.load() == settings.DEFAULTS and settings.damaged() == {} and copies() == []

# 2) a truncated file (power cut while another program wrote it): defaults, ONE copy with the original bytes, damage reported
broken = '{"poll_interval": 60, "mqtt_host": "10.0.0.2", "mqtt_password": "s3cr'
reset(broken)
assert settings.load() == settings.DEFAULTS
assert settings.mqtt_load()["mqtt_host"] == settings.MQTT_DEFAULTS["mqtt_host"]
settings.poll_interval()
assert len(copies()) == 1, copies()                                         # read many times, copied once
assert (folder / copies()[0]).read_text(encoding="utf-8") == broken
d = settings.damaged()
assert d["copy"] == copies()[0] and "not JSON" in d["why"] and not d.get("failed"), d

# 3) a save afterwards goes on from the defaults (the original is safe in the copy) and ends the damage
settings.update({"poll_interval": 120})
assert settings.load()["poll_interval"] == 120 and settings.damaged().get("saved_over") is True

# 4) a new damage later in the same run gets its own copy
os.utime(settings.SETTINGS_PATH)
settings.SETTINGS_PATH.write_text("[1, 2]", encoding="utf-8")              # JSON, but not an object
import time  # noqa: E402
time.sleep(1.1)                                                             # the copy name has the second in it
settings.load()
assert len(copies()) == 2 and "not a JSON object" in settings.damaged()["why"], (copies(), settings.damaged())

# 5) the copy fails (a full disk, a read-only folder): nothing is saved over the damaged file
reset("{oops")
real_copy = settings.shutil.copy2


def no_room(*a, **k):
    raise OSError("No space left on device")


settings.shutil.copy2 = no_room
assert settings.load() == settings.DEFAULTS and settings.damaged()["failed"] is True
try:
    settings.update({"poll_interval": 60})
    raise AssertionError("saved over a damaged file that could not be copied")
except OSError:
    pass
assert settings.SETTINGS_PATH.read_text(encoding="utf-8") == "{oops" and copies() == []
settings.shutil.copy2 = real_copy

# 6) a good file: read as before, no damage
reset('{"poll_interval": 15, "miss_limit": 5}')
assert settings.load()["poll_interval"] == 15 and settings.miss_limit() == 5 and settings.damaged() == {}
print("check_settings_damaged: ok")
