"""Verifica la regola generica del titolo pagina web (senza dipendenze extra).
Esecuzione dalla cartella DASHBOARD:  python tests/check_titles.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "vedetta"))

from app.formatters import should_show_title, update_generic_titles  # noqa: E402


def dev(i, title):
    return {"id": f"d{i}", "scan_info": {"http_title": title}}


# Dispositivi simulati: i titoli generici compaiono su piu' host (anche con
# maiuscole/spazi diversi), quelli identificativi su uno solo.
DEVICES = [
    dev(1, "Login"), dev(2, "login "), dev(3, "Login"),
    dev(4, "Index of /"), dev(5, "Index  of /"),
    dev(6, "Welcome to nginx!"), dev(7, "Welcome to nginx!"),
    dev(8, "Grafana"), dev(9, "Home Assistant"),
    dev(10, "Proxmox Virtual Environment"), dev(11, "Router Login"),
    dev(12, "Login Request"), dev(13, "Login Request"),
    dev(14, "Site doesn't have a title (text/html; charset=utf-8)."),
    dev(15, "Pannello NAS\nRequested resource was /login.html"),
    dev(16, "Camera 3\nDid not follow redirect to http://10.0.0.5/signin"),
    dev(17, "404 Not Found"),
    dev(18, None),
]
update_generic_titles(DEVICES)

HIDE = ["Login", "Index of /", "Welcome to nginx!", "Login Request",
        "Site doesn't have a title (text/html; charset=utf-8).", "404 Not Found", "404",
        "Pannello NAS\nRequested resource was /login.html",
        "Camera 3\nDid not follow redirect to http://10.0.0.5/signin", None, ""]
SHOW = ["Grafana", "Home Assistant", "Proxmox Virtual Environment", "Router Login"]

errors = 0
for t in HIDE:
    ok = not should_show_title(t)
    errors += not ok
    print(("OK  " if ok else "FAIL"), "nascosto:", repr(t))
for t in SHOW:
    ok = should_show_title(t)
    errors += not ok
    print(("OK  " if ok else "FAIL"), "mostrato:", repr(t))
print("Errori:", errors)
sys.exit(1 if errors else 0)
