# Home Assistant integration

What Vedetta reads from Home Assistant and what it can publish back. Publishing needs MQTT: see [MQTT](MQTT.md).

[← Back to the README](../README.md)

| Direction | What happens |
|---|---|
| **HA → Vedetta** *(read-only)* | Device registry, areas and integrations give names, manufacturers, models and categories. Matched by MAC, or by the device’s configuration address when it is unique. Turn it off in *Search methods → Home Assistant data*. |
| **Vedetta → HA** *(your choice, needs MQTT)* | MQTT discovery publishes one **Vedetta** device (online / offline / mobile counters, average latency, *Scan now*). Per device, **Share with HA** adds a sub-device with tracker, connectivity and latency. Renames follow; removing cleans HA up. |
