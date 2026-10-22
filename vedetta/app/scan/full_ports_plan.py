"""The plan of the full port scan of a slow device, in the background: blocks of ports (each with its own limit, so a slow device never loses a whole run to one timeout), how many blocks a run may do, how long to wait after a block
that timed out (a day, then two, four, seven: capped, as the retry of any background job), and when a card is due for the scan. Pure functions and numbers: what is sent, and when, is in rescan_background.py."""

LAST_PORT = 65535
BLOCK_SIZE = 4096
BLOCK_TIMEOUT_S = 300       # a block of 4096 ports took 45-76 s at -T3 on a slow device in the tests of 22 Oct
BLOCKS_PER_RUN = 8          # a run stops after these (about eight minutes on a slow device) and goes on at the next deep search
PAUSE_S = 20                # between two blocks of the same run
RETRY_BASE_S = 86400
RETRY_MAX_S = 7 * 86400


def block(start: int) -> tuple[int, int]:
    """The first and the last port of the block that begins at `start`."""
    return start, min(start + BLOCK_SIZE - 1, LAST_PORT)


def retry_delay(failures: int) -> int:
    """Seconds to wait after the n-th failure in a row: a day, two, four, seven, never more."""
    return min(RETRY_BASE_S * 2 ** max(int(failures or 1) - 1, 0), RETRY_MAX_S)


def is_due(info: dict, now: float, every: float) -> bool:
    """Is the card due for the scan? Not while it waits after a failure; otherwise when the scan is in progress, was never finished with its services read, or is older than `every`."""
    if now < float(info.get("full_ports_retry_at") or 0):
        return False
    return bool(info.get("full_ports_next")) or now - float(info.get("full_ports_at") or 0) > every or not info.get("services_at")
