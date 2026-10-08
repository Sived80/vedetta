<div align="center">

<img src="docs/images/banner.svg" alt="Vedetta — know every device on your network" width="100%">

# Your router says “Unknown device”.<br>Vedetta tells you what it is — and shows you why.

**A Home Assistant app that finds the devices on your LAN, works out what each one is, and shows the evidence.**

<a href="docs/PRIVACY.md"><img src="docs/images/icon-no-cloud.svg" alt="No cloud" title="No cloud" width="96"><img src="docs/images/icon-no-accounts.svg" alt="No accounts" title="No accounts" width="96"><img src="docs/images/icon-no-telemetry.svg" alt="No telemetry" title="No telemetry" width="96"><img src="docs/images/icon-read-only.svg" alt="Read-only access to Home Assistant" title="Read-only access to Home Assistant" width="96"><img src="docs/images/icon-masked-exports.svg" alt="Exports masked before they are created" title="Exports masked before they are created" width="96"><img src="docs/images/icon-open-source.svg" alt="Open source (MIT)" title="Open source (MIT)" width="96"></a>

<a href="docs/INSTALLATION.md"><img src="https://img.shields.io/badge/Home%20Assistant-OS%20%7C%20Supervised-03a9f4?style=for-the-badge&logo=homeassistant&logoColor=white" alt="Home Assistant" height="20"></a> <a href="vedetta/CHANGELOG.md"><img src="https://img.shields.io/badge/version-0.4.7-43a047?style=for-the-badge" alt="Version" height="20"></a> <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-607d8b?style=for-the-badge" alt="License" height="20"></a>

**[Install in 2 minutes](#install) · [How it explains itself](#show-your-work) · [Report a device](https://github.com/Sived80/vedetta/issues/new/choose) · [Docs](#documentation) · [Roadmap](docs/ROADMAP.md)**

</div>

<p align="center"><img src="docs/images/demo.gif" alt="An unknown device on the network becomes a Sony console after a scan, and its card shows the clues that decided it" width="100%"></p>
<p align="center"><sub>An unknown device, a scan, a name — and the clues behind it</sub></p>

<p align="center"><picture><source media="(prefers-color-scheme: dark)" srcset="docs/images/group-dark.png"><img src="docs/images/group-light.png" alt="A group of devices on the dashboard: the Sony console, recognized, with its logo and brand" width="100%"></picture></p>

---

## What is Vedetta

You have a few dozen devices on your network. Your router lists their IP addresses and, if you are lucky, a name like `Android_7F3A` or “Unknown device”. Home Assistant knows some of them. The rest are a guess.

Vedetta is the lookout of your LAN. It does three things, in this order:

| 🔭 Discover | 🧠 Recognize | 🔎 Explain |
|---|---|---|
| Finds every device on your network, with presence and latency history. | Works out name, brand, model and category from many weak clues, and stays honest when it does not know. | For every answer, shows the clues behind it and how much each one counted. |

It is a Home Assistant **app** (not a custom integration): install it from the App store, no YAML. It reads Home Assistant’s registry to learn the names and rooms you already chose, and publishes back **only what you decide to share**.

## Not another network scanner

A scanner gives you a list. Vedetta gives you an *answer* and the *reason*. The same device, seen two ways (an example):

| | A typical scanner | Vedetta |
|---|---|---|
| **What you see** | `192.168.1.23` · `AA:BB:CC:…` · Espressif Inc. | **Kitchen light** · Shelly · smart switch |
| **When it is not sure** | “Unknown device”, `Android_7F3A` | It says so and keeps the device in *Other* |
| **Why that name** | Not explained | Every clue behind it is one tap away, with its weight |
| **What you set by hand** | Can be lost at the next scan | Is never overwritten |

## Show your work

Every clue is weak on its own. Vedetta weighs them together, counts a repeated fact once, and shows doubt as doubt. The weights are public.

<p align="center"><img src="docs/images/how-it-works.svg" alt="Ten weak clues are fused by family into name, brand, model, category and area; your own choice is never overwritten, and debug mode shows the reason" width="100%"></p>

<p align="center"><img src="docs/images/evidence-popup.png" alt="The pop-up of the Type shows each clue with its weight and the hypotheses that were rejected" width="560"></p>
<p align="center"><sub>Tap the (i) next to a name, brand or type: every clue, its weight, and what was ruled out</sub></p>

Sources, weights and certainty bars: [Recognition](docs/RECOGNITION.md).
<div align="center">

## 🐞 A device is wrong or unknown? Tell me.

<a href="https://github.com/Sived80/vedetta/issues/new/choose"><img src="docs/images/report-device.svg" alt="Report a device" height="40"></a>

Every report is read and becomes a fix or a new recognition rule, and Vedetta is updated. Attach the encrypted export: it is safe to post.

<sub>Want to do more? [Teach it a device](docs/DEVELOPMENT.md).</sub>

</div>

> [!IMPORTANT]
> **Give it a day or two.** Right after the install Vedetta only knows what it could see in the first minutes. Phones sleep, names are announced now and then, and the presence history is what tells a phone with a changing MAC from a fixed device. A deep search also runs by itself every night at 03:00. Please leave it running for **24 hours (48 is better)** before judging a device. [Why, and what to do if one is still wrong](docs/TROUBLESHOOTING.md).

## Install

> [!NOTE]
> Needs **Home Assistant OS** or **Supervised** (Settings shows **Apps**). Home Assistant *Container* or *Core* has no app store.

1. Add the repository with this button, or add `https://github.com/Sived80/vedetta` by hand in the App store:

   [![Add the Vedetta repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FSived80%2Fvedetta)
2. Search **Vedetta** in the App store and press **Install**.
3. Switch on **Show in sidebar**, press **Start**, open **Vedetta** and press **Scan network**.

Step by step, the local-app option and the first launch: [Installation](docs/INSTALLATION.md).

⭐ If Vedetta names your devices right, a star helps others find it. *Watch → Custom → Releases* tells you when a new version comes out.

## Also inside

📱 Sleeping phones remembered · 📊 Presence and latency history · 🔭 Three search levels, you choose the risk · 🏠 Home Assistant and optional MQTT

All the details: [How Vedetta works](docs/HOW_IT_WORKS.md).

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

## 📜 License and credits

Vedetta is open source under the **[MIT License](LICENSE)**. Everything it builds on is listed, with its license, in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

- 🧰 **Nmap** and **arp-scan** are installed from the Alpine package repository when the app is built on *your* Home Assistant. They are **not included** in this repository; Vedetta runs them as separate programs.
- 🏭 MAC vendor names come from the public **IEEE registries**; icons from **Material Design Icons** (Apache-2.0).
- ™️ Brand and product names are used only to describe the devices Vedetta recognizes. This project is not affiliated with or endorsed by any of them.
