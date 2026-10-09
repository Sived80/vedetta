"""The export for the developer, with a house full of random values: private and public IP addresses, MAC addresses, host names, DNS names
(with their domains), names of people, e-mail addresses and IPv6 addresses, put where the app keeps them (devices, log, journal, settings,
DHCP and Bonjour memory, the database). After the masking none of them may be left in any file of the export, whatever the seed.
The seeds are fixed, so a failure can be repeated; change them (or add one) to look at another house."""
import io
import json
import os
import random
import sqlite3
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_zip as export, export_engine as E  # noqa: E402
from app.storage import devices_config  # noqa: E402
from app.scan import dhcp, mdns_listener  # noqa: E402
from app.ha import ha_registry  # noqa: E402
from app import paths  # noqa: E402
from app.storage import history as history_mod  # noqa: E402
from app.storage.history import History  # noqa: E402
from app.state import state  # noqa: E402

WORDS = ["kitchen", "salotto", "garage", "office", "studio", "cantina", "orto", "nas", "cam", "tv", "printer", "hue", "pi", "esp32", "shelly",
         "tasmota", "sonos", "laptop", "iphone", "galaxy", "ipad", "bedroom", "camera", "stampante", "router"]
FIRST = ["Marta", "Giulia", "Luca", "Paolo", "Chiara", "Anna", "Davide", "Elena", "Sofia", "Matteo", "Ines", "Tomas", "Jana", "Petr"]
DOMAINS = ["casa-rossi.example.com", "bianchi.duckdns.org", "mynas.synology.me", "home.lan", "fritz.box", "localdomain",
           "office.internal.example.net", "famiglia-verdi.dyndns.org"]
PUBLIC_FIRST = [5, 31, 45, 62, 78, 93, 109, 151, 185, 212]


def house(seed: int) -> dict:
    r = random.Random(seed)
    hexs = lambda n: "".join(r.choice("0123456789abcdef") for _ in range(n))   # noqa: E731
    devices, secrets = [], set()
    for i in range(r.randint(18, 28)):
        net = r.choice(["192.168.%d" % r.randint(0, 250), "10.%d.%d" % (r.randint(0, 250), r.randint(0, 250)), "172.%d.%d" % (r.randint(16, 31), r.randint(0, 250))])
        ip = "%s.%d" % (net, r.randint(2, 250))
        mac = ":".join(hexs(2) for _ in range(6))
        word = r.choice(WORDS)
        host = "%s-%s" % (word, hexs(4))
        dns = "%s-%s.%s" % (r.choice(WORDS), hexs(3), r.choice(DOMAINS))
        owner = "%s's %s" % (r.choice(FIRST), r.choice(["iPhone", "iPad", "Galaxy", "laptop", "Pixel"]))
        d = {"id": "d%d" % i, "ip": ip, "mac": mac, "host": host, "dns": dns, "owner": owner,
             "public": "%d.%d.%d.%d" % (r.choice(PUBLIC_FIRST), r.randint(1, 254), r.randint(1, 254), r.randint(1, 254)),
             "email": "%s.%s@%s" % (r.choice(FIRST).lower(), hexs(3), r.choice(["example.com", "mail.example.org"])),
             "v6": "2001:db8:%s:%s::%s" % (hexs(4), hexs(4), hexs(2))}
        devices.append(d)
        secrets.update([ip, mac, host, dns, owner, d["public"], d["email"], d["v6"]])
    return {"devices": devices, "secrets": secrets}


def set_up(h: dict, tmp: Path) -> None:
    D, now = E.day_start, time.time()
    iso = lambda ts: datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")      # noqa: E731
    paths.DATA_DIR = tmp
    devices_config.DEVICES_PATH = tmp / "devices.yaml"
    (tmp / "devices.yaml").write_text(yaml.safe_dump({"devices": [
        {"id": d["id"], "ip": d["ip"], "adapter": "ping", "name": d["owner"]} for d in h["devices"]]}), encoding="utf-8")
    lines = []
    for d in h["devices"]:
        lines += [f"{iso(now - 30)}\tINFO\treverse name of {d['ip']} is {d['dns']}",
                  f"{iso(now - 29)}\tINFO\t{d['owner']} ({d['mac']}) answered from {d['ip']} as {d['host']}",
                  f"{iso(now - 28)}\tWARNING\tcertificate for {d['dns']} seen from {d['public']} ({d['v6']}), contact {d['email']}"]
    (tmp / "dashboard.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (tmp / "journal.jsonl").write_text("\n".join(json.dumps({"id": n, "ts": now - 20 - n, "level": "normal", "key": "journal.online", "icon": "power",
                                                            "params": {"name": d["owner"], "ip": d["ip"], "host": d["dns"]}})
                                                for n, d in enumerate(h["devices"])) + "\n", encoding="utf-8")
    first = h["devices"][0]
    (tmp / "settings.json").write_text(json.dumps({"mqtt_password": "hunter2", "mqtt_host": first["dns"], "note": f"{first['owner']} at {first['ip']}",
                                                   "mail": first["email"]}), encoding="utf-8")
    db = History(tmp / "vedetta.db")
    for d in h["devices"]:
        db.record_presence(d["id"], d["ip"], d["mac"], True, now - 100)
        db._db.execute("INSERT INTO known_macs (mac, first_seen, ip, vendor, hostname, status) VALUES (?, ?, ?, 'Acme', ?, 'known')",
                       (d["mac"], D(5), d["ip"], d["host"]))
    db._db.commit()
    history_mod.history = db
    state.devices.clear()
    dhcp.seen.clear(); mdns_listener.by_mac.clear(); mdns_listener.by_ip.clear()
    ha_registry._state["by_mac"] = {}; ha_registry._state["by_ip"] = {}
    for d in h["devices"]:
        state.devices[d["id"]] = {"id": d["id"], "ip": d["ip"], "mac": d["mac"], "name": d["owner"], "brand": "Acme", "scanned_ports": [], "online": True,
                                  "extra": {"hostname": d["host"], "dns": d["dns"]}}
        dhcp.seen[d["mac"].lower()] = {"hostname": d["host"], "seen": now}
        mdns_listener.by_mac[d["mac"].lower()] = {"name": d["owner"], "ip": d["ip"]}
        mdns_listener.by_ip[d["ip"]] = {"name": d["owner"]}


def texts_of(blob: bytes, tmp: Path) -> dict[str, str]:
    """Every file of the export as text; the database as all the values of all its tables."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    out = {}
    for n in z.namelist():
        raw = z.read(n)
        if n == "data/vedetta.db":
            f = tmp / "check_fuzz.db"
            f.write_bytes(raw)
            con = sqlite3.connect(f)
            parts = []
            for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                parts += [" ".join(str(v) for v in row) for row in con.execute(f"SELECT * FROM {table}").fetchall()]
            con.close()
            out[n] = "\n".join(parts)
        else:
            out[n] = raw.decode("utf-8", "replace")
    return out


problems = []
for seed in (11, 2026, 90210):
    tmp = Path(tempfile.mkdtemp())
    h = house(seed)
    set_up(h, tmp)
    files = texts_of(E.build("dev", None, None), tmp)
    assert "manifest.json" in files and len(files) > 5, list(files)
    for secret in sorted(h["secrets"]):
        for name, text in files.items():
            if secret.lower() in text.lower():
                problems.append((seed, name, secret))
    # for me nothing is masked (so the check above is not an empty promise): the values are there
    mine = texts_of(E.build("me", None, None), tmp)
    assert h["devices"][0]["ip"] in mine["data/settings.json"] and h["devices"][0]["owner"] in mine["data/dashboard.log"], "il test vede i valori quando non sono nascosti"

by_kind = {}
for seed, name, secret in problems:
    kind = ("email" if "@" in secret else "mac" if secret.count(":") == 5 else "ipv6" if "::" in secret else "ip" if secret.replace(".", "").isdigit()
            else "name" if "'s " in secret else "dns" if "." in secret else "host")
    by_kind.setdefault(kind, []).append((seed, name, secret))
assert not problems, "valori casuali rimasti nell'export per lo sviluppatore: " + "; ".join(
    f"{k}: {len(v)} (es. {v[0][2]} in {v[0][1]})" for k, v in sorted(by_kind.items()))
print("TUTTO OK")
