<div align="center">

<picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/radar-dark.svg"><img src="docs/images/radar-light.svg" alt="Vedetta: your router sees addresses, Vedetta sees devices. A radar finds and names the devices of every network and VLAN, and checks the health of the network" width="100%"></picture>

**A Home Assistant app that finds, names and follows every device on your network, and keeps an eye on its health.**

<a href="docs/INSTALLATION.md"><img src="https://img.shields.io/badge/Home%20Assistant-OS%20%7C%20Supervised-03a9f4?style=for-the-badge&logo=homeassistant&logoColor=white" alt="Home Assistant" height="20"></a> <a href="vedetta/CHANGELOG.md"><img src="https://img.shields.io/badge/version-0.13.2-43a047?style=for-the-badge" alt="Version" height="20"></a> <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-607d8b?style=for-the-badge" alt="License" height="20"></a> <a href="https://scorecard.dev/viewer/?uri=github.com/Sived80/vedetta"><img src="https://api.scorecard.dev/projects/github.com/Sived80/vedetta/badge?style=for-the-badge" alt="OpenSSF Scorecard" height="20"></a> <a href="https://sived80.github.io/vedetta/"><img src="https://img.shields.io/badge/%F0%9F%8C%90%20Live%20Demo-try%20it%20in%20your%20browser-ff9800?style=for-the-badge" alt="Live Demo" height="20"></a>

**[Live demo](https://sived80.github.io/vedetta/) · [Install](#install) · [What's new](vedetta/CHANGELOG.md) · [Docs](#docs)**

🌐 **[Live demo](https://sived80.github.io/vedetta/)**: 39 household devices in your browser, nothing to install.

<a href="docs/PRIVACY.md"><img src="docs/images/icon-no-cloud.svg" alt="No cloud" title="No cloud" width="96"><img src="docs/images/icon-no-accounts.svg" alt="No accounts" title="No accounts" width="96"><img src="docs/images/icon-no-telemetry.svg" alt="No telemetry" title="No telemetry" width="96"><img src="docs/images/icon-read-only.svg" alt="Read-only access to Home Assistant by default" title="Read-only access to Home Assistant by default: it writes only when you turn on alerts" width="96"><img src="docs/images/icon-masked-exports.svg" alt="Exports masked before they are created" title="Exports masked before they are created" width="96"><img src="docs/images/icon-never-logs-in.svg" alt="Never logs in to your devices" title="Never logs in to your devices or tries a password; SNMP reads your router only with the community you write" width="96"></a>

</div>

<table width="100%">
<tr><td width="33%"><b>Names every device</b><br>Name, brand, model, type. Your names are never overwritten.</td><td width="33%"><b>Follows it, not its address</b> · <i>new</i><br>A new address keeps the same card.</td><td width="33%"><b>Its own web page</b><br>One tap to the device's page.</td></tr>
<tr><td><b>Network doctor</b><br>Conflicts, drops, restarts, a slow router.</td><td><b>Every network and VLAN</b> · <i>new</i><br>What it sees on each, and how to see more.</td><td><b>Shows its work</b><br>Every clue behind a name. Doubt stays doubt.</td></tr>
</table>

## How it recognizes a device

Many weak clues, weighed together. A repeated fact counts once.

<p align="center"><img src="docs/images/how-it-works.svg" alt="Ten weak clues are fused by family into name, brand, model, category and area; your own choice is never overwritten, and debug mode shows the reason" width="100%"></p>

Sources, weights and certainty bars: [Recognition](docs/RECOGNITION.md).

## See it

<p align="center"><img src="docs/images/hero.png" alt="Vedetta dashboard on a computer in tile view, dark theme, with the phone list view in light theme in front of it" width="100%"></p>
<p align="center"><sub>Tiles or list · light or dark · computer or phone · <a href="https://sived80.github.io/vedetta/">Live demo</a></sub></p>

Also inside: sleeping phones remembered · presence and latency history · three search levels, you choose the risk · Home Assistant and optional MQTT. [How it works](docs/HOW_IT_WORKS.md)

## Install

1. **Add** the repository:<br><a href="https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FSived80%2Fvedetta"><img src="docs/images/button-add.svg" alt="Add to my Home Assistant" height="40"></a>
2. **Install**: find **Vedetta** in the App store.
3. **Start**: press **Start**, then **Scan network**.

Or add `https://github.com/Sived80/vedetta` by hand in the App store. [Step by step](docs/INSTALLATION.md)

> [!NOTE]
> Needs **Home Assistant OS** or **Supervised**. *Container* and *Core* have no App store.

> [!IMPORTANT]
> **Give it a day or two**: phones sleep and names are announced now and then. [Why](docs/TROUBLESHOOTING.md)

⭐ Names your devices right? A star helps others find it. *Watch › Custom › Releases* tells you about new versions.

<a href="https://github.com/Sived80/vedetta/issues/new/choose"><img src="docs/images/button-report.svg" alt="Report a device" height="40"></a><br>
A device is wrong or unknown? Every report becomes a fix. Want to do more? [Teach it a device](docs/DEVELOPMENT.md)

<a href="https://ko-fi.com/B8D228NOWZ"><img src="docs/images/button-kofi.svg" alt="Support on Ko-fi" height="40"></a><br>
Free and open source, and it stays that way.

## Tested

Real exports replayed and a virtual LAN, every release. [How](docs/TESTING.md)

## Docs

**Start** · [Installation](docs/INSTALLATION.md) · [How it works](docs/HOW_IT_WORKS.md) · [Troubleshooting](docs/TROUBLESHOOTING.md)<br>
**Inside** · [Recognition](docs/RECOGNITION.md) · [Networks and VLANs](docs/NETWORKS.md) · [Network doctor](docs/NETWORK_DOCTOR.md) · [Home Assistant](docs/HOME_ASSISTANT.md) · [MQTT](docs/MQTT.md)<br>
**About** · [Privacy](docs/PRIVACY.md) · [Roadmap](docs/ROADMAP.md) · [How it is tested](docs/TESTING.md) · [Development](docs/DEVELOPMENT.md) · [Changelog](vedetta/CHANGELOG.md)

## Your language?

English · Italiano · Deutsch · Čeština (thanks to the community). Adding yours takes no code: copy the `en` folder. [How](docs/DEVELOPMENT.md#add-a-language)

## License and credits

[MIT License](LICENSE). Everything it builds on, with its license: [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md). Nmap and arp-scan are installed from Alpine on your Home Assistant, not shipped here. MAC vendors from the IEEE registries, icons from Material Design Icons. Brand names only describe devices; not affiliated with any of them.
