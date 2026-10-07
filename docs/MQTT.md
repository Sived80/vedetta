# MQTT (optional)

Sharing devices with Home Assistant uses MQTT discovery.

[← Back to the README](../README.md)

> [!NOTE]
> Sharing with Home Assistant uses **MQTT discovery**. MQTT is **not part of a default Home Assistant installation**:
> you need a broker and the MQTT integration.

- Easiest path: install the **[Mosquitto broker app](https://github.com/home-assistant/addons/blob/master/mosquitto/DOCS.md)**
  and add the **[MQTT integration](https://www.home-assistant.io/integrations/mqtt/)**. Vedetta then finds the broker on its own.
- Already have a broker? Enter its address in the app options (`mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`).
- How the discovery messages work: [MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery).

> [!TIP]
> Without MQTT everything else works — search, recognition, Home Assistant lookups, history. Only the **Share with HA** button
> (and the *Vedetta* device with its counters) needs it, and it stays hidden until a broker is connected.
