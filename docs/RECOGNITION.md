# How Vedetta recognizes a device

Sources, weights, certainty bars and the rules for phones. Everything here is public, so no number has to be taken on trust.

[← Back to the README](../README.md)

<p align="center"><img src="images/how-it-works.svg" alt="Ten weak clues are fused by family into name, brand, model, category and area; your own choice is never overwritten, and debug mode shows the reason" width="100%"></p>

- 🗳️ **One fact, one vote.** Cast shows up as an mDNS service, a local API, two ports and a DIAL record — that is *one*
  clue, counted once.
- 🧩 **Platform ≠ function.** A Shelly or Tasmota tells you *“smart device”*, not *“gate opener”*. The word in the name wins.
- 🧾 **Signatures for the ambiguous.** A Google Home and a Chromecast both say “Cast”; the declared model settles it.
- 🧹 **Placeholders are not names.** `Android_7F3A…`, `wMAN MOD 1.47.45`, `shelly1-8CAA…` are recognized as noise and
  replaced by something better — or by *brand + type* (“Sony console”) when nothing else exists.
- 🤷 **Honest about doubt.** Two equally weak candidates → *Other devices*. You can always pick brand and type by hand.
- 🔍 **No black box.** The weights are public: see [the weights, in the open](#the-weights) just below (open the section).

<a name="the-weights"></a>

<details>
<summary><b>The weights, in the open</b> — every number that decides a category and a name</summary>

<br>

**Category.** Each clue adds points to a category; clues that tell the *same fact* count once (the best of the family).

| Clue | Points |
|---|---:|
| Network role (gateway, repeater, access point) | **10** |
| Product signature from the catalog | **8 – 14** |
| Declared service or protocol (mDNS service, UPnP type, ONVIF, local API, Home Assistant integration) | **8** |
| RTSP server header | 6 |
| Service **confirmed** by nmap on a typical port | 4 |
| Brand that makes only one kind of device | 3 |
| Word in the name / page title / banner | 2 *(specific kind words 2–4)* |
| Port number only (service not confirmed) | 1 |

Guard rails: all ports of a category together **max 6**; generic platform clues (Shelly, Tasmota, ESPHome, a chip maker)
**max 3** in total, so a word like *“Thermostat”* always beats *“it runs Tasmota”*; **at least 2 points** or the device stays in
*Other*; two categories within 1 point below 5 points stay in *Other* instead of being picked at random. A category chosen
by hand always wins.

**Name.** The most reliable source wins; a name you set is never overwritten.

| Source | Weight |
|---|---:|
| **Your own name** | never replaced |
| Name you chose in Home Assistant | 95 |
| The device’s own local API | 90 |
| mDNS / Bonjour | 70 |
| Home Assistant integration / device name | 68 |
| UPnP friendly name | 65 |
| DHCP hostname | 55 |
| NetBIOS | 45 |
| Reverse DNS | 40 |
| TLS certificate host name | 38 |
| ONVIF | 35 |
| Web page title *(never a software name with a version)* | 30 |
| Placeholders (`Android_7F3A…`, `shelly1-8CAA…`) | 20 |

Nothing left? It builds one: **brand + model → brand + type → brand + category → network role** (“Server DNS”) → the IP address.
A generated name is never counted as evidence for the category — the app does not get to agree with itself.

</details>

## Certainty bars

Open any device: the rows **Name**, **Brand** and **Type** have a thin **certainty bar** with its percentage and an **(i)**. Press the (i) and a small pop-up says what decided it and which **hypotheses it rejected** (for example "Espressif: the MAC maker, it makes chips, not this product", or "IoT, 3 points: fewer than Network equipment"); press anywhere outside it to close it. The bar is not a mystery number:

- **Chosen by you:** 100%. It is never changed by itself.
- **Group:** how far the best group is from the second one, weighted by how much evidence there is. 12 points against 3 is 75%; 2 points and nothing else is 20%; a tie or too little evidence is 0% and the device stays in *Other devices*. A phone or tablet recognised by its signals is measured against the threshold of the mobile score.
- **Brand:** high when the MAC maker and the name agree or the device declares it; medium with a single clue.
- **Name:** the weight of the source: a name chosen in Home Assistant or given by the device counts more than a page title.

## Phones with changing addresses

iPhones and Android phones can use a **different private MAC address** on each network, or change it over time. Vedetta notices a card that has used two or more private MACs and counts it as a phone or tablet (a replaced network card has a global MAC and does not count; a MAC lent by a Wi-Fi repeater to its clients is ignored). When a phone changes address it leaves an offline card and gets a new one: if **exactly two mobile cards have the same distinctive name** (not a bare "iPhone"), at least one is online and they were **never online together for more than 30 minutes**, they are merged into the older card, which keeps your choices and the whole history. If it is not clear (three cards, two phones online together), nothing is merged.
