# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""Names a device or a person wrote that the export for the developer must mask too (review of 19/11, all values invented):
- the names a deep search read from the device itself: UPnP friendly name, NetBIOS name, ONVIF name, the name its local interface gives
  (ESPHome, Shelly, Sonos...), the name in its web page title and in its certificate (only when they look like a name), the nmap host name;
  also those of devices no longer on the board, kept in the history of the searches (scans.result_json);
- the names kept in the database for removed cards and guests: mac_memory.name / dhcp_name, known_macs.hostname, mac_takeover.carried_name / old_dhcp_name / new_dhcp_name;
- a password or token written in a query string (access_token=, pwd=, auth=, key=), as PRIVACY.md promises.
Generic titles ("404 Not Found", "Login") stay readable: they are clues, not names."""
import json
import os
import sys
import tempfile
import time

os.environ["VEDETTA_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.export import export_zip  # noqa: E402
from app.export.anonymize import Anonymizer  # noqa: E402
from app.storage.history import history  # noqa: E402

now = time.time()
card = {"id": "d1", "name": "Media box", "ip": "192.168.1.30", "mac": "B8:27:EB:00:10:30", "brand": "Roku",
        "scan_info": {"upnp_name": "Roku di Mario Bianchi", "netbios_name": "MARIOPC", "onvif_name": "Telecamera Verdi",
                      "api_name": "Luce Camera Giulia", "http_title": "Casa Neri NAS - Main Menu", "hostname": "nas-ferraris",
                      "tls_subject": "commonName=router-esposito.local/organizationName=Example"}}
old = {"upnp_name": "Stereo di Paolo Gallo", "netbios_name": "LAPTOP-COLOMBO", "http_title": "404 Not Found"}
with history._lock:
    history._db.execute("INSERT INTO scans (device_id, ts, result_json) VALUES (?, ?, ?)", ("gone", now, json.dumps(old)))
    history._db.execute("INSERT INTO mac_memory (mac, first_seen, last_seen, device_id, ip, name, dhcp_name) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        ("b8:27:eb:00:10:31", now, now, "gone2", "192.168.1.31", "Tablet di Sara Conti", "Saras-Tablet"))
    history._db.execute("INSERT INTO known_macs (mac, first_seen, ip, hostname, status) VALUES (?, ?, ?, ?, ?)",
                        ("b8:27:eb:00:10:32", now, "192.168.1.32", "Phone-of-Luca-Ricci", "known"))
    history._db.execute("INSERT INTO mac_takeover (ts, device_id, ip, old_mac, new_mac, carried_name, old_dhcp_name, new_dhcp_name, new_known) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)", (now, "d9", "192.168.1.33", "b8:27:eb:00:10:33", "b8:27:eb:00:10:34",
                                                              "Kindle di Elena Marino", "Kindle-Elena", "Echo-Lombardi"))
    history._db.commit()

anon = export_zip._collect([card])
text = json.dumps(card["scan_info"]) + " " + json.dumps(old) + " Tablet di Sara Conti Saras-Tablet Phone-of-Luca-Ricci Kindle di Elena Marino Kindle-Elena Echo-Lombardi"
masked = anon.text(text)
for secret in ("Bianchi", "MARIOPC", "Verdi", "Giulia", "Neri", "ferraris", "esposito", "Gallo", "COLOMBO", "Conti", "Saras", "Ricci", "Marino", "Elena", "Lombardi"):
    assert secret.lower() not in masked.lower(), (secret, masked)
assert "404 Not Found" in masked, masked                                           # a generic title is a clue, not a name

line = Anonymizer().text("GET /cam?access_token=abcd1234efgh&x=1 /login?pwd=hunter22 /api?auth=Zx9yW8vU /v1?key=k3y-s3cr3t-77 /ok?api_key=s3cr3tvalue")
for secret in ("abcd1234efgh", "hunter22", "Zx9yW8vU", "k3y-s3cr3t-77", "s3cr3tvalue"):
    assert secret not in line, (secret, line)
assert "/cam?" in line and "x=1" in line, line                                     # only the secret goes, the rest of the address stays
print("ALL OK")
