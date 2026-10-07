<div align="center">

<img src="docs/images/banner.svg" alt="Vedetta — know every device on your network" width="100%">

<br>

<a href="docs/INSTALLATION.md"><img src="https://img.shields.io/badge/Home%20Assistant-OS%20%7C%20Supervised-03a9f4?style=for-the-badge&logo=homeassistant&logoColor=white" alt="Home Assistant" height="20"></a> <a href="vedetta/CHANGELOG.md"><img src="https://img.shields.io/badge/version-0.4.3-43a047?style=for-the-badge" alt="Version" height="20"></a> <a href="docs/PRIVACY.md"><img src="https://img.shields.io/badge/privacy-100%25%20local-ffa600?style=for-the-badge" alt="Privacy" height="20"></a> <a href="#what-it-does"><img src="https://img.shields.io/badge/UI-English%20%7C%20Italiano-7e57c2?style=for-the-badge" alt="Languages" height="20"></a> <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-607d8b?style=for-the-badge" alt="License" height="20"></a>

**[Install](docs/INSTALLATION.md) · [Screenshots](#what-is-vedetta) · [Features](#what-it-does) · [How it thinks](docs/RECOGNITION.md) · [Home Assistant](docs/HOME_ASSISTANT.md) · [Roadmap](docs/ROADMAP.md) · [Extend](docs/DEVELOPMENT.md)**

</div>

---

## What is Vedetta

**The lookout of your LAN.** Your router says *“Unknown device”*; Vedetta says *“Sony console”* and shows how it knew. It finds every device on your network, works out *what it is* from many weak clues, and **tells you why**. Anything you set by hand is never overwritten.

It is a Home Assistant **app** (not a custom integration): install it from the App store, no YAML, no cloud. It reads Home Assistant’s registry to learn the names and rooms you already chose, and publishes back **only what you decide to share**.

<p align="center"><img src="docs/images/hero.png" alt="Vedetta dashboard in tile and list view, light and dark theme, with the device detail sheet" width="100%"></p>

<p align="center"><sub>Tiles or list · light or dark · one tap to the evidence behind every name</sub></p>

## What it does

- 🔭 **Three levels of search**, each with its risk shown by a colored dot (🟢 non-intrusive, 🟠 intrusive, 🔴 risky): you choose which run.
- 🧠 **Real recognition**: name, brand, model and category from ~15 independent sources. Ambiguous? It stays in *Other* instead of guessing.
- 🔎 **It explains itself**: certainty bars and a debug view with every clue and its weight.
- 🏠 **Home Assistant aware**, with optional sharing through MQTT.
- 📱 **Remembers sleeping phones**, and recognizes phones with changing MAC addresses.
- 📊 **Presence and latency history**, network roles, brand logos, light/dark, English and Italian.

All the details: [How Vedetta works](docs/HOW_IT_WORKS.md).

## How it recognizes a device

<p align="center"><img src="docs/images/how-it-works.svg" alt="Ten weak clues are fused by family into name, brand, model, category and area; your own choice is never overwritten, and debug mode shows the reason" width="100%"></p>

Many weak clues (services, ports, names, DHCP and Bonjour announcements, the Home Assistant registry) are fused **by family**, so one fact is never counted twice. Placeholders are not names, doubt is shown as doubt, and the weights are public. Sources, weights and certainty bars: [Recognition](docs/RECOGNITION.md).

## Quick start

> [!IMPORTANT]
> ### ⏳ Give Vedetta a couple of days to settle
> Right after the install it only knows what it could see in the first minutes. **Most of what makes it good needs time**: phones sleep, names are announced now and then, and the presence history is what tells a phone with a changing MAC from a fixed device. A deep search also runs by itself every night at 03:00.
>
> Please **leave it installed and running for at least 24 hours (48 is better)** before you decide a device is wrong or open an issue, and press the deep search once. Why this matters, and what to do if a device is still wrong after a day: [Troubleshooting](docs/TROUBLESHOOTING.md).

> [!NOTE]
> Needs **Home Assistant OS** or **Supervised** (Settings shows **Apps**). Home Assistant *Container* or *Core* has no app store.

1. Add the repository with this button, or add `https://github.com/Sived80/vedetta` by hand in the App store:

   [![Add the Vedetta repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FSived80%2Fvedetta)
2. Search **Vedetta** in the App store and press **Install**.
3. Switch on **Show in sidebar** and press **Start**, then open **Vedetta** from the sidebar and press **Scan network**.

Two minutes to install, no cloud. Step by step, the local-app option and the first launch: [Installation](docs/INSTALLATION.md).

## Home Assistant and MQTT

Vedetta reads the Home Assistant registry **read-only**, and can publish chosen devices back through MQTT discovery. MQTT is optional and not part of a default Home Assistant installation; everything else works without it. See [Home Assistant](docs/HOME_ASSISTANT.md) and [MQTT](docs/MQTT.md).

## Privacy and safety

Everything runs **inside your network**, with no cloud, no accounts and no telemetry. Home Assistant access is read-only by construction. *Export for analysis* has two kinds: **for the developer** masks IPs, MACs, names and emails **before the file is created** and encrypts it, so it can be attached to a public issue; **for you** it is your own data, as it is. The encrypted export can be attached to a public issue (key fingerprint `84ba-bfcc-4706-163d`). Details and how to report a mistake: [Privacy and safety](docs/PRIVACY.md).

## Documentation

| Page | What it covers |
|---|---|
| [Installation](docs/INSTALLATION.md) | Both install options, first launch, updating, permissions |
| [How Vedetta works](docs/HOW_IT_WORKS.md) | What it is, features, search methods |
| [Recognition](docs/RECOGNITION.md) | Sources, weights, certainty bars, phones |
| [Home Assistant](docs/HOME_ASSISTANT.md) · [MQTT](docs/MQTT.md) | The two directions of the integration, MQTT setup |
| [Privacy and safety](docs/PRIVACY.md) | What stays local, exports, reporting a mistake |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | The first 24 hours, common problems |
| [Roadmap](docs/ROADMAP.md) | What is done, with date and version, and what is planned |
| [Development](docs/DEVELOPMENT.md) | Teach it a new device or logo, tests, stack |
| [Changelog](vedetta/CHANGELOG.md) | Every version |

## Project status

Vedetta is a one-person project made in spare time, public under the MIT license. It is at version **0.4.3** and under active development: what is built (each item with its date and version) and what is planned is in the [Roadmap](docs/ROADMAP.md). Found a device recognised wrongly? Use [the issue form](https://github.com/Sived80/vedetta/issues/new/choose) and attach the encrypted export.

## 📜 License and credits

Vedetta is open source under the **[MIT License](LICENSE)**. Everything it builds on is listed, with its license, in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

- 🧰 **Nmap** and **arp-scan** are installed from the Alpine package repository when the app is built on *your* Home
  Assistant. They are **not included** in this repository; Vedetta runs them as separate programs.
- 🏭 MAC vendor names come from the public **IEEE registries**; icons from **Material Design Icons** (Apache-2.0).
- ™️ Brand and product names are used only to describe the devices Vedetta recognizes. This project is not affiliated
  with or endorsed by any of them.

---

<div align="center"><sub>Built to be <b>explainable</b>. If it names something wrong, it will show its work — and you will always have the last word.</sub></div>
