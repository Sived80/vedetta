"""Golden-master test of scan.flows.validate_flows / validate_profile (the real caller of validate_profile): 4000 generated settings - unknown or non-string profiles,
non-list ids, unknown / non-string / unhashable step ids, steps not applicable to the profile, missing mandatory steps, empty lists, duplicates, shuffled order, partial
dicts - must give exactly the result (or the FlowError key and params, first error wins) stored in tests/golden/validate_profile.json, written from the code as it was
before the function was split.
Regenerate only on purpose:  VALIDATEPROFILE_GOLDEN_UPDATE=1 python tests/check_validate_profile_golden.py"""
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import flows  # noqa: E402

GOLDEN = Path(__file__).parent / "golden" / "validate_profile.json"
N = 4000
rng = random.Random(97531)
PROFILES = list(flows.PROFILES) + ["bogus", "", None, 5, ("initial",), ["deep"]]
VALID = list(flows.STEP_IDS)
ODD = ["nope", "", None, 3, 1.5, ["arp"], {"a": 1}, ("arp",), True, "ARP", " arp"]


def pick(seq):
    return seq[rng.randrange(len(seq))]


def ids_for(profile):
    if rng.random() < 0.05:
        return pick([None, "arp", ("arp",), {"arp": 1}, 7, {"arp"}])
    applicable = [s.id for s in flows.STEPS if profile in s.flows] or VALID
    mode = rng.random()
    if mode < 0.35:        # mostly valid for the profile, random subset
        ids = [s for s in applicable if rng.random() < 0.6]
    elif mode < 0.55:      # the defaults, maybe with a step removed
        ids = list(flows.DEFAULT_FLOWS.get(profile, ())) if isinstance(profile, str) else []
        if ids and rng.random() < 0.5:
            ids.pop(rng.randrange(len(ids)))
    elif mode < 0.7:       # anything from the whole catalogue (some not applicable)
        ids = [s for s in VALID if rng.random() < 0.4]
    else:
        ids = [pick(VALID) for _ in range(rng.randrange(0, 5))]
    if rng.random() < 0.15:  # duplicates
        ids += ids[:2]
    if rng.random() < 0.15:  # one odd value somewhere
        ids.insert(rng.randrange(len(ids) + 1), pick(ODD))
    if rng.random() < 0.15:  # a second error behind the first
        ids.append(pick(VALID + ODD))
    if rng.random() < 0.5:
        rng.shuffle(ids)
    return ids


def run(fn):
    try:
        return {"ok": fn()}
    except flows.FlowError as exc:
        return {"err": exc.key, "params": exc.params}
    except Exception as exc:
        return {"exception": type(exc).__name__}


out = []
for _ in range(N):
    if rng.random() < 0.7:
        p = pick(PROFILES) if rng.random() < 0.25 else pick(list(flows.PROFILES))
        ids = ids_for(p)
        out.append({"profile": run(lambda: flows.validate_profile(p, ids))})
    else:
        if rng.random() < 0.08:
            data = pick([None, [], "initial", 3, [("initial", ["arp"])]])
        else:
            data = {}
            for _ in range(rng.randrange(0, 4)):
                p = pick(PROFILES) if rng.random() < 0.15 else pick(list(flows.PROFILES))
                if isinstance(p, (str, type(None), int, tuple)):
                    data[p] = ids_for(p)
        out.append({"flows": run(lambda: flows.validate_flows(data))})
out = json.loads(json.dumps(out))
if os.environ.get("VALIDATEPROFILE_GOLDEN_UPDATE") or not GOLDEN.exists():
    GOLDEN.write_text(json.dumps(out, indent=0), encoding="utf-8")
    print("golden written")
want = json.loads(GOLDEN.read_text(encoding="utf-8"))
assert len(want) == len(out) == N
for i, (x, y) in enumerate(zip(out, want)):
    assert json.dumps(x) == json.dumps(y), "case %d differs: %s" % (i, json.dumps([x, y])[:500])
res = [v for o in out for v in o.values()]
assert not any("exception" in v for v in res)
keys = {}
for v in res:
    k = v.get("err", "ok" if "ok" in v else "exc")
    keys[k] = keys.get(k, 0) + 1
for k in ("ok", "flow.error.unknown_profile", "flow.error.not_a_list", "flow.error.unknown_step", "flow.error.not_applicable", "flow.error.required",
          "flow.error.empty", "flow.error.invalid_body"):
    assert keys.get(k, 0) > 40, "scenarios too uniform: %s %s" % (k, keys)
assert any(isinstance(v.get("ok"), list) and len(v["ok"]) > 5 for v in res)
assert any(isinstance(v.get("ok"), dict) and len(v["ok"]) > 1 for v in res)
print("TUTTO OK")
