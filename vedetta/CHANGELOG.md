# Changelog

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
