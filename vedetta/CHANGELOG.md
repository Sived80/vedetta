# Changelog

## 0.4.1
- A **Chromebook is no longer an Apple phone**: ChromeOS asks for the same DHCP options as iOS, so it was read as an iPhone (brand Apple, group Phones and tablets). Its DHCP vendor class (`chromeOS`) now tells it apart: it is a computer and gets no brand from the fingerprint. *(Reported on GitHub, #1.)*
- A **Fairphone is a phone**: Fairphone (and Murena, the e/OS maker) only sell phones, so the brand alone says "phone"; the Android DHCP class by itself was not enough with a factory MAC address. *(#2.)*
- **The export no longer refuses to run.** Cause: the safety check took the multicast groups the app writes in its own log (`239.255.255.250` for SSDP, `224.0.0.251` for mDNS) for "public addresses", while the masking rightly leaves them alone, so the whole export was refused ("masking could not be guaranteed"). The check and the masking now use the same rules, and a test feeds them thousands of address shapes to keep them in agreement. Besides, if one file ever cannot be masked, only that file is left out: `manifest.json` says which one and the kind of problem (never the value) and the page warns that some files were left out. Any `192.168.*` or `172.16-31.*` written with dashes is masked too. *(Reported by two people, one of them on GitHub, #1.)*
- **Two leaks closed in the masking itself**, found by the new tests that feed it every message the app can write: an address right after a word that ends in "ver" (`Server: …`, `DHCP DISCOVER: …`) was taken for a version number and left readable, and a MAC written right after a word and a colon (`mac:AA:BB:…`) was not recognised. A line the masking still cannot clean is now replaced by a note (`[line removed: …]`) and the rest of the file is kept; the manifest counts the lines. If the export fails for any other reason the page now says so and the reason is written in the log.

## 0.4.0
- **Certainty bars** in the device sheet: the rows Name, Brand and Type have a thin bar with the certainty (how it is worked out is in the README) and an (i) that opens a small pop-up with what decided it and the hypotheses it rejected, with the reason. Pressing outside the pop-up closes it.
- **Deep-search badge**: an orange badge on the corner of the arrow next to "Scan the network" says how many devices were never analysed in depth (all of them on the first start, nothing is shown at zero). Opening the menu, the same badge flies into the "To analyse" tile and comes back when it closes. The menu now has two tiles (All | To analyse) and one note, instead of two repeated lines, and says that the search also starts by itself at 03:00.
- **Time zone from Home Assistant**: the nightly maintenance (03:00) and the time in the log follow the time zone of Home Assistant (it was fixed to Rome). Without Home Assistant, the container's time is used.
- **Export for analysis** now also contains the evidence of every device (`state/evidence.json`), the numbers behind "phone" (score, reason and how many private MACs were used, never the addresses), the offset of the time zone, how many devices never had a deep search and counts about the merge of phone cards. Everything goes through the same masking.
- **Phones with private MAC addresses**: a card that has used two or more different private MACs counts as a phone or tablet. A replaced network card or a MAC lent by a repeater does not.
- **Duplicate phone cards are merged**: when a phone changes address and leaves an offline card, two mobile cards with the same distinctive name, at least one online and never online together for more than 30 minutes, become one (the older card, with its history and your choices). Nothing is merged if it is not clear. A notice in the log says it happened.

## 0.3.9
- Export for analysis: public addresses are masked too, **also the ones the app never announced**: your own public IP written in an old line of the log, the routers of your provider on the way out to the Internet, any address that is not a well-known public DNS. Before, only the address read at the moment of the export was known, and right after the app restarted it was not known yet. The final safety check now refuses the export if any such address is left.

## 0.3.8
- Export for analysis: the device ids (`scan-192-168-1-5`) carried the real network written with dashes and were not masked; they are now masked like any other address (`scan-10-0-0-5`), in every file and in the history database.
- Export for analysis: also masks every name in the registries of the house (Home Assistant, Bonjour, DHCP), even for devices that are not on the board, email addresses, and passwords, tokens and keys written in logs or text. A final safety check refuses to export anything if something readable is left, instead of delivering a half masked file.

## 0.3.7
- Export for analysis is anonymised: IPs keep the last number (`10.0.0.x`), MAC addresses keep the manufacturer prefix, names of devices, areas, DHCP and Bonjour hostnames become `iPhone-1`, `Thermostat-1`, `Area-2`... The same value always gets the same placeholder in every file (JSON, log, history database), brand, type, ports, times and scores are left as they are, and the real devices are not touched. The table placeholder → real value stays on your machine and is never in the zip.
- Two ways to export: the button makes an **encrypted** `.txt` (sealed with the author's public key, safe to attach to a public GitHub issue), the arrow next to it a **plain** `.zip` for you or someone you trust. The dialog explains what each one is for. If encryption is unavailable nothing is exported: it never falls back to a plain file.
## 0.3.6
- Brand logos reach more devices: "AdGuard Team" (the name Home Assistant gives) is recognized as AdGuard, a host named "MSI" is an MSI, and a host named "Node-RED" (or serving its page) is Node-RED, even when the network card or the virtual machine says something else.

## 0.3.5
- Brand logos: a big faint logo on the right of each card, cut by the edge, and in the device sheet; in list view the logo replaces the icon in the circle, tinted with the brand colour. 58 brands to start with (Simple Icons and Dashboard Icons, shipped with the app, no Internet request). A brand without a free logo shows none; chip makers never get one. The logo follows the brand shown now, so a brand changed by hand or by a new clue changes it.
- New brand "Magic Home" (the maker is Zengge): recognized from the name, the MAC prefix or the manufacturer declared by Home Assistant.
- The software running on a device now wins over the maker of its hardware: Tasmota and ESPHome are recognized from the web page, so a Sonoff flashed with Tasmota is a Tasmota device.

## 0.3.4
- Pause: the bar under the first card now follows the pause. A timed pause turns it orange and it fills while the pause runs, full when the service resumes; stopped until resumed it is solid red.
- "Open web interface" only appears when an open port really serves a page for people (a normal page, a redirect or a login). Ports that answer 404, 400 or a few bytes of API output (a TV's control service, a streaming stick) no longer get the button, and the button opens the port that does serve the page, with https where needed. Devices analysed before this version keep the old rule until their next deep search.
- Response time: when a device does not answer ping (a PC with the Windows firewall, a sleepy IoT device) the app now measures the ARP round trip, which every device on the same network must answer. If nothing answers, the value stays empty.
- The page check now reads the whole answer instead of the first packet, so small servers that send headers and page separately are no longer taken for empty.

## 0.3.3
- Deep search "not yet analysed": a device that answers nothing useful (a phone with every port closed) is no longer listed again and again. The search now remembers it was tried ("Deep search: nothing found" on the device card), and the nightly run waits as long as for any other device.
- A deep search no longer erases what a device announced earlier (Bonjour name and model, UPnP, NetBIOS). A phone that was asleep during the scan keeps its identity instead of falling into "Other devices". If the scan finds no open port at all, every previous clue is kept.

## 0.3.2
- Log card: the "Log level" button now sits on the same column as the title arrow, and the "Search the log" field is slightly more compact.
- Start-up messages of the app (`run.sh`) are now in English, like the documentation and the code comments.
- Documentation: install steps checked on a real Home Assistant, correct direct links (`/app/<name>`), and a note on what improves over time.

## 0.3.1
- Deep search: the menu next to "Scan network" has a second item, "Deep search: not yet analysed…", that analyses in depth only the devices that never were (the ones with no "Last deep scan" date). When every device has already been analysed, the item is disabled.

## 0.3.0
- More solid recognition: clues add up by family (the same fact, like Cast, counts once), ports have a cap, and two categories tied on weak clues stay in "Other devices".
- Product signature catalog (`app/data/signatures.json`): the declared model decides where generic signals are ambiguous (Google Home vs Chromecast, Fire TV, PlayStation, Proxmox...).
- Debug mode: list of the clues with their family and points; app documentation updated.

## 0.2.1
- Memory of Bonjour (mDNS) names per MAC and continuous listening for announcements: sleeping phones (iPhones with a private address) keep the name once it has been seen.
- Page titles that are a software name with a version no longer become the device name; the declared DHCP class (e.g. PS3) counts as a clue for type and brand; consoles added to the types.

## 0.2.0
- Home Assistant data (device registry, read-only) as a source of name, brand, model, area and category; new "Home Assistant data" step in the search methods. Needs the `homeassistant_api` permission.
- Sharing with HA by choice: each device card has "Share with HA" / "Remove from HA". Home Assistant shows a "Vedetta" device with the shared devices as sub-devices, without merging into existing ones.
- Categories reduced to 9; names from the network role (DNS server, Repeater...), placeholders recognized, brand and type editable by hand.
- Device card: fixed attributes and a "More attributes" drop-down; debug mode (3 taps on the title) and export for analysis.
- Classic page removed: only the `/ha` dashboard through ingress remains.

## 0.1.0
- First version as a Home Assistant app: ingress, data in /data, MQTT discovery.
