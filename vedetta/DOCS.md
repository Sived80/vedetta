# Vedetta

Vedetta finds the devices on your local network, recognizes them (name, brand, category), follows their presence
and latency, and shows them on a page in the Home Assistant sidebar (ingress: no port to open).
Everything stays at home: no data is sent outside your network.

## How to use it

- **Search** (magnifier): finds the IP and MAC addresses that are present. You pick the devices to add to the board.
- **Device card**: IP, MAC, response time and ports are always visible; "More attributes" opens the rest
  (brand, type, area...). Brand and type can be chosen by hand and are never changed again. The
  **Share with HA** button shows the device in Home Assistant (see below).
- **Deep search** (arrow next to "Scan network"): two items, "Deep search…" for all devices, or "Deep search: not
  yet analysed…" for only the devices never analysed in depth.
- **Search methods** (menu): which methods the three searches use (initial, associative, deep). The dot shows the
  risk: green non-intrusive, orange intrusive, red risky.
- **Export for analysis** (menu, discreet item): builds a file with the configuration, the history and the reason behind the name, brand and
  category of every device. **Before the file is created** IPs (the last number is kept), MAC addresses (the manufacturer prefix is kept)
  and names (`iPhone-1`, `TV-2`...) are masked, the same value always getting the same placeholder; emails become `email-1@masked.invalid`; passwords and tokens are excluded and nothing is
  sent anywhere. A final check looks for anything still readable and, if it finds something, nothing is exported. The table that tells which placeholder is which device stays on your machine (`/data/export_mapping.local`).
  - **Encrypted export** (the button): a `.txt` that only the author of Vedetta can open (it is sealed with the public key in
    `app/data/report_key.pub`). Attach it to a GitHub issue: it is safe even if the issue is public.
  - **Plain export** (the arrow): a `.zip` that is not encrypted, to read yourself or hand over privately. Never post it in public.
- **Debug mode**: 3 consecutive taps on the title of the top card (or Ctrl+Shift+D). An orange DEBUG badge stays
  visible while it is on; the card shows the clues, scores and sources of name and brand.

## Options

- `language`: default language (`en` or `it`); each browser can pick another one.
- `log_level`: `debug`, `info`, `warning`, `error`.
- `interface`: network interface to scan (empty = automatic, e.g. `enp0s18`).
- `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`: manual MQTT broker. When empty, the Home Assistant
  MQTT service (Mosquitto app) is used, if present.

## Permissions and what each one is for

| Permission | What it is for |
|---|---|
| Host network (`host_network`) and `NET_ADMIN`/`NET_RAW` | `arp-scan`, `nmap`, ping, SSDP/mDNS and passive DHCP listening (UDP port 67). Local requests only, never towards the Internet (except the periodic update of the MAC prefixes and the public IP check from the network panel). |
| `homeassistant_api` | **Read-only** access to the Home Assistant registries (devices, entities, areas, integrations) to give devices a name, brand, model, area and category. It writes nothing and calls no services. It can be turned off in the search methods ("Home Assistant data" step). |
| MQTT service (`mqtt:want`) | Publishes to Home Assistant only what you choose to share. |
| Ingress | The interface only accepts connections from the Supervisor. |

## Sharing with Home Assistant (MQTT)

By default Home Assistant sees a single device, **Vedetta**, with the counters (online, offline, mobile, new,
average latency) and the "Scan now" button. A network device appears in Home Assistant only if you press
**Share with HA** on its card: it becomes a sub-device of Vedetta with a tracker, connectivity and latency,
without merging into the real device that may already exist in Home Assistant. **Remove from HA** takes it
away. Availability is on `vedetta/status`.

## Brand logos

When the brand of a device is known and has a free logo, a faint logo appears on its card and in its sheet (in list view it
replaces the icon in the circle). Logos ship with the app, so nothing is requested from the Internet. The logo follows the
brand shown at that moment: if you change the brand by hand, or a new clue changes it, the logo changes too. Brands without
a logo (and chip makers such as Espressif) show none.

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

## Known limits

- Devices with a private MAC address (iPhone/iPad) do not always announce their name: they stay "brand mobile"
  until a name arrives from Bonjour, DHCP, Home Assistant or your own choice.
- A slow device (e.g. a console) is analysed with targeted ports first and, afterwards, in the background.
- Deep searches use CPU: on small machines avoid running them together with heavy loads.
