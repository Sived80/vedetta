<div align="center">

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/radar-dark.svg"><img src="docs/images/radar-light.svg" alt="Vedetta: your router sees addresses, Vedetta sees devices. A radar finds and names the devices of every network and VLAN, and checks the health of the network" width="100%"></picture>

**The Home Assistant app that finds and follows every device on your network and your VLANs, and tells your phone when one goes away.**

<a href="docs/INSTALLATION.md"><img src="https://img.shields.io/badge/Home%20Assistant-OS%20%7C%20Supervised-03a9f4?style=for-the-badge&logo=homeassistant&logoColor=white" alt="Home Assistant" height="20"></a> <a href="vedetta/CHANGELOG.md"><img src="https://img.shields.io/badge/version-1.0.2-43a047?style=for-the-badge" alt="Version" height="20"></a> <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-607d8b?style=for-the-badge" alt="License" height="20"></a> <a href="https://scorecard.dev/viewer/?uri=github.com/Sived80/vedetta"><img src="https://api.scorecard.dev/projects/github.com/Sived80/vedetta/badge?style=for-the-badge" alt="OpenSSF Scorecard" height="20"></a> <a href="https://sived80.github.io/vedetta/"><img src="https://img.shields.io/badge/%F0%9F%8C%90%20Live%20Demo-try%20it%20in%20your%20browser-ff9800?style=for-the-badge" alt="Live Demo" height="20"></a>

<a href="docs/PRIVACY.md"><img src="docs/images/icon-no-cloud.svg" alt="No cloud" title="No cloud: everything stays in your home" width="96"><img src="docs/images/icon-no-accounts.svg" alt="No accounts" title="No accounts: nothing to sign up for" width="96"><img src="docs/images/icon-no-telemetry.svg" alt="No telemetry" title="No telemetry: nothing is sent out" width="96"><img src="docs/images/icon-read-only.svg" alt="Read-only access to Home Assistant" title="Read-only access to Home Assistant: it writes only when you turn on alerts" width="96"><img src="docs/images/icon-masked-exports.svg" alt="Exports masked before they are created" title="Exports masked before they are created" width="96"><img src="docs/images/icon-never-logs-in.svg" alt="Never logs in to your devices" title="Never logs in to your devices or tries a password; SNMP reads your router only with the community you write" width="96"></a>

</div>

## See it

<p align="center"><img src="docs/images/hero.png" alt="Vedetta dashboard on a computer in tile view, dark theme, with the phone list view in light theme in front of it" width="100%"></p>
<p align="center"><sub>Tiles or list · light or dark · computer or phone · <a href="https://sived80.github.io/vedetta/">Live demo</a>, 46 household devices, nothing to install</sub></p>

Also inside: sleeping phones remembered · each device's own web page, one tap away · three search levels, you choose the risk · your device list as CSV or JSON · Home Assistant events and optional MQTT. [How it works](docs/HOW_IT_WORKS.md)

## Tested

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/testing-numbers-dark.svg"><img src="docs/images/testing-numbers-light.svg" alt="400+ automatic tests, 4,000+ hours of real home networks, 150+ real devices, 30+ network scenarios" width="100%"></picture>

Real exports replayed and a virtual LAN, every release. Images built and signed on GitHub, checkable by anyone. [How](docs/TESTING.md)

## How it recognizes a device

Many weak clues, weighed together. A repeated fact counts once.

<p align="center"><img src="docs/images/how-it-works.svg" alt="Ten weak clues are fused by family into name, brand, model, category and area; your own choice is never overwritten, and debug mode shows the reason" width="100%"></p>

Sources, weights and certainty bars, all in the open: [Recognition](docs/RECOGNITION.md).

## What it does

**Every network, every VLAN.** The networks behind your router, tried before you add them, checked every 15 minutes.

**Your phone knows first.** When a device goes away, and when it is back. Never a "back" without a real "gone".

**30 days of memory.** Presence, link quality and the names each device had. The last 12 hours at a glance.

**It follows the device, not the address.** A new address or a new private MAC: still the same card.

**A doctor for your network.** Duplicate addresses, drops, restarts, a slow router.

**It watches, never touches.** It never logs in to a device and never tries a password.

And of course it names every device: name, brand, model and type, with every clue in the open. [How it recognizes a device](#how-it-recognizes-a-device)

## Install

> [!IMPORTANT]
> **Give it a day or two**: phones sleep and names are announced now and then. [Why](docs/TROUBLESHOOTING.md)

> [!NOTE]
> Needs **Home Assistant OS** or **Supervised**. *Container* and *Core* have no App store.

**1. Add** the repository, or add `https://github.com/Sived80/vedetta` by hand in the App store.<br>
<a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FSived80%2Fvedetta"><img src="docs/images/button-add.svg" alt="Add to my Home Assistant" height="40"></a>

**2. Install**: find **Vedetta** in the App store.<br>
**3. Start**: press **Start**, then **Scan network**. [Step by step](docs/INSTALLATION.md)

**A device is wrong or unknown?** Every report becomes a fix, and you can [teach it a device](docs/DEVELOPMENT.md).<br>
<a href="https://github.com/Sived80/vedetta/issues/new/choose"><img src="docs/images/button-report.svg" alt="Report a device" height="40"></a>

**Free and open source, and it stays that way.** A coffee keeps it going.<br>
<a href="https://ko-fi.com/B8D228NOWZ"><img src="docs/images/button-kofi.svg" alt="Support on Ko-fi" height="40"></a>

⭐ Names your devices right? A star helps others find it. *Watch › Custom › Releases* tells you about new versions.

## Automations

Turn on *Events in Home Assistant* (Menu → Alerts), then import a ready-made blueprint. Each event carries name, address, brand and type: [Home Assistant](docs/HOME_ASSISTANT.md).

**New device on the network**<br>
<a href="https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FSived80%2Fvedetta%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fvedetta%2Fnew_device.yaml"><img src="https://my.home-assistant.io/badges/blueprint_import.svg" alt="Import the new device blueprint"></a>

**Device went offline** (and back)<br>
<a href="https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FSived80%2Fvedetta%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fvedetta%2Fdevice_down.yaml"><img src="https://my.home-assistant.io/badges/blueprint_import.svg" alt="Import the device offline blueprint"></a>

## Docs

**Start** · [Installation](docs/INSTALLATION.md) · [How it works](docs/HOW_IT_WORKS.md) · [Troubleshooting](docs/TROUBLESHOOTING.md)<br>
**Inside** · [Recognition](docs/RECOGNITION.md) · [Networks and VLANs](docs/NETWORKS.md) · [Network doctor](docs/NETWORK_DOCTOR.md) · [Home Assistant](docs/HOME_ASSISTANT.md) · [MQTT](docs/MQTT.md)<br>
**About** · [Privacy](docs/PRIVACY.md) · [Roadmap](docs/ROADMAP.md) · [How it is tested](docs/TESTING.md) · [Development](docs/DEVELOPMENT.md) · [Changelog](vedetta/CHANGELOG.md)

## Your language?

English · Italiano · Deutsch · Čeština (thanks to the community). Adding yours takes no code: copy the `en` folder. [How](docs/DEVELOPMENT.md#add-a-language)

## License and credits

[MIT License](LICENSE). Everything it builds on, with its license: [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md). Nmap and arp-scan are installed from Alpine on your Home Assistant when the app starts, not shipped here. MAC vendors from the IEEE registries, icons from Material Design Icons. Brand names only describe devices; not affiliated with any of them.
