"""The touch policy: how much a device is contacted. Rule: never risk commanding a device.
  none   - only watching (ARP, announcements, presence). The user chose «don't touch», or the device has a printing or industrial control port open and the user did not say otherwise;
  calm   - the device is slow: no risky step (all ports, service detection), everything else as the profile says;
  normal - everything the profile says.
This is also the pre-analysis of the fragile devices: it reads only what the saved scan already knows (the slow flag, the open ports) and sends nothing.
The choice of the user is the field `no_touch` of the card: "on" (or true) = don't touch; "off" (or false) = the user took the automatic protection away (the device stays calm if it is fragile).
Pure functions, no network and no clock."""
from dataclasses import replace

from . import flows
from .scan_common import is_no_talk_port

NONE, CALM, NORMAL = "none", "calm", "normal"
_ON, _OFF = (True, "on"), (False, "off")


def fragile_reasons(device: dict) -> list[str]:
    """Why a device is fragile, from the saved scan: an open printing or industrial control port, and the slow flag."""
    info = device.get("scan_info") or {}
    found = []
    if any(is_no_talk_port(p) for p in info.get("ports") or []):
        found.append("no_talk_port")
    if info.get("slow_scan"):
        found.append("slow")
    return found


def touch_level(device: dict) -> str:
    choice = device.get("no_touch")
    if choice in _ON:
        return NONE
    reasons = fragile_reasons(device)
    if "no_talk_port" in reasons and choice not in _OFF:
        return NONE
    return CALM if reasons else NORMAL


def may_touch(device: dict) -> bool:
    """False when only watching is allowed: no adapter call, no response-time measure, no scan."""
    return touch_level(device) != NONE


def touchable(devices: list[dict]) -> list[dict]:
    """The cards that may be asked something (the others are only watched)."""
    return [d for d in devices if may_touch(d)]


def calm_steps(steps: list[str]) -> list[str]:
    """The steps of a profile without the risky ones (flows.Step.risk), in the same order."""
    risky = {s.id for s in flows.STEPS if s.risk == "risky"}
    return [s for s in steps if s not in risky]


def calm_batch(batch):
    return replace(batch, steps=calm_steps(batch.steps))
