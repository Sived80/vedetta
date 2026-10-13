"""Identifiability matrix of the MAC layer, generated (not hand-listed) and brute-forced.

Situations are not listed by hand: a device is described by orthogonal DIMENSIONS (kind of MAC, path to the LAN, addressing, number of cards, IP
aliases, sharing of the address, visibility, DHCP client id) and every combination is simulated (full factorial design, several noise levels and
event times). The named cases (repeater lending its MAC, real conflict, rotating private MAC, mesh roaming, VRRP, PC with two cards...) are just regions
of that space, and a case nobody thought of is still there as a combination. To add a situation: add a value to DIMS and handle it in build().

For every simulated network the script extracts binary SIGNALS (what a device can tell us, from which source, with what rhythm), and then:
  1. the matrix P(signal | situation);
  2. the ambiguous classes: situations with different truth that give the SAME signals (unidentifiable with what we record today);
  3. the minimal set of signals that separates all the truths that can be separated at all (exact search over all subsets);
  4. a brute-force run of the real classifier (app/macclassify.py) over every simulation, against the known truth.
Usage: python tools/mac_matrix.py [--quick] [--out FOLDER]   (no network, no database, stdlib only)."""
import itertools
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vedetta"))
from app import macclassify  # noqa: E402

T = 180                      # cycles per simulation (one ARP view per cycle, 60 s each)
CYCLE_S = 60.0
RENEW = 40                   # DHCP renewal every RENEW cycles
DIMS = {
    "mac": ["factory", "private_fixed", "private_rotating", "user_toggle", "virtual"],   # user_toggle: factory -> private -> factory (settings switch)
    "path": ["direct", "proxy", "roaming"],          # WDS keeps the real MAC: identical to "direct" by construction
    "addressing": ["static", "dhcp", "sequential"],
    "nics": [1, 2],
    "aliases": [1, 3],
    "sharing": ["alone", "replaced", "replaced_back", "conflict"],
    "visible": ["arp", "dhcp_only"],
    "cid": [0, 1],
    "hostname": [0, 1, 2],                           # DHCP name (opt 12): none, unique to the device, or a generic one shared by many devices
}
GRID_FULL = [(p, tf, s) for p in (0.95, 0.7) for tf in (0.3, 0.6) for s in (1,)]
GRID_QUICK = [(0.95, 0.5, 1)]
RANK = {"conflict": 5, "lender": 4, "virtual": 3, "multi_address": 2, "private": 1, "normal": 0}


FAMILIES = [("android-dhcp-14", "1,3,6,15,26,28,51,58,59,43"), ("", "1,121,3,6,15,119,252"), ("MSFT 5.0", "1,15,3,6,44,46,47,31,33,121,249,252")]


class Net:
    def __init__(self, seed, p_arp, base=0):
        self.base, self.fam = base, seed % len(FAMILIES)
        self.rng, self.p_arp = random.Random(seed), p_arp
        self.answers = defaultdict(list)       # ip -> [(mac, lo, hi, host)]
        self.events = []                       # (t, source, ip, mac, host, cid)
        self.truth = {}
        self.host_of, self.lenders, self.conflict = {}, set(), False       # identity truth: which MAC belongs to which physical host
        self._ip, self._mac, self._host = 9, 0, 0

    def ip(self):
        self._ip += 1
        return f"10.0.{self.base}.{self._ip}"

    def mac(self, laa=False):
        self._mac += 1
        return f"{'DA' if laa else '00'}:11:{self.base:02X}:00:{self._mac // 256:02X}:{self._mac % 256:02X}"

    def new_host(self):
        self._host += 1
        return self._host

    def own(self, mac, host_id):
        self.host_of[mac] = host_id

    def tag(self, mac, kind):
        if RANK[kind] >= RANK.get(self.truth.get(mac, "normal"), 0):
            self.truth[mac] = kind

    def answer(self, ip, mac, lo, hi, host=None):
        self.answers[ip].append((mac, lo, hi, host))

    def dhcp(self, ip, mac, host, cid, lo, hi, fam=None):
        vc, prl = FAMILIES[self.fam if fam is None else fam]
        for t in range(lo, hi, RENEW):
            self.events.append((t, "dhcp", ip, mac, host, cid, vc, prl))

    def run_arp(self):
        for t in range(T):
            for ip, answerers in self.answers.items():
                active = [a for a in answerers if a[1] <= t < a[2]]
                if not active or self.rng.random() > self.p_arp:
                    continue
                mac, _, _, host = active[self.rng.randrange(len(active))]       # first reply wins
                self.events.append((t, "arp", ip, mac, None, None, None, None))
                if host and t % 30 == 0 and self.rng.random() < 0.5:
                    self.events.append((t, "mdns", ip, mac, host, None, None, None))


def is_laa(mac):
    return bool(int(mac[:2], 16) & 2) and not mac.startswith("00:00:5E")


def build(spec, p_arp, tf, seed, base=0):
    n = Net(seed, p_arp, base)
    t0, t1, t2 = int(T * tf), int(T * 0.35), int(T * 0.65)
    me = n.new_host()
    host = None if not spec["hostname"] else (f"host{seed}" if spec["hostname"] == 1 else "iPhone")
    cid = f"cid-{seed}" if spec["cid"] else None
    pol = spec["mac"]
    if pol == "private_rotating":
        macs = [(n.mac(True), 0, t0), (n.mac(True), t0, T)]
    elif pol == "user_toggle":                                   # factory MAC -> private MAC -> back to the factory MAC (settings switch)
        f, pm = n.mac(), n.mac(True)
        macs = [(f, 0, t1), (pm, t1, t2), (f, t2, T)]
    elif pol == "virtual":
        macs = [(f"00:00:5E:00:01:{n.base % 256:02X}", 0, T)]          # a virtual MAC per network: the shared constant made two groups look like one device
        for _ in range(2):                                        # the two real routers behind the virtual MAC
            r, rip, rh = n.mac(), n.ip(), n.new_host()
            n.answer(rip, r, 0, T, None)
            n.tag(r, "normal")
            n.own(r, rh)
    elif pol == "private_fixed":
        macs = [(n.mac(True), 0, T)]
    else:
        macs = [(n.mac(), 0, T)]
    for m, _, _ in macs:
        n.own(m, me)
    ips = [(n.ip(), 0, T)] if spec["addressing"] != "sequential" else [(n.ip(), 0, T // 3), (n.ip(), T // 3, 2 * T // 3), (n.ip(), 2 * T // 3, T)]
    windows = {"alone": [(0, T)], "conflict": [(0, T)], "replaced": [(0, t1)], "replaced_back": [(0, t1), (t2, T)]}[spec["sharing"]]
    if spec["addressing"] == "sequential":
        windows = [(0, T)]                                        # sharing applies only to a single-address device (see valid())
    carriers = [(None, 0, T)]
    if spec["path"] == "proxy":
        r = n.mac()
        n.lenders.add(r)
        n.own(r, n.new_host())
        n.answer(n.ip(), r, 0, T, None)
        carriers = [(r, 0, T)]
    elif spec["path"] == "roaming":                               # two proxy nodes: the client moves from one to the other
        a, b = n.mac(), n.mac()
        for x in (a, b):
            n.lenders.add(x)
            n.own(x, n.new_host())
            n.answer(n.ip(), x, 0, T, None)
        carriers = [(a, 0, t0), (b, t0, T)]
    if spec["visible"] == "arp":
        extra = [n.ip(), n.ip()] if spec["aliases"] == 3 else []
        for i, (ip, ilo, ihi) in enumerate(ips):
            for wlo, whi in (windows if i == 0 else [(ilo, ihi)]):
                lo, hi = max(wlo, ilo), min(whi, ihi)
                if lo >= hi:
                    continue
                for m, mlo, mhi in (macs if spec["path"] == "direct" else carriers):
                    if max(lo, mlo) < min(hi, mhi):
                        n.answer(ip, m, max(lo, mlo), min(hi, mhi), host)
        for ip in extra:
            for m, mlo, mhi in (macs if spec["path"] == "direct" else carriers):
                n.answer(ip, m, mlo, mhi)
    if spec["addressing"] != "static":                            # DHCP of the primary device: its own MAC (chaddr) at every lease
        for ip, ilo, ihi in ips:
            for wlo, whi in (windows if ip == ips[0][0] else [(ilo, ihi)]):
                for m, mlo, mhi in macs:
                    lo, hi = max(wlo, ilo, mlo), min(whi, ihi, mhi)
                    if lo < hi:
                        n.dhcp(ip, m, host, cid, lo, hi)
    if spec["sharing"] != "alone":                                # the other device on the same address
        y, yhost, yid = n.mac(), (None if not spec["hostname"] else (f"other{seed}" if spec["hostname"] == 1 else "iPhone")), n.new_host()
        n.own(y, yid)
        spans = {"replaced": [(t1, T)], "replaced_back": [(t1, t2)], "conflict": [(0, T)]}[spec["sharing"]]
        for lo, hi in spans:
            n.answer(ips[0][0], y, lo, hi, yhost if spec["addressing"] != "static" else None)
            if spec["addressing"] != "static":
                n.dhcp(ips[0][0], y, yhost, None, lo, hi, fam=(n.fam + 1) % len(FAMILIES))
        n.tag(y, "conflict" if spec["sharing"] == "conflict" else "normal")
        n.conflict = spec["sharing"] == "conflict" and spec["visible"] == "arp"
    if spec["nics"] == 2:                                         # second card of the same host
        m2, ip2 = n.mac(), n.ip()
        n.own(m2, me)
        n.answer(ip2, m2, 0, T, host)
        if spec["addressing"] != "static":
            n.dhcp(ip2, m2, host, cid, 0, T)
        n.tag(m2, "normal")
    for m, _, _ in macs:                                          # kinds, for the brute force of the classifier
        if pol == "virtual":
            kind = "virtual"
        elif spec["sharing"] == "conflict" and spec["path"] == "direct" and spec["visible"] == "arp":
            kind = "conflict"
        elif is_laa(m):
            kind = "private"
        elif spec["aliases"] == 3 and spec["path"] == "direct" and spec["visible"] == "arp":
            kind = "multi_address"
        else:
            kind = "normal"
        n.tag(m, kind)
    n.run_arp()
    return n


def valid(spec):
    if spec["addressing"] == "sequential" and (spec["sharing"] != "alone" or spec["aliases"] == 3):
        return False
    if spec["mac"] == "virtual" and (spec["path"] != "direct" or spec["addressing"] == "sequential" or spec["visible"] != "arp"):
        return False
    if spec["visible"] == "dhcp_only" and (spec["addressing"] == "static" or spec["sharing"] != "alone" or spec["aliases"] == 3):
        return False                                              # nothing observable, or an address nobody answers
    if spec["addressing"] == "static" and (spec["cid"] or spec["hostname"]):
        return False
    return True


def specs():
    keys = list(DIMS)
    for combo in itertools.product(*(DIMS[k] for k in keys)):
        s = dict(zip(keys, combo))
        if valid(s):
            yield s


# ---------------------------------------------------------------------------------------------- signals (what a device can tell us)
SIGNALS = [  # name, source, rhythm: how it is observed
    ("mac_on_2_ips", "arp", "window"), ("mac_on_3_ips", "arp", "window"), ("ip_flips_1", "arp", "history"), ("ip_flips_4", "arp", "history"),
    ("ip_alternates", "arp", "rhythm"), ("dhcp_arp_mismatch", "arp+dhcp", "per lease"), ("laa_mac", "arp", "static"), ("virtual_mac", "arp", "static"),
    ("hostname_on_2_macs", "dhcp", "per lease"), ("hostname_handoff", "dhcp", "history"), ("dhcp_ip_never_in_arp", "arp+dhcp", "history"),
    ("mac_many_ips_never_together", "arp", "history"), ("clientid_on_2_macs", "dhcp", "per lease"), ("ip_two_macs_overlap", "arp", "history"),
    ("mac_returns", "arp", "history"), ("hostname_laa_pair", "dhcp", "per lease"),
]


def signals(net):
    arp = defaultdict(list)
    dh = []
    for t, src, ip, mac, host, cid, *_ in net.events:
        if src == "arp":
            arp[ip].append((t, mac))
        elif src == "dhcp":
            dh.append((t, ip, mac, host, cid))
    f = dict.fromkeys((s[0] for s in SIGNALS), False)
    by_mac = defaultdict(list)
    for ip, obs in arp.items():
        for t, m in obs:
            by_mac[m].append((t, ip))
    maxsim = 0
    for m, obs in by_mac.items():
        for i, (t, _) in enumerate(obs):
            maxsim = max(maxsim, len({ip for tt, ip in obs[i:] if tt < t + 10}))
        if len({ip for _, ip in obs}) >= 3 and all(len({ip for tt, ip in obs if t <= tt < t + 10}) <= 1 for t, _ in obs):
            f["mac_many_ips_never_together"] = True
        f["laa_mac"] |= bool(int(m[:2], 16) & 2) and not m.startswith("00:00:5E")
        f["virtual_mac"] |= m.startswith("00:00:5E:00:01")
    f["mac_on_2_ips"], f["mac_on_3_ips"] = maxsim >= 2, maxsim >= 3
    for ip, obs in arp.items():
        seq = [m for _, m in sorted(obs)]
        flips = sum(1 for a, b in zip(seq, seq[1:]) if a != b)
        f["ip_flips_1"] |= flips >= 1
        f["ip_flips_4"] |= flips >= 4
        f["ip_alternates"] |= flips >= 4 and flips / max(1, len(seq)) >= 0.25
        runs = [m for i, m in enumerate(seq) if i == 0 or m != seq[i - 1]]
        f["mac_returns"] |= len(runs) > len(set(runs))
        spans = defaultdict(lambda: [10 ** 9, -1, 0])
        for t, m in obs:
            s = spans[m]
            s[0], s[1], s[2] = min(s[0], t), max(s[1], t), s[2] + 1
        for (_, a), (_, b) in itertools.combinations(spans.items(), 2):
            if min(a[2], b[2]) >= 3 and (min(a[1], b[1]) - max(a[0], b[0])) * CYCLE_S >= 60:
                f["ip_two_macs_overlap"] = True
    host_macs, cid_macs, host_span = defaultdict(set), defaultdict(set), defaultdict(dict)
    for t, ip, m, h, c in dh:
        if h:
            host_macs[h].add(m)
            s = host_span[h].setdefault(m, [t, t])
            s[0], s[1] = min(s[0], t), max(s[1], t)
        if c:
            cid_macs[c].add(m)
        f["dhcp_ip_never_in_arp"] |= ip not in arp
        near = [mm for tt, mm in arp.get(ip, []) if abs(tt - t) <= 5]
        f["dhcp_arp_mismatch"] |= bool(near) and m not in near
    f["hostname_on_2_macs"] = any(len(v) >= 2 for v in host_macs.values())
    f["hostname_laa_pair"] = any(len({bool(int(m[:2], 16) & 2) for m in v}) == 2 for v in host_macs.values())
    f["clientid_on_2_macs"] = any(len(v) >= 2 for v in cid_macs.values())
    for h, spans in host_span.items():
        for (_, a), (_, b) in itertools.combinations(spans.items(), 2):
            f["hostname_handoff"] |= a[1] < b[0] or b[1] < a[0]
    return f


def rows_of(net):
    agg = {}
    for t, src, ip, mac, host, cid, *_ in net.events:
        r = agg.setdefault((ip, mac, src), {"ip": ip, "mac": mac, "source": src, "first_seen": t * CYCLE_S, "last_seen": t * CYCLE_S, "seen_count": 0})
        r["first_seen"], r["last_seen"], r["seen_count"] = min(r["first_seen"], t * CYCLE_S), max(r["last_seen"], t * CYCLE_S), r["seen_count"] + 1
    return list(agg.values())


def truth_sig(net, rows):
    """What a decision needs to know, as booleans (how MANY devices stand behind a bridge does not change any decision): does one device show
    up with several MACs (to merge), does a MAC stand for other devices (lender), is an address contested by two devices at once (conflict)."""
    seen = {r["mac"] for r in rows}
    counts = Counter(net.host_of.get(m, m) for m in seen)
    return (any(c >= 2 for c in counts.values()), any(m in net.lenders for m in seen), bool(net.conflict))


def link_features(events):
    """Features of every MAC as the layer would hold them: DHCP fields, client id, activity sessions (a gap of more than 10 cycles splits one)."""
    sys.path.insert(0, str(ROOT / "vedetta"))
    feats, ts_by = {}, defaultdict(list)
    for t, src, ip, mac, host, cid, vc, prl in events:
        if src == "mdns":
            continue
        f = feats.setdefault(mac, {"first": 1e18, "last": 0.0, "ips": set()})
        f["first"], f["last"] = min(f["first"], t * CYCLE_S), max(f["last"], t * CYCLE_S)
        f["ips"].add(ip)
        ts_by[(mac, ip, src)].append(t)
        if src == "dhcp":
            if host:
                f["hostname"] = host
            if cid:
                f["client_id"] = cid
            if vc or prl:
                f["fingerprint"] = f"{vc or ''}|{prl or ''}"
    for (mac, ip, src), ts in ts_by.items():
        ts.sort()
        start = prev = ts[0]
        for x in ts[1:] + [None]:
            if x is None or x - prev > 10:
                feats[mac].setdefault("sessions", []).append((start * CYCLE_S, prev * CYCLE_S, (ip,)))
                start = x
            prev = x if x is not None else prev
    return feats


def evaluate_linker(n_networks, size, rng_seed=7):
    from app import macidentity
    rng = random.Random(rng_seed)
    pool = list(specs())
    zones = {"same": Counter(), "diff": Counter()}
    false_merges, missed = [], Counter()
    for k in range(n_networks):
        events, host_of, spec_of = [], {}, {}
        for i in range(size):
            spec = pool[rng.randrange(len(pool))]
            net = build(spec, rng.choice((0.95, 0.7)), rng.choice((0.3, 0.6)), rng.randrange(10 ** 6), base=i)
            events += net.events
            for m, h in net.host_of.items():
                host_of[m] = (i, h)
                spec_of[m] = spec
        feats = link_features(events)
        for p in macidentity.link(feats):
            a, b = p["a"], p["b"]
            if a not in host_of or b not in host_of:
                continue
            same = host_of[a] == host_of[b]
            zones["same" if same else "diff"][p["zone"]] += 1
            if same and p["zone"] == "unrelated":
                missed[("no evidence at all", spec_of[a]["mac"], spec_of[a]["hostname"], spec_of[a]["cid"])] += 1
            if not same and p["zone"] == "same":
                false_merges.append((spec_of[a], spec_of[b], p["why"]))
            if same and p["zone"] != "same":
                missed[(spec_of[a]["mac"], spec_of[a]["hostname"], spec_of[a]["cid"], p["zone"])] += 1
    return zones, false_merges, missed


def main():
    quick = "--quick" in sys.argv
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else None
    grid = GRID_QUICK if quick else GRID_FULL
    spec_list = list(specs())
    per_spec, confusion, by_dim_err = {}, Counter(), defaultdict(lambda: [0, 0])
    worst = []
    for idx, spec in enumerate(spec_list):
        vecs, sigs, errs, runs = [], set(), 0, 0
        for p, tf, seed in grid:
            net = build(spec, p, tf, seed * 1000 + idx)
            rows = rows_of(net)
            sig = signals(net)
            vecs.append([sig[s[0]] for s in SIGNALS])
            sigs.add(truth_sig(net, rows))
            got = {m: v["kind"] for m, v in macclassify.classify(rows)["macs"].items()}
            for m, want in net.truth.items():
                if m in got:
                    confusion[(want, got[m])] += 1
                    runs += 1
                    errs += got[m] != want
        per_spec[idx] = {"p": [sum(c) / len(c) for c in zip(*vecs)], "sigs": sigs}
        for d, v in spec.items():
            by_dim_err[(d, v)][0] += errs
            by_dim_err[(d, v)][1] += runs
        worst.append((errs / max(1, runs), idx))
    # --- matrix by truth outcome
    outcome = defaultdict(list)
    for idx, s in per_spec.items():
        for sg in s["sigs"]:
            outcome[sg].append(idx)
    cols = [s[0] for s in SIGNALS]
    mat = {sg: [sum(per_spec[i]["p"][j] for i in ids) / len(ids) for j in range(len(cols))] for sg, ids in outcome.items()}
    # --- ambiguous classes: same signal vector (rounded), different truth
    classes = defaultdict(list)
    for idx, s in per_spec.items():
        classes[tuple(round(x) for x in s["p"])].append(idx)
    ambiguous = [(k, ids) for k, ids in classes.items() if len({sg for i in ids for sg in per_spec[i]["sigs"]}) > 1]
    # --- minimal signal set separating every pair of truths that any signal can separate (exact)
    outs = list(mat)
    pairs = [(a, b) for a, b in itertools.combinations(outs, 2)]
    disc = {pr: {j for j in range(len(cols)) if abs(mat[pr[0]][j] - mat[pr[1]][j]) >= 0.5} for pr in pairs}
    separable = [pr for pr in pairs if disc[pr]]
    best = None
    for size in range(1, len(cols) + 1):
        for sub in itertools.combinations(range(len(cols)), size):
            if all(disc[pr] & set(sub) for pr in separable):
                best = sub
                break
        if best:
            break
    lines = [f"# Matrice di identificabilita' del livello MAC ({'rapida' if quick else 'completa'})", "",
             f"Specifiche simulate: {len(spec_list)} combinazioni di dimensioni x {len(grid)} parametri di rumore/tempo. Esiti (verita') distinti: {len(outs)}.", "",
             "## Dimensioni (le situazioni sono combinazioni di queste)", ""]
    lines += [f"- **{k}**: {', '.join(map(str, v))}" for k, v in DIMS.items()]
    lines += ["", "## Segnali (cosa puo' dirci un dispositivo)", "", "| segnale | fonte | come arriva |", "|---|---|---|"]
    lines += [f"| {n} | {s} | {r} |" for n, s, r in SIGNALS]
    lines += ["", "## Insieme minimo di segnali che separa tutto cio' che si puo' separare", "",
              ", ".join(cols[j] for j in best) if best else "(nessuno)",
              f"\nCoppie di esiti separabili: {len(separable)} su {len(pairs)}; non separabili da nessun segnale: {len(pairs) - len(separable)}.", ""]
    lines += ["## Classi ambigue (stessi segnali, verita' diversa): il sistema oggi NON puo' decidere", "",
              f"{len(ambiguous)} classi su {len(classes)}. Le piu' grandi:", ""]
    for key, ids in sorted(ambiguous, key=lambda kv: -len(kv[1]))[:12]:
        truths = Counter(sg for i in ids for sg in per_spec[i]["sigs"])
        varying = {d: sorted({str(spec_list[i][d]) for i in ids}) for d in DIMS if len({spec_list[i][d] for i in ids}) > 1}
        on = [cols[j] for j, b in enumerate(key) if b]
        lines.append(f"- {len(ids)} situazioni, segnali accesi: {', '.join(on) or 'nessuno'}")
        lines.append(f"  - verita' diverse: {'; '.join(f'{sg} (x{c})' for sg, c in truths.most_common(4))}")
        lines.append(f"  - dimensioni che variano: {varying}")
    lines += ["", "## Ambiguita' per decisione (quanta parte delle situazioni NON si decide con i segnali attuali)", ""]
    for name, fn in (("uno stesso apparecchio compare con piu' MAC (da unire)", lambda s: s[0]), ("un MAC che fa da ponte per altri apparecchi", lambda s: s[1]),
                     ("un indirizzo contestato da due apparecchi", lambda s: s[2])):
        bad = sum(len(ids) for ids in classes.values() if len({fn(sg) for i in ids for sg in per_spec[i]["sigs"]}) > 1)
        lines.append(f"- {name}: {bad}/{len(spec_list)} situazioni ({100 * bad / len(spec_list):.0f}%)")
    quick_n = 3 if quick else 40
    zones, false_merges, missed = evaluate_linker(quick_n, 20)
    ns, nd = sum(zones["same"].values()), sum(zones["diff"].values())
    lines += ["", f"## Collegamento dei MAC (macidentity) su {quick_n} reti da 20 apparecchi: verita' nota", "",
              f"- coppie dello STESSO apparecchio: {ns}: unite {zones['same']['same']} ({100 * zones['same']['same'] / max(1, ns):.0f}%), "
              f"'possibile' {zones['same']['possible']} ({100 * zones['same']['possible'] / max(1, ns):.0f}%), 'nessun legame' (nessuna prova) {zones['same']['unrelated']} "
              f"({100 * zones['same']['unrelated'] / max(1, ns):.0f}%), separate per errore {zones['same']['different']}",
              f"- coppie di apparecchi DIVERSI: {nd}: **unite per errore {zones['diff']['same']}** ({100 * zones['diff']['same'] / max(1, nd):.3f}%), "
              f"'possibile' {zones['diff']['possible']}, separate {zones['diff']['different']}", ""]
    for sa, sb, why in false_merges[:4]:
        lines.append(f"- unione sbagliata: {sa['mac']}/{sa['hostname']} con {sb['mac']}/{sb['hostname']}: {'; '.join(why)}")
    lines += ["- stessi apparecchi non uniti, per (politica MAC, nome, client id, esito): " + ", ".join(f"{k}x{c}" for k, c in missed.most_common(6)), ""]
    lines += ["", "## Forza bruta sul classificatore reale (macclassify): verita' -> risposta", "", "| verita' | risposta | casi |", "|---|---|---|"]
    lines += [f"| {w} | {g} | {c} |" for (w, g), c in sorted(confusion.items(), key=lambda kv: (kv[0][0] == kv[0][1], -kv[1]))][:30]
    tot = sum(confusion.values())
    ok = sum(c for (w, g), c in confusion.items() if w == g)
    lines += ["", f"Esattezza complessiva: {ok}/{tot} = {100 * ok / max(1, tot):.1f}%.", "", "## Errori per valore di dimensione (tasso di errore)", ""]
    lines += [f"- {d}={v}: {100 * e / max(1, r):.0f}% ({e}/{r})" for (d, v), (e, r) in sorted(by_dim_err.items(), key=lambda kv: -kv[1][0] / max(1, kv[1][1]))[:14]]
    lines += ["", "## Le 10 specifiche con piu' errori", ""]
    for rate, idx in sorted(worst, reverse=True)[:10]:
        lines.append(f"- {100 * rate:.0f}% errori: {spec_list[idx]}")
    report = "\n".join(lines) + "\n"
    print(report)
    if out:
        out.mkdir(parents=True, exist_ok=True)
        (out / ("matrice_rapida.md" if quick else "matrice.md")).write_text(report, encoding="utf-8")
        (out / "matrice.json").write_text(json.dumps({"signals": cols, "outcomes": {json.dumps(k): v for k, v in mat.items()},
                                                      "minimal": [cols[j] for j in best or []]}, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
