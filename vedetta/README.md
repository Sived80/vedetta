# Vedetta

Local network dashboard for Home Assistant: it finds and recognizes the devices on your LAN (name, brand, category),
follows their presence and latency, and shows them in the sidebar. It reads Home Assistant's registries
(read-only) to recognize them better and shares with Home Assistant only the devices you choose; alerts only if you turn them on. Nothing about
your devices leaves your network; three optional checks reach the Internet (see DOCS.md).

It runs on Home Assistant OS and Supervised (it uses the host network). Details, permissions and options are in **DOCS.md**.
