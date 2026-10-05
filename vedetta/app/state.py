import asyncio
import json
import time

from .formatters import update_generic_titles
from . import blocklist, devices_config, dhcp, latency, netutil, newdevices, probe, scanner, settings
from .applog import logger
from .history import history

# L'intervallo di controllo e' una impostazione (settings.poll_interval, 10-300 s),
# riletta a ogni ciclo: vedi _interval().
ARP_MAX_AGE = 10
_MAX_TOMBSTONES = 200
_QUEUE_SIZE = 200

# Un dispositivo risulta offline solo dopo questo numero di controlli falliti
# consecutivi (~90s a 30s di intervallo). Telefoni in standby e dispositivi con
# il WiFi a risparmio energetico saltano ogni tanto un controllo: senza questa
# tolleranza le loro card cambiavano stato (e venivano sostituite) a ogni ciclo.
# Il ritardo di rilevamento offline scala con l'intervallo scelto (3 x intervallo).
MISS_LIMIT = 3

# Campi che il probe OSSERVA sul dispositivo (non derivano dalla configurazione):
# se un controllo fallisce ma il dispositivo e' ancora "tollerato" come online,
# si tengono quelli dell'ultimo controllo riuscito invece di svuotarli.
_OBSERVED = ("mac", "vendor", "vendor_role", "brand", "brand_source", "brand_confidence", "battery", "battery_source", "uptime", "signal_kind", "signal_value", "signal_band", "signal_label", "signal_color")


def _ip_key(device: dict) -> tuple[int, ...]:
    return tuple(int(o) for o in device["ip"].split("."))


class DeviceState:
    """Stato dei dispositivi tenuto in memoria e aggiornato da un poller in
    background. Le pagine lo leggono senza fare probe sincroni, e ogni cambiamento
    viene inviato ai browser aperti come evento (SSE)."""

    def __init__(self) -> None:
        self.devices: dict[str, dict] = {}
        self.rev = 0
        self.ready = asyncio.Event()
        # Ultimo MAC visto per dispositivo: da spento il probe non lo vede piu',
        # ma serve ancora a riconoscerne nome e marca (impronta DHCP, prefisso).
        self._last_mac: dict[str, str] = {}
        self._rev_of: dict[str, int] = {}
        self._removed: dict[str, int] = {}
        self._subscribers: set[asyncio.Queue] = set()
        self._wake = asyncio.Event()
        self._force = False  # un aggiornamento chiesto a mano vale anche in pausa
        self._conflicts_reported: set = set()
        self._paused_until: float | None = self._load_pause()  # epoch; inf = fino alla ripresa; None = attivo
        self._task: asyncio.Task | None = None
        self._next_at = 0.0
        self._arp: tuple[float, dict[str, dict]] | None = None
        self._arp_lock = asyncio.Lock()
        self._misses: dict[str, int] = {}
        self._last_seen: dict[str, float] = {}
        self._db_state: dict[str, bool] = {}
        self._bg: set[asyncio.Future] = set()
        # Scansioni in corso: stanno qui (e non solo nel browser che le ha
        # avviate) cosi' cambiando pagina e tornando il led lampeggiante e
        # l'effetto sul pulsante di ricerca si ritrovano com'erano.
        self.rescanning: set[str] = set()
        self._search_running = 0
        self._search_hold_until = 0.0
        self._newdev_macs: frozenset[str] = frozenset()
        self._newdev_lock = asyncio.Lock()
        self._own_ip: str | None = None

    # ---- ciclo di vita ----
    async def load_history(self) -> None:
        """Riparte dallo stato salvato: senza, dopo ogni riavvio si
        perderebbe "visto l'ultima volta" dei dispositivi offline."""
        try:
            last = await asyncio.to_thread(history.last_presence)
        except Exception:
            logger.exception("Lettura dello storico presenza fallita")
            return
        for device_id, (online, ts) in last.items():
            self._db_state[device_id] = online
            if not online:
                self._last_seen[device_id] = ts
            mac = await asyncio.to_thread(history.last_mac, device_id)
            if mac:
                self._last_mac[device_id] = mac

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def trigger(self, force: bool = False) -> None:
        """Forza un ciclo di aggiornamento immediato (force: anche in pausa)."""
        if force:
            self._force = True
        self._wake.set()

    # ---- pausa del controllo periodico ----
    @staticmethod
    def _pause_file():
        return settings.CONFIG_DIR / "pause.json"

    @classmethod
    def _load_pause(cls) -> float | None:
        """La pausa sopravvive al riavvio del servizio (come tutte le impostazioni)."""
        try:
            raw = json.loads(cls._pause_file().read_text(encoding="utf-8")).get("until")
        except (OSError, ValueError, AttributeError):
            return None
        if raw == "forever":
            return float("inf")
        if isinstance(raw, (int, float)) and raw > time.time():
            return float(raw)
        return None

    def _save_pause(self) -> None:
        try:
            path = self._pause_file()
            if self._paused_until is None:
                path.unlink(missing_ok=True)
                return
            path.parent.mkdir(parents=True, exist_ok=True)
            until = "forever" if self._paused_until == float("inf") else self._paused_until
            path.write_text(json.dumps({"until": until}), encoding="utf-8")
        except OSError:
            logger.exception("Pausa non salvata su disco")

    def paused_remaining(self) -> float | None:
        """Secondi alla fine della pausa (inf = senza scadenza); None se non in pausa."""
        if self._paused_until is None:
            return None
        left = self._paused_until - time.time()
        if left <= 0:
            self._paused_until = None
            return None
        return left

    def pause(self, minutes: int = 0) -> None:
        """Sospende i controlli periodici per N minuti (0 = finche' non si riprende).
        Le azioni chieste a mano (aggiorna, ricerca) restano possibili."""
        self._paused_until = time.time() + minutes * 60 if minutes else float("inf")
        self._save_pause()
        logger.info("Controllo periodico in pausa (%s)", f"{minutes} min" if minutes else "fino alla ripresa")
        self._emit(self.poll_info())
        self._wake.set()

    def resume(self) -> None:
        self._paused_until = None
        self._save_pause()
        logger.info("Controllo periodico ripreso")
        self._force = True
        self._emit(self.poll_info())
        self._wake.set()

    # ---- lettura ----
    def sorted_devices(self) -> list[dict]:
        return sorted(self.devices.values(), key=_ip_key)

    def poll_info(self) -> dict:
        interval = self._interval()
        next_in = max(0.0, self._next_at - time.monotonic()) if self._next_at else interval
        left = self.paused_remaining()
        return {
            "type": "poll", "rev": self.rev, "interval_ms": interval * 1000, "next_in_ms": int(next_in * 1000),
            "paused": left is not None,
            "paused_in_ms": int(left * 1000) if left is not None and left != float("inf") else None,
        }

    @staticmethod
    def _miss_limit() -> int:
        """Controlli falliti di fila prima dell'offline (impostazione dell'utente)."""
        try:
            return settings.miss_limit()
        except Exception:
            return MISS_LIMIT

    @staticmethod
    def _interval() -> int:
        """Intervallo corrente in secondi (impostazione dell'utente)."""
        try:
            return settings.poll_interval()
        except Exception:
            return settings.DEFAULTS["poll_interval"]

    # ---- eventi ----
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def is_subscribed(self, q: asyncio.Queue) -> bool:
        return q in self._subscribers

    # ---- attivita' in corso ----
    def track(self, future: asyncio.Future) -> None:
        """Tiene un riferimento forte a un lavoro in background: un task senza
        riferimenti puo' essere eliminato dal garbage collector a meta'."""
        self._bg.add(future)
        future.add_done_callback(self._bg.discard)

    def activity_info(self) -> dict:
        searching = self._search_running > 0 or time.monotonic() < self._search_hold_until
        return {"type": "activity", "rev": self.rev, "rescanning": sorted(self.rescanning), "search": searching}

    def _emit_activity(self) -> None:
        self._emit(self.activity_info())

    def rescan_started(self, device_ids: list[str]) -> None:
        self.rescanning.update(device_ids)
        self._emit_activity()

    def rescan_finished(self, device_id: str) -> None:
        self.rescanning.discard(device_id)
        self._emit_activity()

    def search_started(self) -> None:
        self._search_running += 1
        self._emit_activity()

    def search_finished(self) -> None:
        self._search_running = max(0, self._search_running - 1)
        # La ricerca e' in due richieste (rapida, poi approfondita): una breve
        # tenuta evita che l'effetto si spenga e riaccenda tra l'una e l'altra.
        self._search_hold_until = time.monotonic() + 2.5
        self._emit_activity()
        asyncio.get_running_loop().call_later(2.6, self._emit_activity)

    def emit_event(self, event: dict) -> None:
        """Evento generico verso i browser aperti (es. ruoli di rete aggiornati)."""
        self._emit(event)

    def emit_alert(self, log_message: str, key: str, **params) -> None:
        """Avviso (es. nuova porta aperta): al log il testo cosi' com'e', ai
        browser aperti chiave e parametri, tradotti nella lingua di ciascuno."""
        logger.warning(log_message)
        from . import journal  # tardivo: evita cicli all'import
        journal.add("normal", key, icon="alert", **params)
        self._emit({"type": "alert", "level": "warning", "key": key, "params": params})

    def _emit(self, event: dict) -> None:
        event = {**event, "rev": self.rev} if "rev" not in event else event
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Client troppo lento: lo si scollega, si riconnettera' da solo
                # e ricevera' le differenze mancanti tramite catch_up.
                self._subscribers.discard(q)

    def catch_up(self, since: int) -> list[dict]:
        """Eventi persi da un client rimasto indietro (o appena collegato con la
        revisione della pagina che ha ricevuto)."""
        events = []
        for device_id, rev in self._rev_of.items():
            if rev > since and device_id in self.devices:
                events.append({"type": "device", "id": device_id, "rev": rev, "device": self.devices[device_id]})
        for device_id, rev in self._removed.items():
            if rev > since:
                events.append({"type": "removed", "id": device_id, "rev": rev})
        return events

    # ---- aggiornamento ----
    async def arp_snapshot(self) -> dict[str, dict]:
        """Tabella ARP recente (riusa quella del ciclo di controllo se fresca)."""
        return await self._arp_by_ip(120)

    async def _arp_by_ip(self, max_age: float) -> dict[str, dict]:
        async with self._arp_lock:
            now = time.monotonic()
            if self._arp is None or now - self._arp[0] > max_age:
                try:
                    hosts = await scanner.arp_scan()
                    self._arp = (time.monotonic(), {h["ip"]: h for h in hosts})
                except Exception:
                    logger.exception("Scansione ARP fallita")
                    if self._arp is None:
                        self._arp = (time.monotonic(), {})
            return self._arp[1]

    def _record_presence(self, result: dict, online: bool, ts: float) -> None:
        """Salva nello storico solo le transizioni online/offline."""
        device_id = result["id"]
        if self._db_state.get(device_id) == online:
            return
        self._db_state[device_id] = online
        task = asyncio.create_task(self._write_presence(device_id, result.get("ip"), result.get("mac"), online, ts))
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def _write_presence(self, device_id: str, ip: str | None, mac: str | None, online: bool, ts: float) -> None:
        try:
            await asyncio.to_thread(history.record_presence, device_id, ip, mac, online, ts)
        except Exception:
            logger.exception("Salvataggio dello storico presenza fallito per %s", device_id)

    def _apply(self, config: dict, result: dict, current: dict[str, dict], sample: float | None = None,
               force: bool = False) -> None:
        """sample = tempo di risposta misurato in questo ciclo (ms, None se la
        misura non ha avuto risposta)."""
        # Se la configurazione del dispositivo e' cambiata mentre il probe era in
        # corso (rinomina, nuova scansione...), il risultato e' gia' obsoleto:
        # applicarlo farebbe tornare per un attimo il nome vecchio.
        if current.get(config["id"]) != config:
            return

        device_id = result["id"]
        auto = result.pop("auto_name", None)
        if auto:
            devices_config.update_auto_name(device_id, auto[0], auto[1], force=len(auto) > 2 and bool(auto[2]))
        previous = self.devices.get(device_id)
        now = time.time()
        if result.get("mac"):
            self._last_mac[device_id] = result["mac"]
        if result["online"]:
            latency.tracker.add(device_id, sample)
        if result["online"]:
            self._misses[device_id] = 0
            self._last_seen[device_id] = now
            self._record_presence(result, True, now)
        else:
            misses = self._misses.get(device_id, 0) + 1
            self._misses[device_id] = misses
            if previous is not None and previous["online"] and misses < self._miss_limit():
                result = {
                    **result, "online": True,
                    "extra": {**previous["extra"], **result["extra"]},
                    **{k: previous.get(k) for k in _OBSERVED},
                }
            else:
                # L'evento porta l'istante dell'ultima volta visto online, non
                # quello in cui ci si e' accorti: il grafico parte dal momento
                # reale della caduta.
                self._record_presence(result, False, self._last_seen.get(device_id, now))
        # Solo da offline: per un dispositivo online cambierebbe a ogni ciclo e
        # farebbe sostituire la card ogni 30 secondi senza motivo.
        result["last_seen"] = None if result["online"] else self._last_seen.get(device_id)
        # Tempo di risposta: media mobile a gradini (cambia raramente, quindi non
        # genera un evento a ogni ciclo). Un dispositivo offline non ne ha.
        if result["online"]:
            result["latency_ms"] = latency.tracker.value(device_id)
        else:
            latency.tracker.reset(device_id)
            result["latency_ms"] = None
        result["latency_color"] = latency.color(result["latency_ms"])

        # force: dopo una ricerca l'evento parte comunque, anche se i dati grezzi sono uguali:
        # categoria e icona si calcolano all'invio (ruoli di rete, regole) e la pagina deve rifarle.
        if not force and self.devices.get(result["id"]) == result:
            return
        self.devices[result["id"]] = result
        self.rev += 1
        self._rev_of[result["id"]] = self.rev
        self._removed.pop(result["id"], None)
        # Il dispositivo viaggia grezzo: card e riga HTML le rende il flusso di
        # ogni browser nella sua lingua (vedi api_events in main.py).
        self._emit({"type": "device", "id": result["id"], "device": result})

    def remove(self, device_id: str) -> None:
        if self.devices.pop(device_id, None) is None:
            return
        self._misses.pop(device_id, None)
        self._last_seen.pop(device_id, None)
        self._db_state.pop(device_id, None)
        latency.tracker.reset(device_id)
        self.rev += 1
        self._rev_of.pop(device_id, None)
        self._removed[device_id] = self.rev
        while len(self._removed) > _MAX_TOMBSTONES:
            self._removed.pop(next(iter(self._removed)))
        self._emit({"type": "removed", "id": device_id})

    async def poll_once(self) -> None:
        snapshot = devices_config.load_devices()
        update_generic_titles(snapshot)
        arp_task = asyncio.create_task(self._arp_by_ip(0))
        # Tempo di risposta misurato in parallelo ai probe, nello stesso ciclo.
        lat_task = asyncio.create_task(
            latency.measure_many([(d["id"], d["ip"], d.get("port", 80)) for d in snapshot]))
        results = await asyncio.gather(
            *(probe.probe_device({**d, "last_mac": self._last_mac.get(d["id"])}, arp_task) for d in snapshot),
            return_exceptions=True,
        )
        try:
            samples = await lat_task
        except Exception:
            samples = {}
        current = {c["id"]: c for c in devices_config.load_devices()}
        for config, result in zip(snapshot, results):
            if isinstance(result, Exception):
                logger.error("Probe fallito per %s: %r", config.get("ip"), result)
                continue
            self._apply(config, result, current, samples.get(config["id"]))
        for device_id in [i for i in self.devices if i not in current]:
            self.remove(device_id)
        await self._save_latency()
        try:
            arp = await arp_task  # gia' completata dai probe: nessuna nuova scansione
        except Exception:
            arp = {}
        await self.follow_ip_changes(arp)
        self.report_ip_conflicts()
        await self.check_new_devices(arp)
        self.ready.set()

    def report_ip_conflicts(self) -> None:
        """Avvisa una volta per ogni IP a cui rispondono MAC diversi (scanner.arp_conflicts)."""
        for ip, macs in scanner.arp_conflicts.items():
            key = (ip, tuple(macs))
            if key in self._conflicts_reported:
                continue
            self._conflicts_reported.add(key)
            self.emit_alert(f"IP duplicato {ip}: risponde da {', '.join(macs)}", "alert.ip_conflict", ip=ip, macs=", ".join(macs))

    async def follow_ip_changes(self, arp: dict[str, dict]) -> None:
        """Un dispositivo offline il cui MAC (gia' noto) risponde ora a UN solo altro
        IP non assegnato ad altri dispositivi ha cambiato indirizzo (DHCP): lo si segue
        invece di darlo per spento. Nessuna azione se i candidati sono ambigui."""
        if not arp:
            return
        by_mac: dict[str, list[str]] = {}
        for ip, host in arp.items():
            mac = newdevices.normalize_mac(host.get("mac"))
            if mac:
                by_mac.setdefault(mac, []).append(ip)
        configs = devices_config.load_devices()
        used = {c["ip"] for c in configs}
        for config in configs:
            device = self.devices.get(config["id"])
            mac = newdevices.normalize_mac(self._last_mac.get(config["id"]))
            if not device or device.get("online") or not mac or config["ip"] in arp:
                continue
            # Un MAC su piu' IP e' quello di un ripetitore Wi-Fi che "presta" il proprio
            # indirizzo ai client collegati a lui (MAC translation): non identifica un
            # dispositivo, quindi non si segue nulla.
            if len(by_mac.get(mac, [])) != 1:
                continue
            candidates = [ip for ip in by_mac[mac] if ip not in used]
            if len(candidates) != 1:
                continue
            new_ip = candidates[0]
            old_ip = await asyncio.to_thread(devices_config.update_ip, config["id"], new_ip)
            if old_ip is None:
                continue
            used.discard(old_ip)
            used.add(new_ip)
            self._misses[config["id"]] = 0
            label = device.get("name") or old_ip
            self.emit_alert(f"{label}: IP cambiato {old_ip} -> {new_ip}", "alert.ip_changed",
                            label=label, old=old_ip, new=new_ip)
            self.trigger()

    async def _save_latency(self) -> None:
        """Un campione medio al minuto per dispositivo, in una sola transazione."""
        rows = latency.tracker.take_minute()
        if not rows:
            return
        try:
            await asyncio.to_thread(history.record_latency, rows)
        except Exception:
            logger.exception("Salvataggio dello storico latenza fallito")

    # ---- nuovi dispositivi in rete ----
    def set_new_devices(self, devices: list[dict]) -> None:
        """Memorizza l'elenco dei 'new' ed emette l'evento solo se l'insieme
        dei MAC e' cambiato."""
        macs = frozenset(d["mac"] for d in devices)
        changed = macs != self._newdev_macs
        self._newdev_macs = macs
        if changed:
            self._emit(newdevices.event(devices))

    async def new_devices_event(self) -> dict:
        """Evento con l'elenco corrente (frame iniziale di api_events)."""
        devices = await asyncio.to_thread(newdevices.list_new)
        return newdevices.event(devices)

    async def check_new_devices(self, arp: dict[str, dict] | None = None) -> None:
        """Confronta i MAC visti (ARP gia' disponibile, nessuna nuova scansione)
        con quelli noti; avvisa per i mai visti."""
        if arp is None:
            arp = self._arp[1] if self._arp else {}
        async with self._newdev_lock:
            try:
                configs = devices_config.load_devices()
                configured_macs = {m for m in (newdevices.normalize_mac(d.get("mac")) for d in self.devices.values()) if m}
                skip_ips = {self._own_ip} if self._own_ip else set()
                if self._own_ip is None:
                    try:
                        _, self._own_ip = await netutil.get_local_network()
                        skip_ips = {self._own_ip}
                    except Exception:
                        pass
                observed = newdevices.observed_macs(arp, dhcp.seen, skip_ips)
                observed = {m: o for m, o in observed.items()
                            if not blocklist.matches(mac=m, ip=o["ip"], name=o["hostname"])}
                fresh, current = await asyncio.to_thread(
                    newdevices.evaluate, observed, {c["ip"] for c in configs}, configured_macs, newdevices.own_macs(),
                )
            except Exception:
                logger.exception("Controllo nuovi dispositivi fallito")
                return
            alerts_on = settings.alerts_enabled()
            for dev in fresh:
                label = newdevices.readable_label(dev)
                ip = dev["ip"] or "-"
                message = f"Nuovo dispositivo in rete: {label} ({ip}) MAC {dev['mac']}"
                if alerts_on:
                    self.emit_alert(message, "alert.new_device", label=label, ip=ip)
                else:
                    logger.info(message)
            self.set_new_devices(current)

    async def refresh_device(self, device_id: str, force: bool = False) -> None:
        """Aggiorna subito un solo dispositivo (dopo una modifica o una
        scansione), senza aspettare il prossimo ciclo."""
        all_configs = devices_config.load_devices()
        update_generic_titles(all_configs)
        config = next((c for c in all_configs if c["id"] == device_id), None)
        if config is None:
            self.remove(device_id)
            return
        arp_task = asyncio.create_task(self._arp_by_ip(ARP_MAX_AGE))
        result, sample = await asyncio.gather(
            probe.probe_device({**config, "last_mac": self._last_mac.get(device_id)}, arp_task),
            latency.measure(config["ip"], config.get("port", 80)),
        )
        current = {c["id"]: c for c in devices_config.load_devices()}
        self._apply(config, result, current, sample, force=force)

    async def _loop(self) -> None:
        while True:
            # clear all'inizio: un trigger arrivato durante il ciclo fa partire
            # subito il successivo invece di andare perso.
            self._wake.clear()
            if self.paused_remaining() is None or self._force:
                self._force = False
                try:
                    await self.poll_once()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Ciclo di aggiornamento fallito")
                    self.ready.set()
            else:
                self.ready.set()
            # Riletto a ogni ciclo: un cambio dalle Impostazioni vale subito
            # (l'API sveglia il ciclo con trigger()).
            interval = self._interval()
            left = self.paused_remaining()
            # In pausa si riparte appena finisce, non un intervallo dopo.
            wait = interval if left is None else min(interval, left + 0.2)
            self._next_at = time.monotonic() + wait
            self._emit(self.poll_info())
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass


state = DeviceState()
