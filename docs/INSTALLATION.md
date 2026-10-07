# Installation

How to install Vedetta in Home Assistant, what happens at the first launch, and which permissions the app asks for.

[← Back to the README](../README.md)

# Install

> [!NOTE]
> **Before you start.** Vedetta is a Home Assistant *app* (older versions call it an *add-on*). Open Home Assistant and go to
> **Settings**: if you see **Apps** (or **Add-ons**, or **Applicazioni** in Italian), you are ready. If you run Home Assistant *Container* or *Core*, there is no
> app store and Vedetta cannot run. It needs **Home Assistant OS** or **Supervised**.

Pick **one** of the two ways below. Both end the same way: Vedetta appears in your sidebar.

## Option A · Add the repository (the easy way)

1. **Add the repository.** Click the button:

   [![Add the Vedetta repository to my Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FSived80%2Fvedetta)

   It opens a small My Home Assistant page (the first time it asks for your Home Assistant's address, usually `http://homeassistant.local:8123`). Press **Open link**. Home Assistant then asks **Add the app repository?** with the address already filled in: press **Add**.

   *Nothing asks and you land on the App store? Then the repository is already added: go on to step 2.*

   *Prefer to do it by hand, or the button does not work?* In Home Assistant open **Settings → Apps**, press **Install app** (bottom right) to open the App store, press **⋮** (top right) and choose **Repositories**. Press **Add** (bottom right), paste the address below and press **Add** again. The window closes by itself and **Vedetta** appears in the list:

   ```text
   https://github.com/Sived80/vedetta
   ```

   *In an Italian Home Assistant the same path is* **Impostazioni → Applicazioni → Installa app → ⋮ → Archivi digitali → Aggiungi**. *The App store page is titled* Raccolta delle app.

2. Back in the App store, type **Vedetta** in the search box. It shows up under its own heading. Open it: the page shows the version and an **Install** button. Press **Install**.
3. When it finishes, switch on **Show in sidebar**, then press **Start**.
4. Click **Vedetta** in the left sidebar (or open `http://homeassistant.local:8123/app/468cebee_vedetta`). Done: go to [First launch](INSTALLATION.md#first-launch).

## Option B · Local app (without the repository)

You copy the app folder into Home Assistant's `addons` folder, using the **Samba share** app to reach it from your computer.

1. **Install Samba share.** *Settings → Apps → App store →* search **Samba share** *→ Install.* Open its **Configuration** tab, type a **username** and **password** of your choice, save, then press **Start**.
2. **Get the files.** You need the folder named `vedetta` (the one that contains `config.yaml`). On the [GitHub page](https://github.com/Sived80/vedetta) press **Code → Download ZIP** and unzip it.
3. **Open the Home Assistant folders from your computer.**
   - *Windows:* press <kbd>Win</kbd> + <kbd>E</kbd>, click the address bar, paste the line below and press <kbd>Enter</kbd>.
   - *Mac:* in Finder choose **Go → Connect to Server** and paste `smb://homeassistant.local/addons`.

   ```text
   \\homeassistant.local\addons
   ```

   Sign in with the Samba username and password from step 1. If `homeassistant.local` is not found, use your Home Assistant's IP address instead (for example `\\192.168.1.50\addons`).
4. **Copy the whole `vedetta` folder** into that `addons` folder. You should end up with `addons/vedetta/config.yaml`.
5. **Tell Home Assistant to look again.** *Settings → Apps → App store → ⋮ → Check for updates.* A **Local apps** section appears at the bottom with **Vedetta**.
6. Open it, press **Install**, switch on **Show in sidebar**, press **Start**.
7. Click **Vedetta** in the left sidebar, or jump straight in with a direct link (replace `homeassistant.local` with your Home Assistant's address if it is different):

   | Go to | Link |
   |---|---|
   | The Vedetta page | [`http://homeassistant.local:8123/app/local_vedetta`](http://homeassistant.local:8123/app/local_vedetta) |
   | The app's settings page (Start, Stop, Log) | [`http://homeassistant.local:8123/config/app/local_vedetta/info`](http://homeassistant.local:8123/config/app/local_vedetta/info) |
   | The Vedetta page, through My Home Assistant (asks for your address once) | [open Vedetta](https://my.home-assistant.io/redirect/supervisor_ingress/?addon=local_vedetta) |
   | The app's settings page, through My Home Assistant | [open the app page](https://my.home-assistant.io/redirect/supervisor_app/?app=local_vedetta) |

   > [!TIP]
   > Bookmark the first link. These links are for **Option B**. With Option A the app is named `468cebee_vedetta` (the code comes from the repository address, so it is the same for everyone): use `http://homeassistant.local:8123/app/468cebee_vedetta`.

> [!TIP]
> For developers: `tools/deploy_addon.sh` does steps 4-6 over SSH.
> `VEDETTA_HA_HOST=<your-ha-address> VEDETTA_HA_KEY=<ssh-key> tools/deploy_addon.sh`

## First launch

1. Open **Vedetta** from the sidebar. The first page may be empty: that is normal.
2. Press **Scan network**. Within a few seconds the devices on your network appear; add the ones you want on your board.
3. **Leave it running for at least 24 hours** (see the box at the top). Vedetta is not learning: it collects clues, and some only arrive with time. Phones that were asleep announce their names when they wake up, the history bars (24 h and 7 days) fill in, and a deeper search runs every night. Expect most names to settle within a day. Devices that announce nothing (an iPhone with a private Wi-Fi address, for example) stay generic: set their name once by hand and it stays.
4. Curious why it chose a name? The debug view lists every clue behind each name and brand.

Want to share devices back into Home Assistant? That needs an MQTT broker: see [MQTT (optional)](MQTT.md). Everything else works without it.

**Updating:** when a new version is out, *Settings → Apps → Vedetta → Update*.

<details>
<summary><b>Permissions, explained</b></summary>

| Permission | Why |
|---|---|
| Host network + `NET_ADMIN` / `NET_RAW` | `arp-scan`, `nmap`, ping, mDNS/SSDP, passive DHCP (UDP 67). Local requests only. |
| `homeassistant_api` | **Read-only** registry lookups (devices, entities, areas, integrations). |
| MQTT service *(optional)* | Publishes only what you choose to share, if a broker is available. |
| Ingress | UI reachable only through Home Assistant. |

</details>
