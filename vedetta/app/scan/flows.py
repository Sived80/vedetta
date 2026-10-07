"""Registry of the functions (steps) and profiles (sub-flows) of the search.

Searches are ONE SINGLE flow (see pipeline.py) made of independent functions;
the three profiles choose which functions to enable:
  initial     = initial search (magnifier button): host discovery on the LAN.
  associative = associative search: scan of the chosen devices before adding them.
  deep        = deep search: rescan of the devices already on the dashboard
                (button and nightly maintenance).

This module is pure logic (no imports from the rest of the app): registry,
defaults and validation, shared by settings.py, pipeline.py and the APIs."""
from dataclasses import dataclass

INITIAL = "initial"
ASSOCIATIVE = "associative"
DEEP = "deep"
PROFILES = (INITIAL, ASSOCIATIVE, DEEP)


@dataclass(frozen=True)
class Step:
    id: str
    flows: tuple[str, ...]            # profiles in which the step is applicable
    locked_in: tuple[str, ...] = ()   # profiles in which it is mandatory
    risk: str = "easy"                # easy (not invasive) | invasive | risky


_ALL = PROFILES
_HOST = (ASSOCIATIVE, DEEP)  # steps that work on a known host, not on discovery

# The order here is the canonical order in which the lists are saved and shown.
#
# Risk of each function, based on what it does on the network:
#   easy     standard and light requests (ARP, mDNS, UPnP, WS-Discovery, reverse DNS, HTTP/RTSP
#            as a single request): they do not disturb the devices.
#   invasive queries the device directly (ports, certificates, APIs, SNMP): it may
#            show up in its logs or in security alerts.
#   risky    aggressive or very long probes (all ports, OS detection,
#            multicast traffic): they can slow down or lock up fragile devices.
STEPS: tuple[Step, ...] = (
    Step("arp", (INITIAL,), (INITIAL,), "easy"),
    # Names are not searched in the initial search (with so little information random
    # names come out): the list of found hosts has only IP and MAC. They are searched in the device analysis.
    # Home Assistant data (device registry: name, manufacturer, model, area): does not touch the network.
    Step("ha_registry", _HOST, risk="easy"),
    Step("mdns", _HOST, risk="easy"),
    Step("reverse_names", _HOST, risk="easy"),
    Step("ssdp", _HOST, risk="easy"),
    Step("onvif", _HOST, risk="easy"),
    Step("rtsp", _HOST, risk="easy"),
    Step("netbios_snmp", _HOST, risk="invasive"),
    Step("ports_fast", _HOST, risk="invasive"),
    Step("ports_all", _HOST, risk="risky"),
    Step("service_os", _HOST, risk="risky"),
    Step("http_title", _HOST, risk="easy"),
    Step("tls_ssh", _HOST, risk="invasive"),
    Step("local_api", _HOST, risk="invasive"),
    Step("igmp", (DEEP,), risk="risky"),
    Step("adapter_probe", _HOST, risk="invasive"),
)
STEP_IDS = tuple(s.id for s in STEPS)
_BY_ID = {s.id: s for s in STEPS}

# Functions available but off until the user turns them on (see the description).
OFF_BY_DEFAULT = {"igmp"}

# Defaults: initial = 2 functions, associative = 4, deep = all the applicable ones.
DEFAULT_FLOWS: dict[str, tuple[str, ...]] = {
    INITIAL: ("arp",),
    ASSOCIATIVE: ("ha_registry", "reverse_names", "onvif", "rtsp", "ports_fast", "http_title", "tls_ssh", "local_api", "adapter_probe"),
    DEEP: tuple(s.id for s in STEPS if DEEP in s.flows and s.id not in OFF_BY_DEFAULT),
}


def default_flows() -> dict[str, list[str]]:
    return {p: list(ids) for p, ids in DEFAULT_FLOWS.items()}


class FlowError(ValueError):
    """Invalid flow setting: key is the translation key of the
    message (flow.error.*), params its placeholders."""

    def __init__(self, key: str, **params) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


def validate_profile(profile: str, ids) -> list[str]:
    """Valid list of steps for a profile, normalized (no duplicates, in
    canonical order). FlowError if not valid."""
    if profile not in PROFILES:
        raise FlowError("flow.error.unknown_profile", profile=str(profile))
    if not isinstance(ids, list):
        raise FlowError("flow.error.not_a_list", profile=profile)
    for step_id in ids:
        step = _BY_ID.get(step_id) if isinstance(step_id, str) else None
        if step is None:
            raise FlowError("flow.error.unknown_step", step=str(step_id))
        if profile not in step.flows:
            raise FlowError("flow.error.not_applicable", step=step.id, profile=profile)
    chosen = set(ids)
    for step in STEPS:
        if profile in step.locked_in and step.id not in chosen:
            raise FlowError("flow.error.required", step=step.id, profile=profile)
    if not chosen:
        raise FlowError("flow.error.empty", profile=profile)
    return [s.id for s in STEPS if s.id in chosen]


def validate_flows(flows) -> dict[str, list[str]]:
    """Validation of a {profile: [steps]} dict (even partial)."""
    if not isinstance(flows, dict):
        raise FlowError("flow.error.invalid_body")
    return {profile: validate_profile(profile, ids) for profile, ids in flows.items()}
