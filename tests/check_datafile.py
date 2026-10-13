"""The data files shipped with the app (app/data/*.json: kinds, integrations, logos, signatures) are read in one place. A file that cannot be read (missing, not JSON, not an object, no such key) used to empty
the recognition without a trace in three of the four readers (finding R4b of the global review, rule: no empty answer without a trace). Now it is told ONCE per file in the log at warning level, and the answer
is None (the caller uses its own empty value and the service goes on). A good file says nothing. Also: every file the app ships is readable, so a file lost in a build is seen by the gate."""
import logging
import os
import sys
import tempfile
from pathlib import Path

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import applog, datafile  # noqa: E402

records: list = []


class Catch(logging.Handler):
    def emit(self, record):
        records.append(record)


applog.logger.addHandler(Catch())
tmp = Path(tempfile.mkdtemp())


def warnings() -> list:
    return [r for r in records if r.levelno == logging.WARNING]


# a good file: the value, and nothing is said
(tmp / "good.json").write_text('{"things": [1, 2, 3]}', encoding="utf-8")
assert datafile.read(tmp / "good.json", "things", what="Things") == [1, 2, 3]
assert not warnings(), "a good file says nothing"

# three ways to be unreadable: None, ONE warning per file however many times it is asked, and the text says what is empty now
(tmp / "broken.json").write_text("{not json", encoding="utf-8")
(tmp / "nokey.json").write_text('{"other": []}', encoding="utf-8")
for name in ("broken.json", "nokey.json", "missing.json"):
    del records[:]
    for _ in range(3):
        assert datafile.read(tmp / name, "things", what="Things table") is None, name
    assert len(warnings()) == 1, (name, [r.getMessage() for r in records])
    assert "Things table" in warnings()[0].getMessage() and name in warnings()[0].getMessage(), warnings()[0].getMessage()

# the default of the caller is what an unreadable file answers; a null that the file really holds is returned as it is
(tmp / "null.json").write_text('{"things": null}', encoding="utf-8")
assert datafile.read(tmp / "gone.json", "things", what="Things table", default=[]) == []
assert datafile.read(tmp / "null.json", "things", what="Things table", default=[]) is None

# a file that is JSON but not an object is a broken build: it stops loudly, it is not turned into an empty table
(tmp / "list.json").write_text("[1, 2]", encoding="utf-8")
try:
    datafile.read(tmp / "list.json", "things", what="Things table")
    raise AssertionError("a list instead of an object must stop")
except TypeError:
    pass

# a file that is read again after it was repaired answers normally (the warning was only about the past)
(tmp / "broken.json").write_text('{"things": ["ok"]}', encoding="utf-8")
assert datafile.read(tmp / "broken.json", "things", what="Things table") == ["ok"]

# every file that the app ships, with the key its reader asks for
SHIPPED = {"device_kinds.json": "kinds", "ha_integrations.json": "integrations", "brand_logos.json": "logos", "signatures.json": "signatures", "brands.json": "aliases", "dhcp_vendor_classes.json": "console", "local_api.json": "api_types", "type_words.json": "groups", "product_words.json": "products"}
for name, key in SHIPPED.items():
    del records[:]
    value = datafile.read(datafile.DATA_DIR / name, key, what=name)
    assert value and not warnings(), (name, key, [r.getMessage() for r in records])
# the three readers that used to say nothing: with the files missing they answer empty and say so, once each
from app.ha import ha_type_evidence  # noqa: E402
from app.recognition import brand_logo  # noqa: E402
real_dir, real_logo = datafile.DATA_DIR, brand_logo.DATA_PATH
empty_dir = Path(tempfile.mkdtemp())
datafile.DATA_DIR, brand_logo.DATA_PATH = empty_dir, empty_dir / "brand_logos.json"
ha_type_evidence._ha_table_cache = None
brand_logo._index.cache_clear()
del records[:]
assert ha_type_evidence._read_kind_rows() == [] and ha_type_evidence._ha_integrations() == {} and brand_logo._index() == {}
told = " ".join(r.getMessage() for r in warnings())
assert len(warnings()) == 3 and "device kinds" in told and "Home Assistant integrations" in told and "brand logos" in told, told
datafile.DATA_DIR, brand_logo.DATA_PATH = real_dir, real_logo
ha_type_evidence._ha_table_cache = None
brand_logo._index.cache_clear()
assert ha_type_evidence._read_kind_rows() and ha_type_evidence._ha_integrations() and brand_logo._index(), "the real tables are read again"
# the consoles of the DHCP fingerprint: the real table names them, a lost table recognises none and says so once
from app.ha import identity_shift  # noqa: E402
assert all(identity_shift.family(c) == "console" for c in ("ps3", "PS4 x", "ps5", "PlayStation", "Xbox 360", "Nintendo Switch")) and identity_shift.family("msft 5.0") == "windows"
datafile.DATA_DIR = empty_dir
identity_shift._console_classes.cache_clear()
del records[:]
assert identity_shift.family("ps5") != "console" and identity_shift.family("xbox") != "console"
assert len(warnings()) == 1 and "console" in warnings()[0].getMessage(), [r.getMessage() for r in records]
datafile.DATA_DIR = real_dir
identity_shift._console_classes.cache_clear()
assert identity_shift.family("ps5") == "console", "the real table is read again"
# the generic titles of the Home Assistant entries: the real table refuses them as a name, a lost table refuses none and says so once
from app.ha import ha_registry  # noqa: E402
assert all(ha_registry._usable_name(t) is None for t in ("MQTT", " FRITZ!Box ", "Home Assistant", "Shelly", "Tasmota", "ESPHome", "Mobile App")) and ha_registry._usable_name("Cancello") == "Cancello"
datafile.DATA_DIR = Path(tempfile.mkdtemp())      # a folder not yet reported: the warning is once per file
ha_registry._generic_titles.cache_clear()
del records[:]
assert ha_registry._usable_name("Shelly") is not None
assert len(warnings()) == 1 and "integrations" in warnings()[0].getMessage(), [r.getMessage() for r in records]
datafile.DATA_DIR = real_dir
ha_registry._generic_titles.cache_clear()
assert ha_registry._usable_name("Shelly") is None, "the real table is read again"
# the local interfaces: the real table, and a lost table that has no interface and no platform adapter and says so once
W = ha_type_evidence.W_DECLARED
assert ha_type_evidence._api_types() == {"shelly": ("iot", W), "tasmota": ("iot", 2), "esphome": ("iot", 3), "cast": ("media", W), "roku": ("media", W), "sonos": ("audio", W)}, ha_type_evidence._api_types()
assert ha_type_evidence._platform_adapters() == ("shelly",)
datafile.DATA_DIR = Path(tempfile.mkdtemp())
ha_type_evidence._api_types.cache_clear()
ha_type_evidence._platform_adapters.cache_clear()
del records[:]
assert ha_type_evidence._api_types() == {} and ha_type_evidence._platform_adapters() == ()
assert len(warnings()) == 1 and "local interfaces" in warnings()[0].getMessage(), [r.getMessage() for r in records]
datafile.DATA_DIR = real_dir
ha_type_evidence._api_types.cache_clear()
ha_type_evidence._platform_adapters.cache_clear()
# the keywords of the types: the real table has the seven groups, a lost table has none (no word recognises anything) and says so once
from app.ha import ha_type_text  # noqa: E402
assert list(ha_type_text.rules()) == ["iot", "printer", "media", "audio", "router", "pc", "server"], list(ha_type_text.rules())
assert "epson" in ha_type_text.rules()["printer"]["subs"] and "server" in ha_type_text.rules()["server"]["toks"] and "stampante" not in ha_type_text.rules()["printer"]["subs"]
datafile.DATA_DIR = Path(tempfile.mkdtemp())
ha_type_text.rules.cache_clear()
del records[:]
assert ha_type_text.rules() == {}
assert len(warnings()) == 1 and "type words" in warnings()[0].getMessage(), [r.getMessage() for r in records]
datafile.DATA_DIR = real_dir
ha_type_text.rules.cache_clear()
# the product words of the export labels: the real table gives the first matching label; a lost table gives none and says so once
from app.export import anonymize_patterns  # noqa: E402
labels = {name: next((label for label, rx in anonymize_patterns.products() if rx.search(name)), None) for name in ("iPhone di Caio", "Apple Watch", "Galaxy S24", "ps5", "Xbox", "Sensore")}
assert labels == {"iPhone di Caio": "iPhone", "Apple Watch": "AppleWatch", "Galaxy S24": "Galaxy", "ps5": "PlayStation", "Xbox": "Xbox", "Sensore": None}, labels
datafile.DATA_DIR = Path(tempfile.mkdtemp())
anonymize_patterns.products.cache_clear()
del records[:]
assert anonymize_patterns.products() == ()
assert len(warnings()) == 1 and "product words" in warnings()[0].getMessage(), [r.getMessage() for r in records]
datafile.DATA_DIR = real_dir
anonymize_patterns.products.cache_clear()
# the brand rules shipped with the app: if the file is missing it is told once; the user's own file may be missing without a word
from app.recognition import brands  # noqa: E402
real_defaults, real_user = brands._DEFAULTS_PATH, brands._USER_PATH
brands._DEFAULTS_PATH = tmp / "no-brands.json"
brands._USER_PATH = tmp / "no-user-brands.json"
del records[:]
assert brands._read(brands._USER_PATH) == {} and not warnings(), "the user's file may be missing"
assert brands._read(brands._DEFAULTS_PATH) == {} and brands._read(brands._DEFAULTS_PATH) == {}
assert len(warnings()) == 1 and "no-brands.json" in warnings()[0].getMessage(), [r.getMessage() for r in records]
brands._DEFAULTS_PATH, brands._USER_PATH = real_defaults, real_user
print("TUTTO OK")
