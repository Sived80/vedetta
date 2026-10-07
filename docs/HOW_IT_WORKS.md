# How Vedetta works

What Vedetta is, what it does and how its search methods work. How it decides what a device is: [Recognition](RECOGNITION.md).

[← Back to the README](../README.md)

# Meet Vedetta

Your router lists *“android-7f3a…”* and *“Unknown device”*. Fing shows a brand and no reason. Home Assistant knows the
devices **you** set up, not the rest of your network.

**Vedetta is the lookout of your LAN.** It finds every device, works out *what it is* from many weak clues, and — this is
the part nobody does — **tells you why**. A name from a title page, a brand from a DHCP fingerprint, a PlayStation spotted
by the class it announces: every conclusion carries its evidence, and anything you set by hand is never overwritten.

Looking for a **network scanner for Home Assistant** that says *what* each device is, not just that it is online?
Vedetta is a Home Assistant **app** (not a custom integration): install it from the App store, no YAML, no cloud. It
works as a local **device discovery and identification** tool with presence and latency history, and it can share the
devices you choose with Home Assistant through MQTT.

It lives inside Home Assistant as an app (sidebar panel via ingress), reads Home Assistant’s own registry to learn the
names and rooms you already chose, and publishes back **only what you decide to share**.

> [!IMPORTANT]
> **Local-only.** No cloud, no accounts, no telemetry. See [Privacy & safety](PRIVACY.md).

# Features

| | |
|---|---|
| 🔭 **Three levels of search** | A light **ARP sweep** that only lists addresses; an **associative** scan of the devices you pick; a **deep** rescan (also nightly) with all ports and service detection, on everything or only on the devices not analysed in depth yet. Each method shows its risk with a colored dot — 🟢 non-intrusive, 🟠 intrusive, 🔴 risky — and you choose which ones run. |
| 🧠 **Real recognition** | Name, brand, model and category from ~15 independent sources, fused by family so one fact is never counted twice. Ambiguous? It stays in *Other* instead of guessing. |
| 🔎 **It explains itself** | A **debug view** shows every clue, its weight and where each name and brand came from. |
| 🏠 **Home Assistant aware** | Reads the device registry (read-only) for names, makers, models, areas and integrations; follows a rename made in HA. |
| 📤 **Share on demand** *(optional, needs [MQTT](MQTT.md))* | One button per device: **Share with HA** / **Remove from HA**. Shared devices appear as sub-devices of a single *Vedetta* device — never merged into your real ones. |
| 📱 **Remembers sleeping phones** | A passive Bonjour/DHCP listener remembers names when devices announce them, so a phone that sleeps keeps its name. |
| 📊 **Presence & latency** | Online/offline history (24 h / 7 days), response time, signal quality, uptime, open ports colored by category. |
| 🧭 **Network roles** | Detects gateway, DHCP and DNS servers, repeaters, access points, double NAT / CGNAT and your public IP. |
| 🛡️ **Careful by design** | Wake-on-LAN only where it makes sense, pause and resume, an ignore list, nothing written to your devices. |
| 🏷️ **Brand logos** | A faint logo of the recognized brand on each card and in the device sheet (in the circle, in list view). Logos ship with the app: no request to the Internet. A brand without a free logo shows none. |
| 🎨 **Home Assistant native look** | Same palette, light/dark, tiles or list, English and Italian, works in the mobile app. |
