# Troubleshooting

Why a device may look wrong in the first hours, and what to try when something does not work.

[← Back to the README](../README.md)

## Give Vedetta 24 hours before you judge it
> Right after the install it only knows what it could see in the first minutes: addresses, and the few names that were already announced. **Most of what makes it good needs time**, and wrong or empty results in the first hours are expected, not a bug:
> - phones sleep and answer only when they wake up, and so do many smart devices;
> - names, models and services are *announced* by the devices now and then (Bonjour, DHCP): Vedetta remembers them as they arrive;
> - who comes and goes (the presence history) is what tells a phone with a changing MAC address from a fixed device;
> - the **deep search** (the badge on the arrow next to *Scan the network* says how many devices still need it) also runs by itself every night at 03:00.
>
> So please **leave it installed, running and with the machine switched on for at least 24 hours (48 is better)** before you decide a device is wrong or open an issue, and press the deep search once.
>
> *Why this is written so loudly:* Vedetta is a one-person project made in spare time. Many reports arrive minutes after the first installation, about devices that simply had not had time to be learned, and answering them takes the time needed to fix the real mistakes. If a device is still wrong after a day, that is exactly the report that helps: use [the issue form](https://github.com/Sived80/vedetta/issues/new/choose) and attach the encrypted export.

## Something not working?

| What you see | What to try |
|---|---|
| Vedetta is not in the sidebar | Open the app page → **Info** tab → switch on **Show in sidebar**. |
| Option B: no **Local apps** section | Check the path is exactly `addons/vedetta/config.yaml`, then **⋮ → Check for updates** again. |
| `\\homeassistant.local` does not open | Use the IP address of Home Assistant, and check that **Samba share** is started. |
| The page opens but no devices appear | Open the app's **Log** tab. If you have several network cards, set the `interface` option (for example `enp0s18`). |
| An iPhone is called *Apple mobile* | Phones with a private Wi-Fi address announce nothing. Set the name once by hand and it stays. |
| After an update something looks old | Press <kbd>Ctrl</kbd> + <kbd>F5</kbd> in the browser. |
