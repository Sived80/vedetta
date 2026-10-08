# Roadmap

What is built, release by release, and what is planned.

[← Back to the README](../README.md)

**Now: version 0.4.7**, released 7 October 2026. **31 things shipped** since the first release on 2 October, **33 planned**. Something you need sooner? [Open an issue](https://github.com/Sived80/vedetta/issues/new/choose) and say which: it moves it up.

## Release by release

| Version | Date | What came with it |
|---|---|---|
| **0.4.4 – 0.4.7** | 7 Oct | New export window · flag a device for the report · new card for the devices found · better groups for devices Home Assistant knows · external links only where a page answers |
| **0.4.0 – 0.4.3** | 6 Oct | Certainty bars with the evidence · badge for devices never searched in depth · phones with private MAC addresses · fixes from real exports (Chromebook, Fairphone, Sky, Echo) · best name wins |
| **0.3.7 – 0.3.9** | 6 Oct | Export for analysis: masked, encrypted, safe to attach to a public issue |
| **0.3.0 – 0.3.5** | 5 Oct | Recognition by clue families and a debug view · open source on GitHub · deep search · pause bar · response time through ARP · 58 brand logos |
| **0.2.0 – 0.2.1** | 5 Oct | Names and areas from the Home Assistant registry · sharing through MQTT · sleeping phones keep their name |
| **0.1.0** | 2 Oct | First release: a Home Assistant app with its own sidebar panel |

## Planned

A ☐ is an idea with a place, not a promise of a date: Vedetta is a one-person, spare-time project. Ordered by theme, not by priority.

<details>
<summary><b>🛡️ New devices and safety</b> · 8 · passive, no credential tests, nothing leaves your network</summary>

- ☐ Radar of new devices: "3 new since your last visit" with *it's mine / ignore*
- ☐ Clear-text services (telnet, FTP, SMB1) with severity per port
- ☐ Passive anomalies: second DHCP server, IP with two MACs, MAC that changes IP
- ☐ Device silent for days; IP changes and conflicts
- ☐ Every alert says why, what to do, and has *this is normal for me*
- ☐ Network health indicator with a public, explained formula
- ☐ TLS certificates close to expiry (self-signed shown as information only)
- ☐ UPnP / IGD: which devices have ports open to the Internet

</details>

<details>
<summary><b>🕰️ History</b> · 5</summary>

- ☐ Event timeline (arrivals, departures, IP and port changes)
- ☐ Before/after comparison between two scans, and "overnight" summary
- ☐ Time machine: snapshots and differences
- ☐ 90-bar status strips with latency sparklines
- ☐ Presence heatmap (7×24), local and opt-in only

</details>

<details>
<summary><b>📡 New local data sources</b> · 4</summary>

- ☐ Extended Home Assistant registry data (Zigbee, Matter, BLE: model, firmware, repeater, signal)
- ☐ Extended mDNS: IPP printers (model, toner), device info, HomeKit category, Matter/Thread
- ☐ Light labels: SSH/FTP/SMTP banners, favicon hash, ONVIF firmware and serial
- ☐ Passive listeners: LLDP, NetBIOS, WS-Discovery, IPv6 (NDP/DHCPv6)

</details>

<details>
<summary><b>🏠 Home Assistant</b> · 7</summary>

- ☐ `vedetta_new_device` event with brand, model and reason
- ☐ Native notification on a service you choose
- ☐ Ready-made blueprints (new device, critical device offline)
- ☐ More aggregate sensors (online, new today, unknown)
- ☐ Weekly digest notification
- ☐ "This device is also in HA as …" on the card
- ☐ Repairs and a custom integration *(later)*

</details>

<details>
<summary><b>🖼️ Views</b> · 4</summary>

- ☐ Per-room view from Home Assistant areas
- ☐ Topology map with certain links only *(later)*
- ☐ Screenshot mode (masks MAC and IP) and a first-run screen
- ☐ Compact Lovelace card *(later)*

</details>

<details>
<summary><b>💡 Original ideas</b> · 5</summary>

- ☐ Inventory export (CSV, JSON, Markdown) with an anonymize option
- ☐ Device identity card: first/last seen, notes, room, warranty
- ☐ "Ask Vedetta" with fixed Assist sentences, no language model
- ☐ "If this repeater drops, who disappears?"
- ☐ Offline, shareable signature packs *(later)*

</details>
