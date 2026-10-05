"""Verifica del flusso unico di ricerca: composizione nmap, validazione delle
impostazioni, default, dipendenze saltate, traduzioni, pipeline con primitive finte.
Nel container: python tests/check_pipeline.py
In locale (Windows) funziona anche senza zoneinfo: se app.applog non si
importa lo si simula. Usa una cartella config temporanea.
Con "python - < file" la cartella corrente deve essere la radice del progetto."""
import asyncio
import json
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, ".")
try:
    import app.applog  # noqa: F401
except Exception:
    stub = types.ModuleType("app.applog")
    import logging
    stub.logger = logging.getLogger("dashboard")
    sys.modules["app.applog"] = stub

try:
    import httpx  # noqa: F401
except ImportError:  # in locale puo' mancare: gli adapter qui sono comunque simulati
    sys.modules["httpx"] = types.ModuleType("httpx")

from app import flows, i18n, pipeline, scanner, settings

tmp = Path(tempfile.mkdtemp())
settings.SETTINGS_PATH = tmp / "settings.json"

IP = "10.0.0.5"
compose = pipeline.compose_nmap_args

# 1) default
d = flows.default_flows()
assert d["initial"] == ["arp"]
assert d["associative"] == ["ha_registry", "reverse_names", "onvif", "rtsp", "ports_fast", "http_title", "tls_ssh", "local_api", "adapter_probe"]
assert d["deep"] == [s.id for s in flows.STEPS if "deep" in s.flows and s.id not in flows.OFF_BY_DEFAULT] and "arp" not in d["deep"]
assert "igmp" not in d["deep"]
assert len(d["deep"]) == 14
assert settings.flows_load() == d  # file assente = default
print("ok: default")

# 2) composizione nmap: una sola invocazione, equivalente alle vecchie
assert compose(d["deep"], IP) == ["-T4", "-sV", "--version-light", "--host-timeout", "150s",
                                  "--script", "http-title", "-p-", IP]
assert compose(d["associative"], IP) == ["-T4", "--host-timeout", "30s", "-p-", IP]
assert compose(["ports_all"], IP) == ["-T4", "--host-timeout", "150s", "-p-", IP]
assert compose(["ports_fast", "ports_all"], IP) == ["-T4", "--host-timeout", "150s", "-p-", IP]
assert compose(["service_os"], IP) == ["-T4", "-sV", "--version-light", "--host-timeout", "150s", IP]
assert compose(["ports_fast", "http_title"], IP) == ["-T4", "--host-timeout", "30s", "-p-", IP], "http-title solo con service_os"
assert compose(["service_os", "ports_fast"], IP)[-2:] == ["-p-", IP]
for none in ([], ["mdns"], ["http_title", "adapter_probe", "netbios_snmp", "ssdp", "reverse_names"]):
    assert compose(none, IP) is None
print("ok: composizione nmap")

# 3) dipendenze: http_title e adapter_probe senza porte -> saltati
run, skipped = pipeline.resolve_plan(["http_title", "adapter_probe", "netbios_snmp"])
assert run == ["netbios_snmp"] and [s for s, _ in skipped] == ["http_title", "adapter_probe"]
run, skipped = pipeline.resolve_plan(d["deep"])
assert run == d["deep"] and skipped == []
run, skipped = pipeline.resolve_plan(["service_os", "adapter_probe"])
assert skipped == []
print("ok: dipendenze saltate")

# 4) validazione
v = flows.validate_profile
assert v("associative", ["http_title", "mdns", "mdns"]) == ["mdns", "http_title"]  # ordine canonico, senza doppioni
for profile, ids, key in (
    ("initial", [], "flow.error.required"),
    ("initial", ["mdns"], "flow.error.not_applicable"),
    ("initial", ["arp", "mdns"], "flow.error.not_applicable"),
    ("initial", ["arp", "ports_all"], "flow.error.not_applicable"),
    ("associative", ["arp"], "flow.error.not_applicable"),
    ("deep", ["arp"], "flow.error.not_applicable"),
    ("deep", ["boh"], "flow.error.unknown_step"),
    ("deep", [3], "flow.error.unknown_step"),
    ("deep", "ports_all", "flow.error.not_a_list"),
    ("deep", [], "flow.error.empty"),
    ("altro", ["mdns"], "flow.error.unknown_profile"),
):
    try:
        v(profile, ids)
        raise SystemExit(f"doveva rifiutare {profile} {ids}")
    except flows.FlowError as exc:
        assert exc.key == key, (profile, ids, exc.key)
print("ok: validazione")

# 5) impostazioni: parziale, persistenza, alerts non perso, reset, file corrotto
assert settings.flows_update({"deep": ["ports_all", "netbios_snmp"]}) == {**d, "deep": ["netbios_snmp", "ports_all"]}
assert settings.flows_load()["associative"] == d["associative"]
assert settings.update({"alerts": False}) == {"alerts": False, "poll_interval": 30, "miss_limit": 3}
saved = json.loads(settings.SETTINGS_PATH.read_text(encoding="utf-8"))
assert saved == {"alerts": False, "poll_interval": 30, "miss_limit": 3, "flows": {"deep": ["netbios_snmp", "ports_all"]}}, saved
assert settings.load() == {"alerts": False, "poll_interval": 30, "miss_limit": 3}  # load() delle impostazioni semplici invariato
try:
    settings.flows_update({"initial": ["mdns"], "deep": ["ports_fast"]})
    raise SystemExit("doveva rifiutare")
except flows.FlowError:
    pass
assert settings.flows_load()["deep"] == ["netbios_snmp", "ports_all"], "una richiesta non valida non salva nulla"
settings.SETTINGS_PATH.write_text(json.dumps({"flows": {"initial": ["mdns"], "deep": ["ssdp"]}}), encoding="utf-8")
assert settings.flows_load() == {**d, "deep": ["ssdp"]}, "profilo non valido -> default, gli altri restano"
assert settings.flows_reset() == d
assert "flows" not in json.loads(settings.SETTINGS_PATH.read_text(encoding="utf-8"))
print("ok: impostazioni flussi")

# 6) traduzioni complete in entrambe le lingue
for lang in ("en", "it"):
    for s in flows.STEPS:
        for part in ("label", "description"):
            key = f"flow.step.{s.id}.{part}"
            assert i18n.translate(lang, key) != key, (lang, key)
    for p in flows.PROFILES:
        for part in ("label", "description"):
            key = f"flow.profile.{p}.{part}"
            assert i18n.translate(lang, key) != key, (lang, key)
    for key in ("invalid_body", "unknown_profile", "not_a_list", "unknown_step", "not_applicable", "required", "empty"):
        assert i18n.translate(lang, "flow.error." + key, profile="p", step="s") != "flow.error." + key
print("ok: traduzioni")

# 7) pipeline con primitive finte: nessun nmap/avahi veri
calls = []


async def fake_run_nmap(args, semaphore=None):
    calls.append(("nmap", args))
    return ('<nmaprun><host><status state="up"/><address addr="10.0.0.5" addrtype="ipv4"/>'
            '<ports><port portid="80"><state state="open"/><service name="http" method="probed"/></port></ports>'
            '</host></nmaprun>')


async def fake_protocol(ip, timeout=12):
    calls.append(("proto", ip))
    return {"netbios_name": "PC"}


async def fake_ssdp(timeout=6):
    calls.append(("ssdp",))
    return {IP: {"name": "TV"}}


async def fake_mdns():
    calls.append(("mdns",))
    return {IP: "salotto"}


async def fake_resolve(ips, passive_names=None):
    calls.append(("resolve", passive_names is None))
    return dict(passive_names or {})


async def fake_confirm(ip, ports):
    calls.append(("confirm", ip))


async def fake_shelly(ip, port):
    calls.append(("shelly", ip, port))
    return {"mac": "AA", "uptime_seconds": 5, "name": "shelly1", "extra": {"x": 1}}


scanner._run_nmap, scanner.protocol_scan, scanner.ssdp_scan = fake_run_nmap, fake_protocol, fake_ssdp
PILOT = {"slow": False, "elapsed": 0.8, "ports": []}


async def fake_pilot(ip):
    calls.append(("pilot", ip))
    return dict(PILOT)


scanner.pilot = fake_pilot
scanner.mdns_scan, scanner.resolve_names, scanner._confirm_http_ports = fake_mdns, fake_resolve, fake_confirm
pipeline.shelly_gen1.probe = fake_shelly


async def main():
    # deep di default: UN solo nmap, ssdp e mdns una volta, protocolli in parallelo
    batch = await pipeline.prepare_batch("deep", [IP])
    info = await pipeline.run_deep(IP, batch)
    assert [c for c in calls if c[0] == "nmap"] == [("nmap", compose(d["deep"], IP))]
    assert ("pilot", IP) in calls  # prima di tutte le porte si misura se il dispositivo regge
    assert info["mdns_name"] == "" or info["mdns_name"] is None or info["mdns_name"] == "salotto"
    assert info["netbios_name"] == "PC" and info["upnp_name"] == "TV" and info["adapter"] == "shelly_gen1"
    fields = scanner.format_scan_info(info)
    assert fields["ports"][0]["label"].startswith("80") and fields["netbios_name"] == "PC"
    calls.clear()

    # profilo deep ridotto: letto a ogni esecuzione, nessun nmap, http_title saltato
    settings.flows_update({"deep": ["netbios_snmp", "http_title"]})
    batch = await pipeline.prepare_batch("deep", [IP])
    info = await pipeline.run_deep(IP, batch)
    assert not [c for c in calls if c[0] in ("nmap", "ssdp", "mdns", "confirm", "shelly")], calls
    assert info["netbios_name"] == "PC" and info["ports"] == [] and info["adapter"] == "generic"
    calls.clear()

    # associativa di default: nmap rapido + conferma web + adapter Shelly, nome dallo Shelly
    settings.flows_reset()
    r = await pipeline.run_associative(IP, "hint")
    assert [c for c in calls if c[0] == "nmap"] == [("nmap", compose(d["associative"], IP))]
    assert r["adapter"] == "shelly_gen1" and r["suggested_name"] == "shelly1" and r["suggested_port"] == 80
    assert set(r) >= {"ip", "mac", "hostname", "ports", "adapter", "suggested_name", "suggested_port", "shelly_extra"}
    calls.clear()

    # associativa senza porte: http_title/adapter saltati, nome dal suggerimento
    settings.flows_update({"associative": ["reverse_names", "http_title", "adapter_probe"]})
    r = await pipeline.run_associative(IP, "hint")
    assert not [c for c in calls if c[0] in ("nmap", "confirm", "shelly")]
    assert r["adapter"] == "generic" and r["suggested_name"] == "hint" and r["ports"] == []
    calls.clear()

    # iniziale: solo ARP (IP e MAC), nessuna ricerca di nomi (ne' mDNS ne' nomi inversi)
    async def fake_arp():
        return [{"ip": IP, "mac": "AA:BB:CC:00:00:01", "vendor": None}]
    scanner.arp_scan = fake_arp
    settings.flows_reset()
    hosts = await pipeline.run_initial()
    assert hosts[0]["ip"] == IP and hosts[0]["mac"] == "AA:BB:CC:00:00:01" and hosts[0]["ports"] == []
    assert not [c for c in calls if c[0] in ("resolve", "mdns")]
    # il computer che esegue l'app non compare in ARP: si aggiunge con il MAC della sua interfaccia
    assert scanner.own_host(None, []) is None
    assert scanner.own_host("10.0.0.5", [{"ip": "10.0.0.5", "mac": "AA:BB:CC:00:00:09"}]) is None


asyncio.run(main())
# Dispositivo lento: la prova pilota lo segnala e si scansionano le porte mirate (60 s).
async def slow_case():
    calls.clear()
    PILOT.update(slow=True, elapsed=11.0)
    info = await pipeline.run_deep(IP, await pipeline.prepare_batch("deep", [IP]))
    args = [c[1] for c in calls if c[0] == "nmap"][0]
    assert "-p-" not in args and scanner.FAST_PORTS in args and args[args.index("--host-timeout") + 1] == "60s", args
    assert info.get("slow_scan") is True
    PILOT.update(slow=False, elapsed=0.8)
asyncio.run(slow_case())
print("ok: pipeline con primitive finte")
print("TUTTO OK")
