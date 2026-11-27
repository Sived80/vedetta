# SPDX-License-Identifier: GPL-3.0-only — additional terms in NOTICE
"""The parts of the network behind the router (1.0 step P11, S41) that need no network: the networks.json Vedetta starts with, which rows of the list of new
devices are behind the router, the new-device alerts of each address in the journal, and how long Vedetta waits between two sweeps of a routed network."""
import ipaddress
import json
import os
import re

SWEEP_S_DEFAULT = 900          # routedwatch.ROUTED_SWEEP_S of the P11 plan: the value when the code under test does not have it (the base code)


def networks_file(cidr: str, network_id: str = "lab20", touch: str = "presence", state: str = "confirmed") -> dict:
    """The content of networks.json with one network behind the router, written as the panel writes it (network_store._row)."""
    return {"networks": [{"id": network_id, "cidr": cidr, "via": ["routed"], "touch": touch, "state": state, "exclude": []}]}


def write_networks(data_dir: str, content: dict) -> str:
    """Writes networks.json in Vedetta's data folder before it starts; returns its path."""
    path = os.path.join(data_dir, "networks.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(content, f, indent=1)
    return path


def listed_in(rows: list, cidr: str) -> set:
    """The addresses inside `cidr` among the rows of /api/new-devices (a row behind the router may have no MAC)."""
    net = ipaddress.ip_network(cidr)
    out = set()
    for row in rows or ():
        try:
            if ipaddress.ip_address(str(row.get("ip") or "")) in net:
                out.add(str(row["ip"]))
        except ValueError:
            continue
    return out


def alerts_by_ip(lines, key: str = "alert.new_device") -> dict:
    """{address: how many alerts of this kind} from the lines of journal.jsonl; lines that are not JSON are skipped."""
    out: dict = {}
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("key") == key:
            ip = str((entry.get("params") or {}).get("ip") or "-")
            out[ip] = out.get(ip, 0) + 1
    return out


def sweep_seconds(code_dir: str) -> int:
    """ROUTED_SWEEP_S as written in the code under test (app/routedwatch.py), SWEEP_S_DEFAULT when the file or the constant is not there. Read, never changed."""
    try:
        with open(os.path.join(code_dir, "app", "routedwatch.py"), encoding="utf-8") as f:
            found = re.search(r"^ROUTED_SWEEP_S\s*(?::\s*\w+\s*)?=\s*(\d+)", f.read(), re.MULTILINE)
    except OSError:
        return SWEEP_S_DEFAULT
    return int(found.group(1)) if found else SWEEP_S_DEFAULT
