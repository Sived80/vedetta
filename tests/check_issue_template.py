"""The GitHub issue form for wrongly recognised devices: valid, asks for the encrypted export only, nothing personal."""
import re
from pathlib import Path

import yaml

path = Path(__file__).resolve().parent.parent / ".github" / "ISSUE_TEMPLATE" / "device-misidentified.yml"
form = yaml.safe_load(path.read_text(encoding="utf-8"))
assert {"name", "description", "body"} <= set(form) and form["title"].startswith("[Device]")
ids = [b["id"] for b in form["body"] if "id" in b]
assert len(ids) == len(set(ids)) and {"version", "real_device", "shown", "expected", "privacy"} <= set(ids), ids
for block in form["body"]:
    assert block["type"] in {"markdown", "input", "textarea", "dropdown", "checkboxes"}, block["type"]
    if block["type"] != "markdown":
        assert block["attributes"].get("label"), block
        if block["type"] == "dropdown":
            assert len(block["attributes"]["options"]) >= 2
text = path.read_text(encoding="utf-8")
assert "Encrypted export" in text and "never attach the plain" in text.lower().replace("**", "")
assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text.replace("0.3.9", "")), "no address in the template"
assert not re.search(r"[\w.+-]+@[\w-]+\.\w+", text), "no email in the template"
privacy = next(b for b in form["body"] if b.get("id") == "privacy")
assert all(o["required"] for o in privacy["attributes"]["options"])
print("TUTTO OK")
