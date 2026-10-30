# Networks seen by Home Assistant

Vedetta scans the network it is on. A device on another network (a VLAN for smart-home devices, a guest network) is out of its reach, but your router or controller usually knows it, and Home Assistant already lists it through the integration of that router. This function lets Vedetta show those devices **without touching them**.

[← Back to the README](../README.md) · [Home Assistant integration](HOME_ASSISTANT.md) · [Privacy](PRIVACY.md)

## What it does

Menu → **Networks seen by Home Assistant**. Turn the function on, press **Read now**, tick the devices you want and press **Adopt**. An adopted device becomes a card like the others: a tile in the group of its type, and the same device card with its history, its name, brand and type rows and its *Other attributes*.

What a card of this kind does **not** have, because Vedetta never talks to the device: ports, response time, uptime, the analysis state, *Search in depth*, *Share with HA* and the report flag. Its online or offline state is what Home Assistant says, with the delay of its integration (usually a few minutes).

## What is read, and what is not

The function is **off by default** and only reads while it is on.

- Home Assistant is asked for its states. Of them, only the **device trackers whose source is a router** are kept (UniFi, FRITZ!Box, MikroTik, a network scanner such as `nmap_tracker`…), and of each only **five facts**: IP address, MAC address, host name, the name Home Assistant shows, and whether it is at home or away.
- Phones with a location, people, zones and anything else are dropped on the spot: nothing of them is kept, shown or written in the log.
- The trackers Vedetta itself publishes by MQTT are left out, so its own devices never come back as new ones.
- A device Vedetta already has (same MAC or same address) is not offered again.
- Nothing is sent to any device: no ping, no port scan, no ARP. The only conversation is with Home Assistant, through the same read-only channel as the registry.

What you adopt is kept in `passive_devices.json` in the app's data folder, **never** in `devices.yaml`, which is the list of what Vedetta checks. What you choose by hand (name, type, brand) is kept apart from what Home Assistant says, so a new reading never overwrites it.

## Names, types and brands

These cards are sure about what Home Assistant tells: a name set in your router or in the integration is shown as it is, with 100% in the three rows. If it is wrong, correct it at the source, or change it in Vedetta: the pencil (name, brand) and the arrow (type) work as on any card, and *Customize card* in the three-dots menu shows them. The type is guessed from the name and the manufacturer in the MAC, like for any card, and you can choose another.

*Ignore device* in the three-dots menu takes the card off the page. It is offered again in the list as long as Home Assistant sees it.

## The list

Clients are grouped by network, in the order Home Assistant lists them, with the addresses ascending inside each one; the ones without an address come last. The network is the `/24` of the address: the VLAN itself is not part of what Home Assistant gives. On the page, a card sits among the others of its group, in address order.

After **Adopt** the panel closes by itself; reopen it from the menu. The number next to the menu entry is how many clients can still be adopted.

## Good to know

- **It needs a router integration in Home Assistant** that tracks the clients (the *Track network devices* option in UniFi, for example), and the clients you want must be tracked there. Vedetta cannot see a device Home Assistant does not.
- **Presence is slower than a probe.** Integrations hold a client "at home" for a while after it leaves (the *consider home* time), so a card of this kind turns offline later than a scanned one. For the same reason the network health check does not use these cards.
- **"Unavailable" is not "away".** When the integration is reloaded or the controller restarts, Home Assistant reports its clients as unavailable: the cards keep their last known state.
- **MQTT.** These cards are not published to Home Assistant: Home Assistant already has them.
- **Several networks with the same addresses** (two networks both using `192.168.1.x`) are not told apart: the MAC identifies the device.

## If it does not work

- *Only available inside Home Assistant*: the app has no access to Home Assistant (outside the add-on, or `homeassistant_api` off).
- *Home Assistant does not answer*: it is busy or restarting; the cards keep their last state and the next reading is in a minute.
- The list is empty: the integration of your router does not track those clients, or Vedetta already has them all.
