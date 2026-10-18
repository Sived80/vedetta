"""The configuration of the add-on is described once and completely (config.yaml, translations/, run.sh, DOCS.md): every option of the schema has a name and a
description in each language, no translation for an option that does not exist, no two options with the same name or the same description, every required
option has its default, the options that switch the functions off reach the app (run.sh) and are explained in DOCS.md."""
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent / "vedetta"
cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
schema, options = cfg["schema"], cfg["options"]
langs = sorted(p.stem for p in (ROOT / "translations").glob("*.yaml"))
assert langs == ["cs", "en", "it"], ("a translation for each language of the app", langs)

# required options (no "?") have a default; the default is an option of the schema
required = {k for k, v in schema.items() if not str(v).endswith("?")}
assert required <= set(options), ("required options without a default", sorted(required - set(options)))
assert set(options) <= set(schema), ("a default for an option that is not in the schema", sorted(set(options) - set(schema)))
assert all(options[k] is not None for k in options)

# the switches: booleans on by default, one per function that reaches the internet
switches = [k for k in schema if k.startswith("internet_") and schema[k] == "bool"]
assert switches == ["internet_public_ip", "internet_path", "internet_mac_database"], switches
assert all(options[k] is True for k in switches), "the functions start on (they can be switched off before the first start)"
assert schema["internet_path_target"] == "str?" and "internet_path_target" not in options, "the target is optional and has no default in the file (the app has it)"

names_seen = {}
for lang in langs:
    tr = yaml.safe_load((ROOT / "translations" / (lang + ".yaml")).read_text(encoding="utf-8"))
    conf = tr["configuration"]
    assert set(conf) == set(schema), (lang, "the translation and the schema must have the same options", sorted(set(conf) ^ set(schema)))
    names, descriptions = [], []
    for key, entry in conf.items():
        assert set(entry) == {"name", "description"}, (lang, key, "name and description, nothing else")
        assert entry["name"].strip() and entry["description"].strip(), (lang, key, "empty")
        assert len(entry["description"]) < 300, (lang, key, "a description is one or two sentences", len(entry["description"]))
        names.append(entry["name"].strip().lower())
        descriptions.append(entry["description"].strip().lower())
    assert len(set(names)) == len(names), (lang, "two options with the same name")
    assert len(set(descriptions)) == len(descriptions), (lang, "two options with the same description")
    names_seen[lang] = names

# what the switches are for is passed to the app, and the names of the options are explained in DOCS.md
run_sh = (ROOT / "run.sh").read_text(encoding="utf-8")
for key, var in (("internet_public_ip", "VEDETTA_INTERNET_PUBLIC_IP"), ("internet_path", "VEDETTA_INTERNET_PATH"),
                 ("internet_mac_database", "VEDETTA_INTERNET_MAC_DB"), ("internet_path_target", "VEDETTA_INTERNET_PATH_TARGET")):
    assert "'%s'" % key in run_sh and var in run_sh, (key, "run.sh must pass it to the app")
docs = (ROOT / "DOCS.md").read_text(encoding="utf-8")
missing = [k for k in schema if "`%s`" % k not in docs and not k.startswith("mqtt_")]
assert not missing, ("options not explained in DOCS.md", missing)
assert "`mqtt_host`" in docs
print("TUTTO OK")
