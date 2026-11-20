"""The life of a network, for the panel «Networks»: how many cards it holds, how many are on now, and whether it went mute.

Pure: it is handed the cards (id and address) and the last presence the history recorded of each card (history.last_presence: {id: (online, ts)},
written by the cycle at every change between on and off). That record is the one source used: it is what the cards show, it survives a
restart, and for a card that is off its time is the moment it was last seen on (state_cycle writes the instant of the drop, not the moment it
was noticed). A card on now answered now; a card off answered last at the time of its record; a card never recorded says nothing.

Mute: a confirmed network with cards, none of them on, whose newest known answer is older than QUIET_S. A network whose cards were never
recorded is not mute (nothing is known of it); a proposed or paused one is not either (nobody expects an answer from it)."""
import ipaddress

from .model import Network

QUIET_S = 24 * 3600


def _held(network: Network, ip) -> bool:
    try:
        return network.holds(ipaddress.IPv4Address(ip))
    except (ValueError, TypeError):
        return False


def tally(network: Network, cards, last: dict, now: float) -> dict:
    """{"cards": the cards the network holds, "on": how many of them are on now, "mute": see above}; `cards` are (id, address) pairs."""
    held = [cid for cid, ip in cards if _held(network, ip)]
    records = [last[cid] for cid in held if cid in last]
    on = sum(1 for online, _ in records if online)
    return {"cards": len(held), "on": on, "mute": network.state == "confirmed" and on == 0 and _quiet(records, now)}


def _quiet(records: list, now: float) -> bool:
    """The newest answer among the records (now for a card on) is older than QUIET_S; False when there is no record."""
    answered = [now if online else ts for online, ts in records]
    return bool(answered) and max(answered) <= now - QUIET_S
