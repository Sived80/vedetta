"""The service types of the DNS-SD browsing (scan/mdns_browsing.py):
1) a type announced on the network is data from outside: a malformed one ("local.", ".", "x.local.") is left out instead of making zeroconf raise
   BadTypeInNameException in the event loop (seen on a real network);
2) the question for the service types is asked again later (zeroconf asks it only in its first ~14 s: a type that appears afterwards would never be
   browsed by the continuous listener): one multicast question, at intervals that double up to one hour (RFC 6762 section 5.2).
    python tests/check_mdns_types.py"""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.scan import mdns_browsing  # noqa: E402
from app.scan.mdns_browsing import Browsing, TypesQuestion  # noqa: E402

# 1) valid and malformed types
for good in ("_http._tcp.local.", "_hap._udp.local.", "_googlecast._tcp.local.", "_amzn-wplay._tcp.local."):
    assert mdns_browsing.valid_service_type(good), good
for bad in ("local.", ".", "", "x.local.", "_http._tcp.", "_http._sctp.local.", "_._tcp.local.", "_http._tcp.local", "a" * 300 + "._tcp.local.", None):
    assert not mdns_browsing.valid_service_type(bad), bad

made: list = []


class FakeBrowser:
    def __init__(self, zc, stype, handlers=None):
        made.append(stype)


zc = mdns_browsing._Zeroconf(azc=types.SimpleNamespace(zeroconf=object()), browser=FakeBrowser, info=None, v4=None, removed="removed")
b = Browsing(zc, lambda r: None, 3000, None)
for name in ("local.", ".", "_http._tcp.local.", "_http._tcp.local."):
    b.on_type(zeroconf=None, service_type="_services._dns-sd._udp.local.", name=name, state_change="added")
assert made == ["_http._tcp.local."], made
assert b.types == {"_http._tcp.local."}, b.types

# 2) the schedule of the question for the types: first after FIRST_S, then doubling, never more than MAX_S apart
q = TypesQuestion(now=0.0)
assert not q.due(TypesQuestion.FIRST_S - 1)
times = []
t = 0.0
while t < 6 * 3600:
    t += 30.0
    if q.due(t):
        times.append(t)
        q.asked(t)
gaps = [b - a for a, b in zip(times, times[1:])]
assert times[0] == TypesQuestion.FIRST_S, times[:3]
assert all(g2 >= g1 for g1, g2 in zip(gaps, gaps[1:])), gaps
assert max(gaps) <= TypesQuestion.MAX_S and gaps[-1] == TypesQuestion.MAX_S, gaps
assert len(times) < 20, "too many questions in six hours: %d" % len(times)

# 3) asking sends ONE question for the meta type, multicast, through the zeroconf already open (no new socket)
sent: list = []
zc2 = mdns_browsing._Zeroconf(azc=types.SimpleNamespace(zeroconf=types.SimpleNamespace(async_send=lambda out: sent.append(out))), browser=FakeBrowser, info=None, v4=None, removed="removed")
Browsing(zc2, lambda r: None, 3000, None).ask_types()
assert len(sent) == 1, sent
questions = sent[0].questions
assert [qq.name for qq in questions] == ["_services._dns-sd._udp.local."], questions
assert not questions[0].unicast, "the question must be multicast (QM): the answers reach every listener"
print("TUTTO OK")
