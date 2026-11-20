"""The promise of PRIVACY.md: names and domains are masked in the export for the developer. Found by the global review: a short first name (Leo, Eva, Ugo: three letters; Jo: two) was taken for a
«technical word» and stayed readable, and a domain with an ending that is not in the short list (my.dyn.nu) stayed readable too. The words that really are technical (pve, nas, cam, tv...) are a short
white list, the rest is masked; the domain endings cover the dynamic-DNS and country ones, while the names of files (dashboard.log, run.sh, app.js, lib.rs, setup.py) stay what they are."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export.anonymize import Anonymizer  # noqa: E402

# names of three letters: masked, and the audit sees what is left (two letters stay noise, a known limit: «ab» is as likely a code as a name)
for name in ("Leo", "Eva", "Ugo", "Max", "Ale", "Tom"):
    a = Anonymizer()
    assert a.add_device([name]) is not None, name
    masked = a.text(f"host {name} online")
    assert name not in masked, (name, masked)
    assert a.leaks(masked) == [] and a.leaks(f"host {name} online"), (name, a.leaks(f"host {name} online"))

# technical words stay readable (a clue for the debug) and are not given a placeholder
for word in ("pve", "nas", "cam", "tv", "pc", "hub", "ups", "dns", "nvr", "plc", "ab"):
    a = Anonymizer()
    assert a.add_device([word]) is None, word
    assert a.text(f"{word} is on") == f"{word} is on", word

# domains: the dynamic-DNS and country endings are masked
for domain in ("my.dyn.nu", "family.example.su", "home.example.tk", "casa.example.in", "mio.example.fr", "x.example.jp"):
    a = Anonymizer()
    out = a.text(f"connected to {domain} ok")
    assert domain.split(".")[0] not in out.replace("connected to", "") or domain not in out, (domain, out)
    assert domain not in out, (domain, out)

# what is not a domain stays: file names, versions, the public infrastructure
for same in ("dashboard.log", "devices.yaml", "run.sh", "app.js", "lib.rs", "setup.py", "state.json", "version 0.6.3", "see github.com for it", "cache.pyc"):
    assert Anonymizer().text(same) == same, (same, Anonymizer().text(same))

# the recipients of the alerts (notify services of Home Assistant) carry the name of a person or a phone: masked, the same one always the same;
# the generic services stay (18/11: a recipient that was not also a card name went out as it was)
a = Anonymizer()
got = a.text('[{"service": "notify.mobile_app_marcos_iphone", "delay_s": 0}, {"service": "notify.tv_salotto"}] notify.mobile_app_marcos_iphone notify.notify')
assert "marcos" not in got and "salotto" not in got and got.count("notify.recipient_1") == 2 and "notify.recipient_2" in got and "notify.notify" in got, got
assert a.text(got) == got and a.mapping()["notify_services"]["notify.recipient_1"] == "notify.mobile_app_marcos_iphone"
print("ALL OK")
