from . import shelly_gen1, generic

ADAPTERS = {
    "shelly_gen1": shelly_gen1.probe,
    "generic": generic.probe,
}
