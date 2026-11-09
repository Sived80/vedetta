from . import shelly_gen1, generic, ping

ADAPTERS = {
    "shelly_gen1": shelly_gen1.probe,
    "generic": generic.probe,
    "ping": ping.probe,           # chosen by the network (touch "presence" behind the router), never stored on a card
}
