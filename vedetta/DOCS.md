# Vedetta

Vedetta finds the devices on your local network, recognizes them (name, brand, category), follows their presence
and latency, and shows them on a page in the Home Assistant sidebar (ingress: no port to open).
Nothing about your devices leaves your network. Three optional checks that reach the Internet can be switched off (see Options).

## How to use it

- **Network card** (top): the state of the network at a glance. A tile rotates between latency, gateway, Internet connection and what Vedetta knows. The search and **Scan network** are here too.
- **Devices found** open inside the Network card: add them to the board or ignore them.
- **Search** (magnifier): finds the IP and MAC addresses that are present. You pick the devices to add to the board.
- **Device card**: IP, MAC and ports are always visible; "More attributes" opens the rest (response time, brand, type, area...). The three-dots menu has **Customize card** (name, brand and type can be chosen by hand and are never changed again) and **Ignore**. **Share with HA** shows the device in Home Assistant (see below).
- **Deep search** (arrow next to "Scan network"): two tiles, **All** devices or only those **To analyse** (never analysed in depth). The orange badge on the arrow says how many they are, and it disappears when there are none. The search also starts by itself every night at 03:00, in the time zone of Home Assistant, for the devices never analysed or analysed more than 7 days ago.
- **Search methods** (menu): which methods the three searches use (initial, associative, deep). The dot shows the
  risk: green non-intrusive, orange intrusive, red risky.
- **Export for analysis** (menu, discreet item): builds a file with the configuration, the history and the reasons behind each name, brand and category, for the days you choose. It asks **who it is for**:
  - **For the developer**: a `.txt` with addresses and names masked, sealed so that only the author of Vedetta can open it. Up to 20 MB; safe to attach to a GitHub issue.
  - **For me**: a `.zip` that is not masked and not encrypted, to read yourself. Never post it in public.

  Nothing is sent anywhere. **Flag this device** (the flag in a device sheet) adds that card, its history and a short note to the report. Details: [Privacy and safety](https://github.com/Sived80/vedetta/blob/main/docs/PRIVACY.md).
- **Debug mode**: 3 consecutive taps on the title of the top card (or Ctrl+Shift+D). An orange DEBUG badge stays
  visible while it is on; the card shows the clues, scores and sources of name and brand.

## Options

- `log_level`: `debug`, `info`, `warning`, `error`.
- `interface`: network interface to scan (empty = automatic).
- `internet_public_ip`, `internet_path`, `internet_mac_database`: the three functions that reach the Internet. All are **on** by default; one that is off sends nothing, and the tile *Permissions* shows which are on.
  - Public IP: at start and every 6 hours, one DNS query to a public resolver asks for your public IP address.
  - Path: a traceroute to a public address (`internet_path_target`, empty = `1.1.1.1`) tells a direct connection from a double NAT.
  - Manufacturers: when the list is more than 30 days old, it is downloaded from the public IEEE registries.
- `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`: manual MQTT broker. When empty, the Home Assistant MQTT service (Mosquitto app) is used, if present.

The language is not an option: the page follows Home Assistant (`en`, `it`, `cs` or `de`), and each person can pick theirs in the menu (⋮).

## Permissions and what each one is for

| Permission | What it is for |
|---|---|
| Host network (`host_network`) and `NET_ADMIN`/`NET_RAW` | `arp-scan`, `nmap`, ping, SSDP/mDNS and passive DHCP listening (UDP port 67). Local requests only, never towards the Internet (except the three `internet_*` functions, which can be switched off). |
| `homeassistant_api` | **Read-only** access to the Home Assistant registries (devices, entities, areas, integrations) to give devices a name, brand, model, area and category. It writes nothing and calls no services. It can be turned off in the search methods ("Home Assistant data" step). |
| MQTT service (`mqtt:want`) | Publishes to Home Assistant only what you choose to share. |
| Ingress | The interface only accepts connections from the Supervisor. |

## Sharing with Home Assistant (MQTT)

By default Home Assistant sees a single device, **Vedetta**, with the counters (online, offline, mobile, new,
average latency) and the "Scan now" button. A network device appears in Home Assistant only if you press
**Share with HA** on its card: it becomes a sub-device of Vedetta with a tracker, connectivity and latency,
without merging into the real device that may already exist in Home Assistant. **Remove from HA** takes it
away. The button is disabled until MQTT is active. Availability is on `vedetta/status`.

## Brand logos

When the brand of a device is known and has a free logo, a faint logo appears on its card and in its sheet (in list view it
replaces the icon in the circle). Logos ship with the app, so nothing is requested from the Internet. The logo follows the
brand shown at that moment: if you change the brand by hand, or a new clue changes it, the logo changes too. Brands without
a logo (and chip makers such as Espressif) show none.

## Certainty bars

In a device sheet, the rows Name, Brand and Type have a thin certainty bar with its percentage and an (i): pressing it opens a small pop-up with what decided it and the hypotheses that were rejected (pressing outside closes it). A choice you made by hand is 100% and never changes. For the group, the bar is the lead of the best group over the second one weighted by how much evidence there is (a tie or too little evidence is 0% and the device stays in "Other devices"); for the brand, high when the MAC maker and the name agree or the device declares it; for the name, the weight of the source.

## When Vedetta is not sure

A card that Vedetta cannot name with confidence gets a lens on its icon, a clock while it is new and still settling, and a question mark after a week without an answer, with an invitation to name it or choose its type. The open card says why. This state never changes a type, a brand or a name, and sends nothing to the device.

## Phones that change address

A card that has used two or more different private MAC addresses counts as a phone or tablet. When two mobile cards have the same distinctive name (never a bare "iPhone" or the IP), at least one is online and they were never online together for more than 30 minutes, they are the same phone: the older card keeps your choices and the whole history, takes the address that answers and the other disappears. Nothing is merged when it is not clear.

## How it recognizes devices

Every source proposes a name or a clue and the most reliable one wins; a name you chose by hand is never changed.
The sources are: Home Assistant (a name chosen there), the device's own API, mDNS/Bonjour (with memory and
continuous listening), UPnP, DHCP (name and class), NetBIOS, TLS certificate, web page, network role. The category
adds up clues by family (the same fact does not count twice) and uses a catalog of product signatures
(`app/data/signatures.json`) where generic signals are ambiguous. If two categories are tied on weak clues the
device stays in "Other devices".

## Data and backups

Data lives in `/data` (devices, settings, DHCP and mDNS memory, history, log) and is included in Home Assistant
backups. **Uninstalling the app deletes `/data`**: use "Export for analysis" first if you want to keep a copy.

## After an update

The group of a device is **not stored**: it is worked out again, every time it is shown, from what Vedetta saved about the device (ports, services, names, DHCP class...). So when an update improves the rules, **every device you already have is re-evaluated at the first refresh after the restart**, with no new scan. What stays as it is: a name, brand, group or "phone" switch **you chose by hand** (it is never changed), and a name found earlier (it is only replaced by a better source). The only case that needs a new deep search is a rule that reads something Vedetta never saved for that device: the card's evidence then says there is no clue yet.

## Known limits

- **Give it 24 hours.** Right after the installation Vedetta only knows what it saw in the first minutes. Names, models and types arrive with time (phones that wake up, what devices announce, the presence history, the nightly deep search at 03:00). Wrong or empty results in the first hours are expected: leave it running for at least 24 hours (better 48) and run a deep search before reporting a device.

- Devices with a private MAC address (iPhone/iPad) do not always announce their name: they stay "brand mobile"
  until a name arrives from Bonjour, DHCP, Home Assistant or your own choice.
- A slow device (e.g. a console) is analysed with targeted ports first and, afterwards, in the background.
- Deep searches use CPU: on small machines avoid running them together with heavy loads.
