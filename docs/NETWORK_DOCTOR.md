# Network doctor

Vedetta watches the health of your network while it checks your devices. When something repeats, it tells you what, on which device, and what to try. It never changes anything: it only looks.

[← Back to the README](../README.md) · [Networks and VLANs](NETWORKS.md) · [Privacy](PRIVACY.md)

## Where to find it

Network card → **Health**. It opens four tiles: **Addresses**, **Drops**, **Restarts**, **Latency**. Each shows how many problems are open now; a tile opens the list, a line opens the detail. With no problems it says *Network in good shape*. It is judged every 2 minutes.

## What it looks for

| Tile | Problem | When it speaks |
|---|---|---|
| Addresses | **Duplicate address**: two devices use the same IP | the two answer for that address together for at least 5 minutes, or take turns at it again and again |
| Drops | **Devices that drop together** | at least 5 devices, and at least 1 in 10, go away within the same 2 minutes |
| Restarts | **A device that restarts at a steady pace** | at least 5 drops in a day, between 2 minutes and 6 hours apart, at a regular rhythm |
| Latency | **Your router answers much slower** | its last 15 minutes are at least 3 times slower, and 3 ms slower, than the 6 hours before |

A problem opens only when it is seen at more than one check (one check for drops together), so one flicker opens nothing; it closes by itself after a few clean checks in a row. You can **hide** a problem you already know about.

## Good to know

- **It never controls a device.** No restart, no change of address: the doctor tells you, you decide.
- **Phones are treated as phones.** A phone that leaves the house or sleeps is not a restart.
- **New rules start hidden.** A new rule first runs hidden and is shown to everyone only after it proved right on real networks. In debug mode (three taps on the name of the Network card) you see the hidden ones too, marked as such.
- **Privacy.** The export says how many problems there were, for which rule and in which state, never addresses or names in clear.
