"""One judgement for "are these two MACs the same device?" (recognition/same_device.py). The notice of a second device behind a card (ha/identity_shift.py) and the name that a card keeps
(scan/probe_names.py) ask the very same question, so they use the very same function: the same vetoes, the same evidence that it is one device, the same families of evidence that it is two.
What differs is only how much evidence each consumer wants before it acts, and that is a named policy, not a second copy of the rules. The fingerprints below are made up."""
import os
import sys
import tempfile

os.environ.setdefault("VEDETTA_DATA_DIR", tempfile.mkdtemp())      # never the real folder of the developer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.recognition import same_device  # noqa: E402
from app.ha import identity_shift  # noqa: E402
from app.scan import dhcp, probe_names  # noqa: E402
from app.scan.probe_record import Facts  # noqa: E402

failed = []


def check(label, got, want):
    if got != want:
        failed.append("%s: got %r, expected %r" % (label, got, want))


FP_A = {"prl": "1,3,6,15,26", "vendor_class": "kind-a-1"}
FP_B = {"prl": "1,121,3,6,15", "vendor_class": ""}


def prof(mac, entry=None, **more):
    return same_device.profile(mac, fingerprint=same_device.fingerprint(entry), **more)


# --- 1. what a MAC says about the device itself (RFC 2132, options 55 and 60)
check("fingerprint: list and class", same_device.fingerprint(FP_A), ("1,3,6,15,26", "kind-a-1"))
check("fingerprint: only the list", same_device.fingerprint(FP_B), ("1,121,3,6,15", ""))
check("fingerprint: the class is read without case or spaces", same_device.fingerprint({"prl": "1,3", "vendor_class": "  Kind-A-1 "}), ("1,3", "kind-a-1"))
check("fingerprint: nothing sent", same_device.fingerprint({"hostname": "x"}), None)
check("fingerprint: no entry", same_device.fingerprint(None), None)

# --- 2. the policy of a name: one family of evidence is enough, a private MAC is not a reason to stay silent
NAME = same_device.NAME
a, b = prof("m1", FP_A), prof("m2", FP_B)
j = same_device.judge(a, b, set(), policy=NAME)
check("name: two fingerprints", (j["verdict"], j["reasons"], j["vetoes"]), ("different", ["dhcp_fingerprint"], []))
check("name: the order of the list counts", same_device.judge(prof("m1", {"prl": "1,3,6"}), prof("m2", {"prl": "3,1,6"}), set(), policy=NAME)["verdict"], "different")
check("name: the same fingerprint", same_device.judge(a, prof("m2", dict(FP_A, hostname="other")), set(), policy=NAME)["verdict"], "unknown")
check("name: the same class in another case", same_device.judge(prof("m1", {"prl": "1", "vendor_class": "A B"}), prof("m2", {"prl": "1", "vendor_class": "a b"}), set(), policy=NAME)["verdict"], "unknown")
check("name: one fingerprint is not known", same_device.judge(a, prof("m2", None), set(), policy=NAME)["verdict"], "unknown")
check("name: a private MAC does not silence it (a fingerprint survives the rotation of the MAC)",
      same_device.judge(dict(a, private=True), dict(b, private=True), set(), policy=NAME)["verdict"], "different")

# --- 3. the vetoes and the evidence of "same" are the same for both policies
for policy in (same_device.NOTIFY, NAME):
    tag = policy.name
    check(tag + ": a shared MAC (a repeater lending its own) identifies nobody", same_device.judge(a, b, {"m2"}, policy=policy)["vetoes"], ["shared"])
    check(tag + ": the shared MAC may be either side", same_device.judge(a, b, {"m1"}, policy=policy)["verdict"], "unknown")
    check(tag + ": a network role on either side", same_device.judge(a, b, set(), role_b=True, policy=policy)["vetoes"], ["role"])
    check(tag + ": the same DHCP name wins over any difference", same_device.judge(dict(a, dhcp_name="pc-1"), dict(b, dhcp_name="pc-1"), set(), policy=policy)["verdict"], "same")
    check(tag + ": the same Bonjour name wins over any difference", same_device.judge(dict(a, mdns_name="x"), dict(b, mdns_name="x"), set(), policy=policy)["verdict"], "same")
check("notify: a private MAC is a veto", same_device.judge(dict(a, private=True), b, set())["vetoes"], ["private"])
check("the network roles are the same list", same_device.is_network(["dhcp"]), True)
check("a client has no network role", same_device.is_network(["client"]), False)

# --- 4. the notice does not change: the fingerprint is not one of its families (the same DHCP request is already counted once, as the DHCP family)
rich = dict(a, family="android", grp="phone")
other = dict(b, family="windows", grp="pc")
check("notify: the families are the five that it always had", same_device.judge(rich, other, set())["reasons"], ["dhcp_family", "group"])
check("notify: a fingerprint alone says nothing", same_device.judge(a, b, set())["verdict"], "unknown")
check("name: the other families do not make it act", same_device.judge(dict(rich, fingerprint=None), dict(other, fingerprint=None), set(), policy=NAME)["verdict"], "unknown")

# --- 5. one judge: both consumers call the same function (a spy sees both)
calls = []
real = same_device.judge


def spy(*args, **kwargs):
    calls.append(kwargs.get("policy"))
    return real(*args, **kwargs)


same_device.judge = spy
try:
    MAC_OLD, MAC_NOW = "c6:00:00:00:00:21", "5a:00:00:00:00:22"
    dhcp.seen[MAC_OLD], dhcp.seen[MAC_NOW] = dict(FP_A), dict(FP_B)
    f = Facts.__new__(Facts)
    f.device, f.ip, f.dhcp_name, f.scan_info, f.identity_mac = {"name": "name-a", "name_source": "dhcp", "name_mac": MAC_OLD}, "10.0.0.8", None, {}, MAC_NOW
    n = probe_names.NameState(base_name="name-a", placeholder=False, ha_stale=False)
    probe_names.choose_automatic_name(f, n)
    check("the name of a card asks the shared judge", calls[-1:], [NAME])
    del calls[:]

    class Memory:
        def mac_memory_for(self, device_id):
            return [{"mac": MAC_OLD, "ip": None, "first_seen": 1}, {"mac": MAC_NOW, "ip": None, "first_seen": 2}]

    identity_shift.history = Memory()
    identity_shift.evaluate("card-1", MAC_NOW, {}, 1000.0)
    check("the notice of a second device asks the same function, with its own policy", calls, [same_device.NOTIFY])
finally:
    same_device.judge = real
check("identity_shift.judge is the shared one", identity_shift.judge is same_device.judge, True)
check("identity_shift._different_reasons is the shared one", identity_shift._different_reasons is same_device.different_reasons, True)

if failed:
    print("FAILED:\n  " + "\n  ".join(failed))
    sys.exit(1)
print("OK")
