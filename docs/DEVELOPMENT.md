# Development and extending Vedetta

How to teach Vedetta a new device or brand logo, how the repository is organized and how to run the tests.

[← Back to the README](../README.md)

## Teach it a new device

Recognition is data, not code. A product signature in [`vedetta/app/data/signatures.json`](../vedetta/app/data/signatures.json)
is a few conditions on what a device declares:

```json
{
  "id": "google-home-speaker",
  "group": "audio",
  "kind": "speaker",
  "weight": 14,
  "fixture": "simulated",
  "all": [{ "field": "mdns_model", "re": "google home|home mini|nest mini|nest audio" }]
}
```

`fixture` says whether the signature comes from a **real** device or from the manufacturer’s published data. Export your
device with *Export for analysis*, find the clue that sets it apart, add a row, run the tests.

**Brand logos** work the same way. [`vedetta/app/data/brand_logos.json`](../vedetta/app/data/brand_logos.json) lists, for each
brand, the names it may appear with and its logo file. The logo is worked out from the brand a device shows *now*, so it
follows a brand you change by hand. Add a brand to the list in `tools/update_logos.py`, run it, and the files and the table
are regenerated (logos come from [Simple Icons](https://simpleicons.org) and
[Dashboard Icons](https://github.com/homarr-labs/dashboard-icons)). Only logos that may be redistributed belong here.

## Development

```text
vedetta/            the app (config.yaml, Dockerfile, FastAPI backend, vanilla-JS frontend)
tests/              check_*.py — real-device fixtures and unit checks
tools/              run_tests.py · deploy_addon.sh
```

```bash
python tools/run_tests.py     # everything, from the vedetta/ folder
```

**Stack:** Python 3.14 · FastAPI · asyncio · python-zeroconf · nmap/arp-scan · SQLite · paho-mqtt · plain JavaScript (no
build step).

> [!TIP]
> For developers: `tools/deploy_addon.sh` does steps 4-6 over SSH.
> `VEDETTA_HA_HOST=<your-ha-address> VEDETTA_HA_KEY=<ssh-key> tools/deploy_addon.sh`
