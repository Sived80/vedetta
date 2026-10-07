# Roadmap

What is built and released, and what is planned.

[← Back to the README](../README.md)

> [!NOTE]
> ✅ means it is built, tested and released. Next to it, the day and the version of the app in which it arrived. An empty box (☐) is planned.

## ✅ Done
- ✅ Runs as a Home Assistant app: sidebar panel, own data, backed up with Home Assistant — *02.10.2026 - V0.1.0*
- ✅ Names, brands, models and areas from the Home Assistant registry (read-only) — *05.10.2026 - V0.2.0*
- ✅ Share chosen devices with Home Assistant through MQTT, one button per device — *05.10.2026 - V0.2.0*
- ✅ Phones that sleep keep their name (Bonjour and DHCP memory) — *05.10.2026 - V0.2.1*
- ✅ Recognition by clue families, product signature catalog and a debug view that explains every decision — *05.10.2026 - V0.3.0*
- ✅ MAC vendor names generated from the public IEEE registries — *05.10.2026 - V0.3.0*
- ✅ Open source (MIT), public on GitHub, installable from the App store with one button — *05.10.2026 - V0.3.0*
- ✅ Deep search of only the devices never analysed in depth — *05.10.2026 - V0.3.1*
- ✅ A deep search that finds nothing is remembered, and what a device announced earlier is kept — *05.10.2026 - V0.3.3*
- ✅ Pause bar under the first card: orange and filling for a timed pause, solid red when stopped — *05.10.2026 - V0.3.4*
- ✅ "Open web interface" only where a real page answers — *05.10.2026 - V0.3.4*
- ✅ Response time through ARP when a device does not answer ping — *05.10.2026 - V0.3.4*
- ✅ Brand logos on cards, in the device sheet and in the list (58 brands) — *05.10.2026 - V0.3.5*
- ✅ Magic Home brand; the software on a device (Tasmota, ESPHome) wins over the maker of its hardware — *05.10.2026 - V0.3.5*
- ✅ Export for analysis with IPs, MACs, names and emails masked, and an encrypted report that can be attached to a public GitHub issue — *06.10.2026 - V0.3.7* (hardened in V0.3.8 and V0.3.9)
- ✅ Issue form "Device recognised wrongly", asking only for the encrypted export — *06.10.2026 - repository (no app update)*
- ✅ Certainty bars on name, brand and type, with a pop-up for the evidence and the rejected hypotheses — *06.10.2026 - V0.4.0*
- ✅ A badge on the arrow of the scan button says how many devices were never analysed in depth, and the deep-search menu has two tiles — *06.10.2026 - V0.4.0*
- ✅ The nightly maintenance (03:00) and the log use the time zone of Home Assistant — *06.10.2026 - V0.4.0*
- ✅ Phones with randomized (private) MAC addresses are recognised, and two cards of the same phone are merged — *06.10.2026 - V0.4.0*
- ✅ A Chromebook is a computer (not an Apple phone) and a Fairphone is a phone; both found by a user on GitHub — *06.10.2026 - V0.4.1*
- ✅ Sky boxes are Media and Amazon Echo devices are no longer Network equipment, read from a real export sent by a user — *06.10.2026 - V0.4.2*
- ✅ A device gets its best name: a brand and model name from DHCP (Xiaomi-14) beats an opaque label from mDNS (expiscor), also for devices already named — *06.10.2026 - V0.4.3*
- ✅ The export holds data per MAC address, to understand devices that share an IP address — *06.10.2026 - V0.4.3*
- ✅ New export window: for the developer or for me, choice of the days, progress steps, decisions on what cannot be masked — *07.10.2026 - V0.4.4*
- ✅ Flag a device for the report (card, evidence and history of that device in the export) — *07.10.2026 - V0.4.4*
- ✅ New card for the devices found: ring and tick per row, nothing moves when a button is pressed — *07.10.2026 - V0.4.4*
- ✅ Better group for devices that Home Assistant tracks or knows: a tracked client is no longer typed by the integration, the declared model beats a port banner, entities of unknown integrations count — *07.10.2026 - V0.4.5*
- ✅ External links: a page that answers 403 is not offered as a web interface; the link follows the open web port — *07.10.2026 - V0.4.5*
- ✅ The export leaves out only a file it cannot mask, and says which, instead of refusing everything — *06.10.2026 - V0.4.1*
- ✅ The export also holds the evidence of every device and the numbers behind "phone" (no addresses) — *06.10.2026 - V0.4.0*

## 🛡️ New devices and safety *(passive, no credential tests, nothing leaves your network)*
- [ ] Radar of new devices: "3 new since your last visit" with *it's mine / ignore*
- [ ] Clear-text services (telnet, FTP, SMB1) with severity per port
- [ ] Passive anomalies: second DHCP server, IP with two MACs, MAC that changes IP
- [ ] Device silent for days; IP changes and conflicts
- [ ] Every alert says why, what to do, and has *this is normal for me*
- [ ] Network health indicator with a public, explained formula
- [ ] TLS certificates close to expiry (self-signed shown as information only)
- [ ] UPnP / IGD: which devices have ports open to the Internet

## 🕰️ History
- [ ] Event timeline (arrivals, departures, IP and port changes)
- [ ] Before/after comparison between two scans, and "overnight" summary
- [ ] Time machine: snapshots and differences
- [ ] 90-bar status strips with latency sparklines
- [ ] Presence heatmap (7×24), local and opt-in only

## 📡 New local data sources
- [ ] Extended Home Assistant registry data (Zigbee, Matter, BLE: model, firmware, repeater, signal)
- [ ] Extended mDNS: IPP printers (model, toner), device info, HomeKit category, Matter/Thread
- [ ] Light labels: SSH/FTP/SMTP banners, favicon hash, ONVIF firmware and serial
- [ ] Passive listeners: LLDP, NetBIOS, WS-Discovery, IPv6 (NDP/DHCPv6)

## 🏠 Home Assistant
- [ ] `vedetta_new_device` event with brand, model and reason
- [ ] Native notification on a service you choose
- [ ] Ready-made blueprints (new device, critical device offline)
- [ ] More aggregate sensors (online, new today, unknown)
- [ ] Weekly digest notification
- [ ] "This device is also in HA as …" on the card
- [ ] Repairs and a custom integration *(later)*

## 🖼️ Views
- [ ] Per-room view from Home Assistant areas
- [ ] Topology map with certain links only *(later)*
- [ ] Screenshot mode (masks MAC and IP) and a first-run screen
- [ ] Compact Lovelace card *(later)*

## 💡 Original ideas
- [ ] Inventory export (CSV, JSON, Markdown) with an anonymize option
- [ ] Device identity card: first/last seen, notes, room, warranty
- [ ] "Ask Vedetta" with fixed Assist sentences, no language model
- [ ] "If this repeater drops, who disappears?"
- [ ] Offline, shareable signature packs *(later)*
