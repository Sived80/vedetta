# Home Assistant integration

What Vedetta reads from Home Assistant and what it can publish back. Publishing needs MQTT: see [MQTT](MQTT.md).

[← Back to the README](../README.md)

| Direction | What happens |
|---|---|
| **HA → Vedetta** *(read-only)* | Device registry, areas and integrations give names, manufacturers, models and categories. Matched by MAC, or by the device’s configuration address when it is unique. Turn it off in *Search methods → Home Assistant data*. |
| **HA → Vedetta** *(read-only, off by default)* | The clients your router integration tracks on other networks can be shown as cards, without being probed: see [Networks seen by Home Assistant](HA_NETWORKS.md). |
| **Vedetta → HA** *(Alerts)* | An event on the bus for each message (`vedetta_new_device`, `vedetta_device_down`, `vedetta_device_back`, with `card`, `label`, `ip`, `brand`, `type`, `kind`, `reason`, and `minutes` on a return; `vedetta_test` from *Send a test*). `brand` is the product brand, `type` and `kind` are the same as in MQTT, `reason` says why a device is new (`new_mac`: a MAC never seen on the home network, `new_behind_router`: an address never seen on a network behind the router). A value Vedetta does not know is `null`, never missing. Events are off until you turn on *Events in Home Assistant*; a notification through the notify services you pick, only if you pick some. |
| **Vedetta → HA** *(your choice, needs MQTT)* | MQTT discovery publishes one **Vedetta** device (online / offline / mobile counters, average latency, *Scan now*). Per device, **Share with HA** adds a sub-device with tracker, connectivity and latency. Its tracker attributes include `type` (the group: `router`, `media`, `iot`…; the smart home groups of the page, such as climate or energy, stay `iot` here) and `kind` (a finer type such as `accesspoint`, `nas`, `tv`, `plug`; `null` when Vedetta has none). Renames follow; removing cleans HA up. |

Ready-made blueprints for the events: [new device](../blueprints/automation/vedetta/new_device.yaml) and [device went offline](../blueprints/automation/vedetta/device_down.yaml), with import buttons in the [README](../README.md#automations).
