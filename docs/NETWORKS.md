# Networks and VLANs

Most homes have more than one network: the main one, one for smart-home devices, one for guests, sometimes one for cameras. Vedetta lists them in one page and, for each, shows what it can see there and how to see more.

[← Back to the README](../README.md) · [Network doctor](NETWORK_DOCTOR.md) · [Networks seen by Home Assistant](HA_NETWORKS.md) · [Privacy](PRIVACY.md)

## The Networks page

Menu → **Networks**. One row for each network, with its name, its address, its VLAN, its state and how many devices it holds. Up to 8 networks, the main one included.

| State | What it means |
|---|---|
| **Active** | Vedetta checks its devices |
| **New** | a network Vedetta noticed from the addresses of devices you already have: tap **Adopt** to keep it |
| **Silent for 24 h** | none of its devices answered for a day |
| **Paused** | no check until you tap **Resume** |

The gear of a row opens the network: its name, address and VLAN, its state, **What Vedetta sees**, the devices you ignored there and a **Danger zone**.

## What Vedetta sees

Seven functions, each with **who gives it**: **Vedetta** (it asks the devices itself), **Home Assistant** (through an integration) or your **Router**.

| Function | What it gives |
|---|---|
| Presence | who is on now |
| Name | the name of each device |
| MAC | the hardware address of each device |
| Ports | which services it offers |
| Model | brand and model |
| Stealth | the devices that do not answer |
| Strays | the devices with an address of another network (*coming soon*) |

A function that is not available yet shows **How to turn it on**: a few steps for the simplest way, with where to find them in your router or in Home Assistant. Vedetta changes neither the router nor Home Assistant.

## Adding a network behind the router

**Add network**: a name, the address and subnet as in your router (from `/22` to `/30`, for example `192.168.30.0/24`) and, if you like, the VLAN number. **Try** first: one ping to each address, up to half a minute, and the list of what Vedetta would see. Nothing is saved until you tap **Add**.

On a network behind the router:

- devices are found by **ping, every 15 minutes**; the ones there at the start are the starting point, with no alert;
- **Ports** has a switch: on, Vedetta also reads ports and model, as on your own network;
- the **MAC** of a device does not cross the router: it comes from the router's integration in Home Assistant, or from the router itself over read-only **SNMP v2c** (address and community in the panel; the community stays in Vedetta's data and is never shown again or exported);
- without the router integration in Home Assistant, a device that changes address looks new.

## Danger zone

- **Delete this network** (a network you added): deletes the network and everything Vedetta knows about its devices.
- **Delete all devices** (the main network): deletes its devices and what Vedetta knows about them; the network stays, and what Vedetta finds next is the starting point, with no new-device alert.

Both show what will go before you confirm, and cannot be undone.

## Good to know

- **Beyond the network Home Assistant is on, Vedetta touches only what you chose:** the networks you added and the devices you added. Paused networks, public addresses and the networks of Home Assistant's containers are never touched.
- **One machine on two networks** (your router, Home Assistant with an address on a VLAN) has a card on each, with the same name and the network after it, side by side.
- **A network you cannot reach** (a guest network closed by a firewall): its devices can still be shown through your router integration, without being touched: see [Networks seen by Home Assistant](HA_NETWORKS.md).
