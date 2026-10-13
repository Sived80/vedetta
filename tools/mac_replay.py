"""Replays the real exports through the MAC layer classifier (app/macclassify.py) and tells what it would say.
  python tools/mac_replay.py [ZIP ...]      (default: every vedetta-analisi-*.zip in ~/.vedetta/exports)
Rows are rebuilt from what an export holds: presence_events (ip, mac at each online event) as ARP-like observations, mdns_seen.json (mac -> last ip),
dhcp_seen.json (no address in older versions: not used). It prints the distribution of kinds, the lenders and the conflicts, with MACs shortened.
Private data: the output is for the developer's eyes only, never to be copied into the repository."""
import json
import sqlite3
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
from app import macclassify  # noqa: E402
from app.storage.newdevices import normalize_mac  # noqa: E402


def short(mac):
    return mac[:8] + ".." + mac[-2:]


def rows_from_zip(path):
    zf = zipfile.ZipFile(path)
    tmp = Path(tempfile.mkdtemp()) / "v.db"
    tmp.write_bytes(zf.read("data/vedetta.db"))
    db = sqlite3.connect(tmp)
    agg = {}
    for ip, mac, ts in db.execute("SELECT ip, mac, ts FROM presence_events WHERE online = 1 AND mac IS NOT NULL AND ip IS NOT NULL"):
        mac = normalize_mac(mac)
        if not mac:
            continue
        r = agg.setdefault((ip, mac, "arp"), {"ip": ip, "mac": mac, "source": "arp", "first_seen": ts, "last_seen": ts, "seen_count": 0})
        r["first_seen"], r["last_seen"], r["seen_count"] = min(r["first_seen"], ts), max(r["last_seen"], ts), r["seen_count"] + 1
    for mac, first, last, ip, hits in db.execute("SELECT mac, first_seen, last_seen, ip, hits FROM mac_memory WHERE ip IS NOT NULL"):
        mac = normalize_mac(mac)
        if mac:
            r = agg.setdefault((ip, mac, "arp"), {"ip": ip, "mac": mac, "source": "arp", "first_seen": first, "last_seen": last, "seen_count": 0})
            r["first_seen"], r["last_seen"], r["seen_count"] = min(r["first_seen"], first), max(r["last_seen"], last), r["seen_count"] + int(hits or 1)
    flips = defaultdict(list)                       # ip -> [(ts, old, new)]: every takeover is a change of the MAC that answers an address
    for ts, ip, old, new in db.execute("SELECT ts, ip, old_mac, new_mac FROM mac_takeover ORDER BY ts"):
        old, new = normalize_mac(old), normalize_mac(new)
        if old and new and ip:
            flips[ip].append((ts, old, new))
            for mac, when in ((old, ts - 1), (new, ts)):
                r = agg.setdefault((ip, mac, "arp"), {"ip": ip, "mac": mac, "source": "arp", "first_seen": when, "last_seen": when, "seen_count": 0})
                r["first_seen"], r["last_seen"], r["seen_count"] = min(r["first_seen"], when), max(r["last_seen"], when), r["seen_count"] + 1
    mdns = json.loads(zf.read("data/mdns_seen.json")) if "data/mdns_seen.json" in zf.namelist() else {}
    for raw, card in (mdns.get("by_mac") or {}).items():
        mac, ip = normalize_mac(raw), (card or {}).get("ip")
        if mac and ip:
            t = float(card.get("seen") or 0)
            agg[(ip, mac, "mdns")] = {"ip": ip, "mac": mac, "source": "mdns", "first_seen": t, "last_seen": t, "seen_count": 1}
    extra = {"events": db.execute("SELECT COUNT(*) FROM presence_events").fetchone()[0], "mac_memory": db.execute("SELECT COUNT(*) FROM mac_memory").fetchone()[0],
             "takeover": db.execute("SELECT COUNT(*) FROM mac_takeover").fetchone()[0]}
    extra["flips"] = flips
    return list(agg.values()), extra


def report(path):
    rows, extra = rows_from_zip(path)
    res = macclassify.classify(rows)
    kinds = Counter(v["kind"] for v in res["macs"].values())
    print(f"\n=== {Path(path).name}: {len(rows)} righe ip/mac, {len(res['macs'])} MAC, eventi di presenza {extra['events']}, mac_memory {extra['mac_memory']}, takeover {extra['takeover']}")
    print("   tipi:", dict(kinds))
    for mac, v in sorted(res["macs"].items(), key=lambda kv: -len(kv[1]["ips"])):
        if v["kind"] in ("lender", "multi_address") or len(v["ips"]) >= 3:
            print(f"   {v['kind']:13s} {short(mac)} su {len(v['ips'])} IP: {', '.join(i.rsplit('.', 1)[-1] for i in v['ips'][:12])}")
    for c in res["conflicts"]:
        print(f"   conflitto  .{c['ip'].rsplit('.', 1)[-1]}: {', '.join(short(m) for m in c['macs'])}")
    for ip, fl in sorted(extra["flips"].items(), key=lambda kv: -len(kv[1]))[:4]:
        gaps = sorted(b[0] - a[0] for a, b in zip(fl, fl[1:]))
        runs = 1 + sum(1 for g in gaps if g > 600)             # a pause of more than 10 minutes starts a new burst
        med = gaps[len(gaps) // 2] if gaps else 0
        print(f"   alternanze .{ip.rsplit('.', 1)[-1]}: {len(fl)} cambi, mediana tra due cambi {med:.0f} s, {runs} raffiche, {len({m for _, o, n in fl for m in (o, n)})} MAC")
    by_ip = defaultdict(set)
    for r in rows:
        if r["source"] == "arp":
            by_ip[r["ip"]].add(r["mac"])
    many = sorted(((len(m), ip) for ip, m in by_ip.items() if len(m) >= 2), reverse=True)[:8]
    print("   indirizzi con piu' MAC (osservati):", ", ".join(f".{ip.rsplit('.', 1)[-1]}x{n}" for n, ip in many) or "nessuno")


if __name__ == "__main__":
    files = sys.argv[1:] or sorted(str(p) for p in (Path.home() / ".vedetta" / "exports").glob("vedetta-analisi-*.zip"))
    for f in files:
        report(f)
