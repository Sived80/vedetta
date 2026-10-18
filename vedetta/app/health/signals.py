"""Signals derived from the history, in one place so that the app and the replay of the exports see the same thing."""


def drops_by_device(events) -> dict[str, list[float]]:
    """The moments at which each device went from online to offline. `events` are (device, online, ts) in time order; the first sight of a device is not a drop, and an offline that follows an offline is not another one."""
    state: dict[str, bool] = {}
    drops: dict[str, list[float]] = {}
    for device, online, ts in events:
        if state.get(device) and not online:
            drops.setdefault(device, []).append(ts)
        state[device] = online
    return drops
