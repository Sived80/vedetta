# Architecture — a map for someone opening the code for the first time

[← Back to the README](../README.md) · [Development](DEVELOPMENT.md) · [How it works](HOW_IT_WORKS.md)

This page is written to be read in ten minutes. The index at the end is generated from the code (the first sentence of each module's docstring), so it is always current.

## Start here

1. Read [`vedetta/app/main.py`](../vedetta/app/main.py): it starts everything (`lifespan`) and mounts the routes. Nothing imports it except the tests.
2. Read [`vedetta/app/state.py`](../vedetta/app/state.py): `DeviceState` keeps the card of every device and drives the periodic check; the work itself is in `state_cycle.py` and `state_support.py`.
3. Read [`vedetta/app/scan/probe.py`](../vedetta/app/scan/probe.py): `probe_device` builds the card of ONE device. Names, web addresses and the pipeline of a deep search are in `probe_names.py`, `probe_web.py` and `pipeline.py`.
4. Recognition is **data**: `vedetta/app/data/*.json` (signatures, brands, device kinds). Teaching it a new device usually needs no code (see [Development](DEVELOPMENT.md)).

## The rule of the layers

A module may import from its own layer or from a lower one, never from a higher one. `tests/check_structure.py` enforces it (and forbids import cycles), so the dependencies always point down:

- **layer 0**: `applog`, `assets`, `atomic`, `cyclestats`, `datafile`, `eventbus`, `formatters`, `iface`, `netutil`, `paths`, `procfs`, `sse`
- **layer 1**: `i18n`, `lifecycle`, `macclassify`, `macidentity`, `maclayer`, `pause`, `storage/`
- **layer 2**: `analysis/`, `recognition/`, `topology/`
- **layer 3**: `scan/`
- **layer 4**: `arpview`, `ha/`, `identity_upkeep`, `maintenance`, `newdevicewatch`, `state_cycle`, `state_support`, `state`
- **layer 5**: `export/`
- **layer 6**: `ingress`, `routes/`
- **layer 7**: `main`

A few modules sit at another layer than their folder (for example `scan/dhcp.py` and `scan/mdns_listener.py` are base modules that import only the standard library); they are listed by name in `tests/check_structure.py`.

`main` is the top: it wires the routes and starts the service. Routes call everything below them and nothing but `main` calls a route.

## How one check of the network flows

1. `main.lifespan` starts the background work: it loads the history, starts the state loop, the nightly maintenance, the DHCP listener, the Home Assistant registry reader, the Bonjour listener, MQTT and the network-role watcher.
2. Every cycle `state_cycle.poll_once` loads the saved devices (`devices.yaml`), starts the ARP view and a response-time measurement, and asks `probe.probe_device` about every device in parallel.
3. `probe_device` asks the device's adapter (is it online?), adds what the earlier searches saved (`scan_info`), what Bonjour and DHCP remember and what Home Assistant knows, and decides the name, the brand and whether it is a phone. It returns one record; it only reads, it never changes anything on the network.
4. `state_cycle.settle` decides online or offline (a missed check is tolerated for a while), and `state_cycle.publish` stores the card and emits an event only if the card changed; the browsers receive it through server-sent events (see `sse.py`).
5. After the cycle: changed addresses are followed, duplicate phones merged, address conflicts reported, new devices announced, and the MAC layer (`maclayer.py`) records which MAC answered at which address. The MAC layer only records: nothing reads it yet.
6. A **deep search** (the button, or the night) is `scan/rescan.py`: it runs the deep profile of `pipeline.py` (ports, services, names, certificates), saves the result with its history, warns about ports that opened or closed, and applies a better name if one was found.

## Where to change what

| I want to… | Look at |
|---|---|
| teach it a device or a brand | `vedetta/app/data/signatures.json`, `brands.json`; the tests check it |
| change how a name or a brand is chosen | `scan/probe_names.py`, `recognition/naming.py`, `recognition/identity.py` |
| add or change a page of the web interface | `vedetta/app/frontend/` (ES modules in `js/`, the style in parts joined by `assets.py`), `routes/ha.py` |
| add an API route | `routes/` (one module per theme), wired in `main.py` |
| add or change a step of the search | `scan/flows.py` and `scan/pipeline_plan.py` (which steps run), `scan/pipeline_probes.py` (what each one does) |
| change what is exported for analysis | `export/` (`export_engine.py` is the entry, `anonymize.py` hides the personal data) |
| change what is saved | `storage/` (`history*.py` is the SQLite database, `devices_config.py` the device list) |

## Safety net

The functions that were restructured have a reference test that was generated from the code *before* the change (`tests/check_*_golden.py`, files in `tests/golden/`), so a change that alters their behaviour fails a test. `python tools/gate.py` runs all of them plus the complexity and structure checks. `python tools/readability.py` measures how easy the code is to read.

## Index of the modules

### (top level)

| module | what it is for |
|---|---|
| `applog.py` | The service's own log: a rotating file in the data folder (dashboard.log) and a short in-memory list of the latest entries, which the log page and the export read. |
| `arpview.py` | The view of the network that ARP gives: who answers at which address and with which MAC. |
| `assets.py` | The front-end of the /ha page, kept in several files. |
| `atomic.py` | The atomic write of a file: a temporary file in the same folder, then os.replace. |
| `cyclestats.py` | How the check cycles go: a line in the log only when something is wrong (cycles chained by events, a slow cycle) and one summary an hour. |
| `datafile.py` | Reading of the JSON files shipped with the app (app/data/*.json: kinds of device, Home Assistant integrations, brand logos, product signatures). |
| `eventbus.py` | Delivery of events to the open browsers (and the MQTT bridge): who is listening, and a bounded queue for each. |
| `formatters.py` | Small text and number formatting shared by the whole app: the length limit of a device name, which web page titles are worth showing (and which are noise), uptime rounded for display, and the quality labels of a Wi-Fi signal and of a LAN link speed. |
| `i18n.py` | Internationalization: one folder per language in app/locales/<code>/ with one or more flat JSON files key -> text (server.json for the templates and Python, js.json for the browser). |
| `identity_upkeep.py` | Upkeep of the identity of the cards: what to do when the same device shows up with another address or another card. |
| `iface.py` | LAN network interface: from VEDETTA_IFACE, otherwise from the default routing (/proc/net/route, no external command: it also works with BusyBox). |
| `ingress.py` | Home Assistant ingress support (add-on). |
| `lifecycle.py` | Why did the service restart? A small record of the run (tests/check_lifecycle.py): when it started, a heartbeat (time, memory, the longest delay of the event loop) and a mark when it stops cleanly. |
| `macclassify.py` | Single MAC layer, phase 2: what kind of MAC is this? Pure functions over the rows of ip_mac (no network, no database, no brand). |
| `macidentity.py` | Single MAC layer, phase 3: are two MACs the same physical device? Probabilistic record linkage (Fellegi-Sunter), pure functions, no brand. |
| `maclayer.py` | The single MAC layer, phase 1: what the network says about which MAC answers at which address, as plain observations. |
| `main.py` | Entry point of the service: creates the FastAPI app, starts and stops the background work in the lifespan, and mounts the routes that live in routes/. |
| `maintenance.py` | Night-time maintenance of the service: at night (the hour follows the Home Assistant time zone) it runs the deep search again on the devices that were never analysed or not for a long time, and refreshes the table of manufacturer prefixes. |
| `netutil.py` | Network helpers: the local network of the host (get_local_network: subnet and own address, on the interface chosen in iface) and filter_local_ips, which keeps only the addresses that belong to that network. |
| `newdevicewatch.py` | Watch for MACs never seen on the network: compares what ARP and DHCP show with the known ones and warns once for each new one. |
| `paths.py` | Data paths and environment parameters: a single source of truth. |
| `pause.py` | Pause of the periodic check: when it ends, how long it was, and its survival to a service restart (pause.json). |
| `procfs.py` | Tolerant, lazy reading of the text tables the kernel exposes (/proc/net/route, /proc/net/arp, /proc/self/status). |
| `sse.py` | sse: moved out of main.py (see tools/split_module.py). |
| `state.py` | The shared state of the service: DeviceState keeps the card of every device and drives the periodic check. |
| `state_cycle.py` | The periodic check of DeviceState and its decisions: one cycle (probes, response times and the network table together, the results applied, what is gone forgotten, the housekeeping that follows), the loop that repeats it, and the online/offline decision of a checked device (settle, publish). |
| `state_support.py` | What DeviceState keeps and reports besides the cards, in four small parts: the activities in progress (scans and searches, kept here and not only in the browser that started them, so that after changing page the blinking LED and the search button are found as they were), who is online (presence), the MAC shadow jobs, and the numbers of the diagnostics for the export. |

### analysis/

| module | what it is for |
|---|---|
| `analysis/badges.py` | The badges of a card's icon. |
| `analysis/status.py` | Is a device identified, settling or under analysis? Phase 1: read-only, from the evidence card the app already builds (recognition/evidence.py); it sends nothing. |

### export/

| module | what it is for |
|---|---|
| `export/anonymize.py` | Anonymisation of the export for analysis: only the copy inside the zip changes, never the live data. |
| `export/anonymize_audit.py` | AuditMixin: methods of Anonymizer that belong together (moved out of anonymize.py by tools/split_class.py). |
| `export/anonymize_patterns.py` | anonymize_patterns: moved out of anonymize.py (see tools/split_module.py). |
| `export/anonymize_registry.py` | anonymize_registry: the part of the Anonymizer that knows the real values (addresses, MACs, names, areas) and gives each one its placeholder. |
| `export/export_analysis.py` | export_analysis: build the enriched analysis state (state/analysis.json) for diagnosis and privacy. |
| `export/export_db.py` | export_db: how the export walks the text stored in a copy of the history database - every table, every column, every distinct text value - and masks it in place. |
| `export/export_engine.py` | The export for analysis, in two phases and for two readers. |
| `export/export_estimate.py` | export_estimate: moved out of export_engine.py (see tools/split_module.py). |
| `export/export_gather.py` | export_gather: moved out of export_engine.py (see tools/split_module.py). |
| `export/export_jobs.py` | The export of the window, as a job the window follows step by step: it is started, polled (which steps are done, what the check found), the person decides what could not be fixed, and the file is taken once. |
| `export/export_mask.py` | export_mask: moved out of export_engine.py (see tools/split_module.py). |
| `export/export_zip.py` | Export for analysis: a zip file with the data needed to understand why a name, a brand or a category is wrong. |
| `export/mac_shadow.py` | Shadow data per MAC: collected for analysis only, nothing here decides what a card shows. |
| `export/report_crypto.py` | Encrypted report: the zip is sealed with the maintainer's public key (data/report_key.pub). |

### ha/

| module | what it is for |
|---|---|
| `ha/analysis_view.py` | The state of every card (identified, settling, analysing) for the page. |
| `ha/device_debug.py` | What debug mode shows for a device: the clues that decided its group, the candidates for its name, brand, mobile score, DHCP, roles, scan data and the registry/mDNS memory. |
| `ha/ha_data.py` | Data for the Home Assistant-style dashboard (/ha): inferred device type, compact format for the UI, summary, event log. |
| `ha/ha_registry.py` | Home Assistant registry as a source of name, brand, model and area of the network devices. |
| `ha/ha_type_evidence.py` | ha_type_evidence: moved out of ha_data.py (see tools/split_module.py). |
| `ha/ha_type_text.py` | ha_type_text: moved out of ha_type_evidence.py (see tools/split_module.py). |
| `ha/ha_tz.py` | Time zone (and language) of Home Assistant. |
| `ha/ha_update.py` | Whether Home Assistant has a newer version of this add-on: the red dot on the menu button and the arrow in the menu. |
| `ha/identity_shift.py` | Who is behind a card: two different devices answering at the same address. |
| `ha/mqtt_config.py` | mqtt_config: moved out of mqtt_ha.py (see tools/split_module.py). |
| `ha/mqtt_ha.py` | Publishes Vedetta's state over MQTT using Home Assistant's "device" discovery (homeassistant/device/<id>/config). |
| `ha/mqtt_payloads.py` | mqtt_payloads: moved out of mqtt_ha.py (see tools/split_module.py). |

### recognition/

| module | what it is for |
|---|---|
| `recognition/brand_logo.py` | Logo of a brand, for the cards, the list and the device sheet. |
| `recognition/brands.py` | Device brands. |
| `recognition/evidence.py` | Evidence card: for a device, what decided its name, brand and group, how sure the app is (0-100) and which other hypotheses it rejected. |
| `recognition/identity.py` | Identity of a device in a single place: product brand, "mobile" and battery. |
| `recognition/naming.py` | Device names. |
| `recognition/oui_update.py` | Update of the MAC prefix database from the public IEEE registries (MA-L 24 bit, MA-M 28 bit, MA-S 36 bit and the old IABs, 36 bit). |
| `recognition/roles.py` | Who does what on the network: gateway, DHCP server, DNS server, router, access point, Wi-Fi repeater, and which clients go through a repeater. |
| `recognition/signatures.py` | Catalog of declarative product signatures (app/data/signatures.json). |
| `recognition/twins.py` | Twin cards: cards that look the same (same name, brand and type), like five Shelly called by their model. |
| `recognition/vendor_lookup.py` | Who made a network card, from its MAC address: the IEEE registry (a copy downloaded into the data folder wins over the one shipped with the app), private (random) addresses, and the brand and vendor resolution that the device cards use. |

### routes/

| module | what it is for |
|---|---|
| `routes/bodies.py` | The body of a modifying request: a JSON dictionary or a 400, in one place (a body that was a list, a string or not JSON used to give a 500 with a traceback in the log). |
| `routes/brands.py` | Brand recognition API: rules created from the interface and update of the MAC prefix database from the web. |
| `routes/device_routes.py` | device_routes: moved out of main.py (see tools/split_module.py). |
| `routes/export_routes.py` | The export of the data for analysis (/api/export*): the file in one go, the estimate of the window, and the export as a job that is followed step by step and whose file is taken once. |
| `routes/flows.py` | API of the search flows: which functions (steps) each profile enables. |
| `routes/ha.py` | Home Assistant-style dashboard (/ha) and its JSON APIs (/api/ha/*). |
| `routes/ignored.py` | API of the ignored devices. |
| `routes/mqtt.py` | Status and configuration API for MQTT publishing (GET/POST /api/mqtt). |
| `routes/scan_routes.py` | scan_routes: moved out of main.py (see tools/split_module.py). |
| `routes/settings_routes.py` | settings_routes: moved out of main.py (see tools/split_module.py). |

### scan/

| module | what it is for |
|---|---|
| `scan/adapters/generic.py` | Generic adapter: asks a device whether it answers on a TCP port, with no knowledge of any make. |
| `scan/adapters/shelly_gen1.py` | Adapter for first-generation Shelly devices: reads /status and /settings over HTTP and returns what the device reports about itself. |
| `scan/adapters/shelly_gen2.py` | Second-generation Shelly devices (RPC API): tells whether the device runs on a battery, from the "devicepower:0" component of Shelly.GetStatus. |
| `scan/arpplan.py` | Which addresses the periodic check asks over ARP. |
| `scan/dhcp.py` | Passive DHCP listening: clients (phones included) broadcast their own name (option 12), the list of requested parameters (option 55, which has a characteristic order for each operating system - the principle behind Fingerbank fingerprints) and the vendor class (option 60) when they join the network or ask for a lease. |
| `scan/discovery.py` | Self-declaration protocols not covered by nmap/zeroconf, in pure Python. |
| `scan/flows.py` | Registry of the functions (steps) and profiles (sub-flows) of the search. |
| `scan/internet.py` | Outbound internet connectivity: public IP, double NAT, provider CGNAT. |
| `scan/latency.py` | Device response time, measured in the same check cycle. |
| `scan/localapi.py` | Documented local interfaces of the manufacturers, read-only and without credentials. |
| `scan/mdns_browsing.py` | The DNS-SD browsing shared by the search (scan_mdns) and by the continuous listener (mdns_listener): a browser that asks for the service types, one for every type seen, and the reading (SRV, TXT, A) of every instance that is announced. |
| `scan/mdns_listener.py` | Memory and continuous listening of Bonjour (mDNS) names, like the DHCP memory. |
| `scan/mdns_parse.py` | mdns_parse: moved out of scan_mdns.py (see tools/split_module.py). |
| `scan/pipeline.py` | Single search flow: independent functions (steps) enabled by profiles. |
| `scan/pipeline_plan.py` | pipeline_plan: moved out of pipeline.py (see tools/split_module.py). |
| `scan/pipeline_probes.py` | pipeline_probes: moved out of pipeline.py (see tools/split_module.py). |
| `scan/probe.py` | Builds the card of ONE device (probe_device): asks its adapter, adds what the search, Bonjour, DHCP and Home Assistant know, decides name, brand and "mobile", and returns a single record. |
| `scan/probe_names.py` | probe_names: moved out of probe.py (see tools/split_module.py). |
| `scan/probe_record.py` | probe_record: the records that the stages of probe_device pass to each other (what is known about the device, how it is reached, the brand stage, the name, the product) and the builder of the final card record. |
| `scan/probe_web.py` | probe_web: moved out of probe.py (see tools/split_module.py). |
| `scan/rescan.py` | Deep search of one device (rescan_device): runs the deep profile, saves the result and its history, compares the open ports with the previous scan and warns about the ones that changed, applies a better name, and for a slow device schedules the full port scan in the background (rescan_background.py). |
| `scan/rescan_background.py` | The full port scan of a slow device, in the BACKGROUND (schedule_full_ports): the deep search (rescan.py) covers only the targeted ports of such a device; this one runs afterwards, at a cautious pace and one at a time, adds the extra ports and reads their services. |
| `scan/scan_arp.py` | scan_arp: moved out of scanner.py (see tools/split_module.py). |
| `scan/scan_cert.py` | scan_cert: moved out of scanner.py (see tools/split_module.py). |
| `scan/scan_common.py` | scan_common: moved out of scanner.py (see tools/split_module.py). |
| `scan/scan_format.py` | scan_format: moved out of scanner.py (see tools/split_module.py). |
| `scan/scan_mdns.py` | scan_mdns: moved out of scanner.py (see tools/split_module.py). |
| `scan/scan_nmap.py` | scan_nmap: moved out of scanner.py (see tools/split_module.py). |
| `scan/scan_protocols.py` | scan_protocols: moved out of scanner.py (see tools/split_module.py). |
| `scan/scan_web.py` | scan_web: moved out of scanner.py (see tools/split_module.py). |
| `scan/scanner.py` | Front door of the network scans: it only re-exports what scan_common, scan_arp, scan_mdns, scan_cert, scan_nmap, scan_protocols, scan_web and scan_format define, so callers and tests keep writing scanner.name. |
| `scan/touch_policy.py` | The touch policy: how much a device is contacted. |
| `scan/wol.py` | Wake-on-LAN: standard magic packet (6 bytes of 0xFF + 16 repetitions of the MAC = 102 bytes) sent as a UDP broadcast. |

### storage/

| module | what it is for |
|---|---|
| `storage/blocklist.py` | Ignored devices: they do not appear in searches nor in new-device alerts. |
| `storage/devices_config.py` | The list of monitored devices, saved in devices.yaml: load, add, update, set by hand (override), change of address, automatic name, scan info, remove. |
| `storage/history.py` | The database of the service (vedetta.db, SQLite): presence history, scans, known devices, the memory of MAC addresses and the MAC layer. |
| `storage/history_known.py` | KnownMixin: methods of History that belong together (moved out of history.py by tools/split_class.py). |
| `storage/history_maclayer.py` | MacLayerMixin: the tables of the single MAC layer (moved out of history.py's class by design, see maclayer.py). |
| `storage/history_macs.py` | MacMemoryMixin: methods of History that belong together (moved out of history.py by tools/split_class.py). |
| `storage/history_presence.py` | PresenceMixin: methods of History that belong together (moved out of history.py by tools/split_class.py). |
| `storage/history_scans.py` | ScansMixin: methods of History that belong together (moved out of history.py by tools/split_class.py). |
| `storage/journal.py` | Event log beyond online/offline, for the level-based Log of /ha. |
| `storage/newdevices.py` | New devices on the network: compares the MACs seen via ARP (and DHCP) with the already known ones, stored in the known_macs table of the SQLite history. |
| `storage/overlap.py` | Time overlap of presence sessions, to tell a MAC lent to several cards (shared) from one phone that moved to a new address (not shared). |
| `storage/settings.py` | User settings (config/settings.json): "alerts" = show the alerts (new open port, new device...); "poll_interval" = seconds between one check and the next (fixed values). |
| `storage/starhint.py` | The one-time invitation to star the project on GitHub (config/star_hint.json). |
| `storage/userlang.py` | The language each Home Assistant user chose in the menu (config/user_lang.json). |

### topology/

| module | what it is for |
|---|---|
| `topology/edges.py` | The links «this card is behind that repeater» which the data already prove (topology, phase T0). |
| `topology/graph.py` | Topology, phase T1 (read-only): the links of every source put together. |

### frontend/ha (the page /ha)

The files of `js/` are ES modules: the page loads `js/app.js` and the browser follows the imports; each module imports what it uses of the others and exports what the others use, and `core.js` is the base (it imports nothing). `css/` is joined in name order into ha.css by `assets.py`.

| part | lines | what it is for |
|---|---|---|
| `js/app.js` | 43 | Log open: reloads by itself (more often at the detailed level, where |
| `js/core-menu.js` | 299 | guided typing |
| `js/core-ui.js` | 199 | state |
| `js/core.js` | 225 | Vedetta in Home Assistant style (/ha). Vanilla JavaScript, no libraries. |
| `js/debug.js` | 47 | Origin and reliability of brand and name: data for analysis, not for the user. Enabled with |
| `js/deep.js` | 158 | deep search |
| `js/export.js` | 253 | export for analysis |
| `js/filters.js` | 239 | filters |
| `js/flows.js` | 141 | search methods (flows) |
| `js/ignored.js` | 332 | ignored devices |
| `js/live.js` | 249 | update |
| `js/log.js` | 166 | log |
| `js/more-attrs.js` | 183 | Always visible: IP, MAC, response time, ports. The rest is in the "Other attributes" dropdown. |
| `js/more-edit.js` | 275 | Flag the device for the report: its card, history and this note go in the export for analysis. |
| `js/more-evidence.js` | 133 | Evidence on the rows Name, Brand and Type: a thin bar and the certainty next to the (i) that opens a small pop-up with |
| `js/more-graph.js` | 137 | History chart: a single segmented band (online / offline / no data) |
| `js/more-info.js` | 95 | "More info" dialog |
| `js/net-gauge.js` | 106 | "living cycle" circle |
| `js/net-icons.js` | 23 | Icons of the Network card that have a part of their own to animate (the CSS turns the marked group around the centre of the 24 px box). |
| `js/net-rotator.js` | 185 | rotating tile of the Network card |
| `js/network.js` | 59 | pause |
| `js/new-devices.js` | 320 | new devices |
| `js/pause-place.js` | 14 | Where the pause menu goes: a pure function (nothing here touches the page, so a test can feed it any measure). |
| `js/tile.js` | 308 | tile |
| `js/update.js` | 34 | update available |
| `css/10-base.css` | 166 | Vedetta styled like Home Assistant (/ha). Variables use the same NAMES as the HA frontend, so the page in an |
| `css/11-components.css` | 183 | components |
| `css/12-motion.css` | 173 | motion |
| `css/20-export.css` | 94 | Export dialog (#exportdlg, xp-*). |
| `css/30-deep.css` | 50 | Deep search: the menu of #deep-menu, its rows and the badge on the split button. |
| `css/40-network.css` | 489 | Network card: header with the logo, "living cycle" circle, split scan button, search row with the rotating tile, filter badges, |
| `css/50-tile.css` | 196 | Device tiles: groups, tiles, compact rows, empty state with the scan button, list view, brand logos. |
| `css/60-new-devices.css` | 92 | Devices found panel (#card-new, inside the network card). Its .nd-list/.nd-row/.nd-ic/.nd-text/.nd-actions rows are reused by the #ignored d |
| `css/65-update.css` | 17 | Update window (#updatedlg): what is going to happen before the Updates page of Home Assistant opens. The frame, the header with the X on the |
| `css/70-log.css` | 54 | Log card (#card-log). .log-empty is reused by the #ignored dialog (network). |
| `css/80-more-info.css` | 253 | More info dialog (#more): hero, history, attributes, ports, rename and flag forms, type menu, debug rows. |

