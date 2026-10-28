"""The scenarios: what happens to the cards of Vedetta when the virtual phones do the things that produce doubles or wrong names. Each scenario builds its own
network and a fresh Vedetta, drives the phones, and returns what the cards say; the expectations are in the docstrings and judged by run_scenarios.py."""
from tools.lansim.lan import Lan
from tools.lansim.vedetta_proc import VedettaProcess

ANDROID_MAC, IOS_MAC, IOS_MAC_2 = "c6:00:00:00:00:21", "5a:00:00:00:00:22", "5a:00:00:00:00:24"
SETTLE = 2         # update cycles to wait after a change before looking at the cards


def _phone_cards(vedetta: VedettaProcess) -> list[dict]:
    return sorted(({"ip": c.get("ip"), "name": c.get("name"), "name_source": c.get("name_source"), "online": c.get("online"),
                    "brand": c.get("brand"), "type": c.get("type")} for c in vedetta.cards() if c.get("is_mobile") or c.get("type") == "phone"),
                  key=lambda c: c["ip"] or "")


def s1_stable(code_dir: str) -> dict:
    """An Android phone on the network, nothing happens: one phone card, named as the phone announces itself."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", ANDROID_MAC, 20)
        lan.announce("c1", "android", ANDROID_MAC, address)
        vedetta.add_found()
        vedetta.wait_cycles(SETTLE + 1)
        return {"phones": _phone_cards(vedetta)}


def s4_extender_holds(code_dir: str) -> dict:
    """The extender answers for the phone's address in turns with the phone, several times: still one phone card, the same name, no new card for the extender's MAC."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", ANDROID_MAC, 20)
        lan.announce("c1", "android", ANDROID_MAC, address)
        vedetta.add_found()
        vedetta.wait_cycles(SETTLE + 1)
        before = _phone_cards(vedetta)
        for held in (True, False, True, False, True, False):
            lan.hold("c1", address, held)
            vedetta.wait_cycles(1)
        vedetta.wait_cycles(SETTLE)
        return {"before": before, "after": _phone_cards(vedetta), "cards_total": len(vedetta.cards())}


def s5_inherited_name(code_dir: str) -> dict:
    """An Android phone leaves; an iPhone with a private MAC takes the same address. The card must not carry on with the Android name."""
    with Lan() as lan, VedettaProcess(code_dir) as vedetta:
        address = lan.add_client("c1", ANDROID_MAC, 20)
        lan.announce("c1", "android", ANDROID_MAC, address)
        vedetta.add_found()
        vedetta.wait_cycles(SETTLE + 1)
        before = _phone_cards(vedetta)
        lan.link("c1", False)
        vedetta.wait_cycles(SETTLE)
        lan.add_client("c2", IOS_MAC, 20)
        lan.announce("c2", "ios", IOS_MAC, address)
        vedetta.wait_cycles(SETTLE + 2)
        return {"before": before, "after": _phone_cards(vedetta)}


SCENARIOS = {"S1": s1_stable, "S4": s4_extender_holds, "S5": s5_inherited_name}
