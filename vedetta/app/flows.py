"""Registro delle funzioni (step) e dei profili (sottoflussi) della ricerca.

Le ricerche sono UN SOLO flusso (vedi pipeline.py) fatto di funzioni indipendenti;
i tre profili scelgono quali funzioni attivare:
  initial     = ricerca iniziale (pulsante lente): scoperta host in LAN.
  associative = ricerca associativa: scansione dei dispositivi scelti prima di aggiungerli.
  deep        = ricerca approfondita: riscansione dei dispositivi gia' in dashboard
                (pulsante e manutenzione notturna).

Questo modulo e' logica pura (nessun import dal resto dell'app): registro,
default e validazione, condivisi da settings.py, pipeline.py e dalle API."""
from dataclasses import dataclass

INITIAL = "initial"
ASSOCIATIVE = "associative"
DEEP = "deep"
PROFILES = (INITIAL, ASSOCIATIVE, DEEP)


@dataclass(frozen=True)
class Step:
    id: str
    flows: tuple[str, ...]            # profili in cui lo step e' applicabile
    locked_in: tuple[str, ...] = ()   # profili in cui e' obbligatorio
    risk: str = "easy"                # easy (non invasivo) | invasive (invasivo) | risky (rischioso)


_ALL = PROFILES
_HOST = (ASSOCIATIVE, DEEP)  # step che lavorano su un host noto, non sulla scoperta

# L'ordine qui e' l'ordine canonico con cui le liste vengono salvate e mostrate.
#
# Rischio di ogni funzione, da cosa fa in rete:
#   easy     richieste standard e leggere (ARP, mDNS, UPnP, WS-Discovery, DNS inverso, HTTP/RTSP
#            su richiesta singola): non disturbano i dispositivi.
#   invasive interroga direttamente il dispositivo (porte, certificati, API, SNMP): puo'
#            comparire nei suoi registri o negli avvisi di sicurezza.
#   risky    prove aggressive o molto lunghe (tutte le porte, riconoscimento del sistema,
#            traffico multicast): possono rallentare o bloccare dispositivi fragili.
STEPS: tuple[Step, ...] = (
    Step("arp", (INITIAL,), (INITIAL,), "easy"),
    # I nomi non si cercano nella ricerca iniziale (con cosi' poche informazioni escono nomi
    # a caso): l'elenco dei trovati ha solo IP e MAC. Si cercano nell'analisi dei dispositivi.
    # Dati di Home Assistant (registro dispositivi: nome, produttore, modello, area): non tocca la rete.
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

# Funzioni disponibili ma spente finche' l'utente non le accende (vedi la descrizione).
OFF_BY_DEFAULT = {"igmp"}

# Default: initial = 2 funzioni, associative = 4, deep = tutte quelle applicabili.
DEFAULT_FLOWS: dict[str, tuple[str, ...]] = {
    INITIAL: ("arp",),
    ASSOCIATIVE: ("ha_registry", "reverse_names", "onvif", "rtsp", "ports_fast", "http_title", "tls_ssh", "local_api", "adapter_probe"),
    DEEP: tuple(s.id for s in STEPS if DEEP in s.flows and s.id not in OFF_BY_DEFAULT),
}


def default_flows() -> dict[str, list[str]]:
    return {p: list(ids) for p, ids in DEFAULT_FLOWS.items()}


def get_step(step_id: str) -> Step | None:
    return _BY_ID.get(step_id)


class FlowError(ValueError):
    """Impostazione dei flussi non valida: key e' la chiave di traduzione del
    messaggio (flow.error.*), params i suoi segnaposto."""

    def __init__(self, key: str, **params) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


def validate_profile(profile: str, ids) -> list[str]:
    """Elenco di step valido per un profilo, normalizzato (senza doppioni, in
    ordine canonico). FlowError se non valido."""
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
    """Validazione di un dict {profilo: [step]} (anche parziale)."""
    if not isinstance(flows, dict):
        raise FlowError("flow.error.invalid_body")
    return {profile: validate_profile(profile, ids) for profile, ids in flows.items()}
