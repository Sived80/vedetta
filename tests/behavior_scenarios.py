"""Executable scenarios of the behaviour matrix (tests/data/behavior_matrix.json): each is a small function that raises AssertionError when the app
does the wrong thing. A matrix entry names a scenario in its "check"; to cover a new case write a function here and register it in SCENARIOS."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app.ha import identity_shift  # noqa: E402
from app.recognition.identity import mobile_assess  # noqa: E402
from app.scan import mdns_listener  # noqa: E402
from app.storage.history_presence import PresenceMixin  # noqa: E402

PRIVATE, GLOBAL, LENT = "42:4b:cd:00:00:01", "3c:a6:2f:11:22:33", "3c:a6:2f:44:55:66"


def _assess(**kw) -> dict:
    return mobile_assess(**{"mac": GLOBAL, "name_is_mobile": False, "has_ports": None, **kw})


def lent_mac_mdns() -> None:
    """A MAC at several addresses: what is announced at one address is not filed on the card of another."""
    mdns_listener.STORE_PATH = Path(tempfile.mkdtemp()) / "mdns_seen.json"
    mdns_listener.by_mac.clear()
    mdns_listener.by_ip.clear()
    arp = {"10.9.0.5": LENT, "10.9.0.8": LENT}
    mdns_listener._mac_for_ip = arp.get
    mdns_listener._is_lent_mac = lambda mac: list(arp.values()).count(mac) > 1
    mdns_listener.record("10.9.0.8", "_nearbypresence._tcp", "nearby-phone", '""')
    assert LENT not in mdns_listener.by_mac
    assert mdns_listener.lookup(LENT, "10.9.0.5") is None
    mdns_listener.by_mac[LENT] = {"name": "old", "services": ["_nearbypresence._tcp"], "ip": "10.9.0.8", "seen": 1.0, "score": 1}   # kept by an older version
    assert mdns_listener.lookup(LENT, "10.9.0.5") is None


def phone_on_lent_mac() -> None:
    """A phone with a known name and model keeps its class when only the MAC changes (own private MAC -> MAC lent by a repeater)."""
    phone = dict(name_is_mobile=True, has_ports=False, model_class="mobile", churn=300, mac_changes=1)
    assert mobile_assess(mac=PRIVATE, **phone)["mobile"] and mobile_assess(mac=LENT, **phone)["mobile"]


def repeater_private_mac_stays_router() -> None:
    """A repeater has a locally administered MAC (private) and a few presence flaps: with listening ports it stays below the threshold, with room to spare."""
    result = _assess(mac="4e:3a:fd:00:00:01", has_ports=True, churn=3)
    assert not result["mobile"] and result["score"] <= 2, result


def private_mac_alone_not_phone() -> None:
    assert not _assess(mac=PRIVATE, has_ports=False)["mobile"]


def no_ports_alone_not_phone() -> None:
    assert not _assess(has_ports=False)["mobile"]


def rotation_adds_mobile() -> None:
    assert _assess(mac=PRIVATE, mac_changes=2)["mobile"]


def media_receiver_not_phone() -> None:
    assert not _assess(mac=PRIVATE, has_ports=False, churn=300, media_receiver=True)["mobile"]


def nightly_pc_not_phone() -> None:
    assert not _assess(churn=300)["mobile"]


def _private_mac_counts(events: list[tuple]) -> dict:
    """PresenceMixin.private_mac_counts over (device, mac, online, ts) events, without a database."""
    rows = [{"device_id": d, "mac": m, "online": o, "ts": ts} for d, m, o, ts in events]

    class Fake:
        _lock = type("L", (), {"__enter__": lambda s: s, "__exit__": lambda s, *a: False})()
        _db = type("D", (), {"execute": lambda s, *a: type("R", (), {"fetchall": lambda s: rows})()})()
    return PresenceMixin.private_mac_counts(Fake(), 0, now=100 * 3600.0)


def global_mac_not_rotation() -> None:
    """The history counts only private MACs: a new global MAC (replaced card) is not a rotation."""
    assert _private_mac_counts([("a", GLOBAL, True, 3600.0), ("a", None, False, 7200.0), ("a", "3c:a6:2f:99:99:99", True, 10800.0)]) == {}


def lent_mac_ignored_in_history() -> None:
    """A private MAC that three cards used together for hours (a repeater) counts for none of them."""
    assert _private_mac_counts([(c, PRIVATE, True, 3600.0 * i) for i, c in enumerate("abc", 1)]) == {}


def phone_two_cards_one_mac() -> None:
    """One phone on two cards one after the other (an address change): the private MAC still counts for each card, it was never shared."""
    events = [("old", PRIVATE, True, 3600.0), ("old", None, False, 36000.0), ("new", PRIVATE, True, 36000.0 - 300)]
    assert _private_mac_counts(events) == {"old": 1, "new": 1}


def _profile(mac: str, **kw) -> dict:
    """What identity_shift remembers about a MAC (see identity_shift.profile), with nothing known unless given."""
    base = {"mac": mac, "ip": "10.9.0.20", "private": False, "dhcp_class": None, "family": None, "dhcp_name": None, "grp": None, "mdns_name": None,
            "ha": None, "vendor": None, "first_seen": 0}
    return {**base, **kw}


def contended_address_judged_different() -> None:
    """Two devices that take the same address in turn (a modem and a camera in a real export): global MACs, a different group, name and Home Assistant
    model for each: the card is told apart as two devices and the user is warned, nothing on the card is changed."""
    modem = _profile("c4:5b:be:00:00:01", grp="router", dhcp_name="lte-modem", ha=("Maker A", "LTE", "Modem"))
    camera = _profile("9c:53:22:00:00:02", grp="media", dhcp_name="camera-03", ha=("Maker B", "Cam", "Camera"))
    result = identity_shift.judge(modem, camera, shared=set())
    assert result["verdict"] == "different" and len(result["reasons"]) >= 2, result


def phone_flip_is_not_a_second_device() -> None:
    """A phone flipping between its own private MAC and the MAC lent by a repeater is never judged as a second device (private and shared vetoes)."""
    own, lent = _profile("42:4b:cd:00:00:01", private=True, grp="phone", dhcp_name="phone"), _profile(LENT, grp="router", dhcp_name="repeater")
    assert identity_shift.judge(own, lent, shared={LENT})["verdict"] == "unknown"
    laptop = _profile(GLOBAL, grp="pc", dhcp_name="laptop")   # a global MAC: only the lent one forbids the judgement
    assert "shared" in identity_shift.judge(laptop, lent, shared={LENT})["vetoes"]


SCENARIOS = {f.__name__: f for f in (lent_mac_mdns, phone_on_lent_mac, repeater_private_mac_stays_router, private_mac_alone_not_phone, no_ports_alone_not_phone, rotation_adds_mobile,
                                     media_receiver_not_phone, nightly_pc_not_phone, global_mac_not_rotation, lent_mac_ignored_in_history,
                                     phone_two_cards_one_mac, contended_address_judged_different, phone_flip_is_not_a_second_device)}
