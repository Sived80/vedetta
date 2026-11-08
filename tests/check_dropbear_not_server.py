"""An open SSH port served by Dropbear is not a clue for "server". Dropbear is the SSH server made for small embedded systems (access
points, routers, switches, firmware of appliances); servers and PCs use OpenSSH. Real case (08/11/2026): an access point with SSH by
Dropbear and the word "access point" went to the Servers group, 4 points (SSH) against 3 (the word). The port number alone and OpenSSH
keep counting for "server" as before. A generic rule on the SSH software, not on a brand.
    python tests/check_dropbear_not_server.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import ha_type_evidence as te  # noqa: E402


def card(label, confirmed=True, name="10.0.0.60"):
    return {"ip": "10.0.0.60", "name": name, "scanned_ports": [{"label": label, "confirmed": confirmed, "category": "remote"}]}


def server_points(c):
    return [e for e in te.type_evidence(dict(c)) if e["group"] == "server" and e["family"].startswith("port:22")]


assert not server_points(card("22 · Dropbear sshd")), "Dropbear: no points to server"
assert not server_points(card("22 · dropbear sshd 2022.83")), "any version, any case"
assert server_points(card("22 · OpenSSH 9.6p1 Ubuntu")), "OpenSSH still counts for server"
assert server_points(card("22 · ssh", confirmed=False)), "the port number alone still counts (weak) as before"

# the real case: an access point with Dropbear and the word in its name goes to the network devices group
ap = card("22 · Dropbear sshd", name="Wall access point")
scores = te.type_scores(dict(ap))
assert scores.get("router", 0) > scores.get("server", 0), scores
print("check_dropbear_not_server: ok")
