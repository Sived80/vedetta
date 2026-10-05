# Third-party notices

Vedetta itself is released under the [MIT License](LICENSE). It uses the components below, each under
its own license. None of them is modified, and none of the programs in the last two sections is included
in this repository.

## Python libraries

Installed with `pip` when the app image is built (`vedetta/requirements.txt`). The table lists the
versions pinned there and everything they pull in. Licenses were read from the installed packages.

| Package | Version | License |
|---|---|---|
| fastapi | 0.115.0 | MIT |
| uvicorn | 0.30.6 | BSD-3-Clause |
| httpx | 0.27.2 | BSD-3-Clause |
| PyYAML | 6.0.2 | MIT |
| Jinja2 | 3.1.4 | BSD-3-Clause |
| python-multipart | 0.0.9 | Apache-2.0 |
| zeroconf | 0.151.5 | LGPL-2.1-or-later |
| paho-mqtt | 2.1.0 | EPL-2.0 OR BSD-3-Clause |
| starlette | 0.38.6 | BSD-3-Clause |
| pydantic, pydantic-core, annotated-types, typing-inspection | 2.x | MIT |
| anyio, h11, httptools, ifaddr, watchfiles | various | MIT |
| httpcore, click, idna, MarkupSafe, python-dotenv, websockets, colorama | various | BSD-3-Clause |
| sniffio | 1.3.1 | MIT OR Apache-2.0 |
| certifi | 2026.x | MPL-2.0 |
| typing_extensions | 4.x | PSF-2.0 |

`zeroconf` (LGPL) and `certifi` (MPL) are used as installed, unmodified libraries.

## Bundled data and code

- **MAC vendor names** (`vedetta/app/data/oui-ieee.txt`): generated from the public registries published by the
  IEEE Registration Authority (MA-L, MA-M, MA-S and IAB, <https://standards-oui.ieee.org/>) with
  `tools/update_oui.py`. Names are cleaned only for case and HTML entities.
- **Brand logos** (`vedetta/app/static/ha/logos/`, table in `vedetta/app/data/brand_logos.json`): silhouettes cleaned
  by `tools/update_logos.py` from [Simple Icons](https://simpleicons.org) (CC0-1.0) and from
  [Dashboard Icons](https://github.com/homarr-labs/dashboard-icons) (Apache-2.0,
  <https://www.apache.org/licenses/LICENSE-2.0>, modified: reduced to a single-colour shape). The logos remain
  trademarks of their owners and are shown only to identify the brand of a device, with no claim of affiliation.
- **Icons** (`vedetta/app/static/ha/icons.js`): path data from
  [Material Design Icons](https://pictogrammers.com/library/mdi/) by Pictogrammers, licensed under the
  Apache License 2.0 (<https://www.apache.org/licenses/LICENSE-2.0>).

## Programs run by the app (not included)

- **Nmap** and **arp-scan** are installed from the Alpine Linux package repository when the app image is
  built on your own Home Assistant. Vedetta runs them as separate programs and reads their output. They are
  not part of this repository, and Vedetta does not publish a ready-made image that contains them. Nmap is
  covered by the [Nmap Public Source License](https://nmap.org/npsl/); arp-scan by the GNU GPL.
- The app image is built on the Home Assistant base image
  (<https://github.com/home-assistant/docker-base>).

## Trademarks

Brand and product names (Home Assistant, Shelly, Tasmota, Apple, Google, Sony, Proxmox and others) are used
only to describe the devices Vedetta recognizes. Vedetta is an independent project and is not affiliated
with, or endorsed by, any of them.
