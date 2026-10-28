"""When does the extender answer for a client? In the real network the answers alternate in stretches: the extender holds an address for a few cycles, then the
phone answers again for a longer while, with a few very long stretches (the durations are heavy tailed). The schedule is a list with one entry per scan cycle:
True = the extender answers for the client (the client stays silent), False = the client answers itself."""
import math
import random

CLAIM_MEDIAN = 8       # cycles: the middle duration of a stretch in which the extender answers (the real network: about 9 on the busiest address)
AWAY_MEDIAN = 15       # cycles: the middle duration of a stretch in which the client answers
CLAIM_SIGMA = 1.0
AWAY_SIGMA = 1.5
GLITCH_PROB = 0.10     # a stretch of exactly one cycle: the real network has changes that follow the previous one within a cycle (9 % of them)


def _duration(rng: random.Random, median: float, sigma: float) -> int:
    if rng.random() < GLITCH_PROB:
        return 1
    return max(1, round(rng.lognormvariate(math.log(median), sigma)))


def claim_schedule(rng: random.Random, cycles: int, claim_median: float = CLAIM_MEDIAN, away_median: float = AWAY_MEDIAN,
                   claim_sigma: float = CLAIM_SIGMA, away_sigma: float = AWAY_SIGMA) -> list[bool]:
    """The states of `cycles` cycles, starting with the client answering."""
    schedule, claimed = [], False
    while len(schedule) < cycles:
        median, sigma = (claim_median, claim_sigma) if claimed else (away_median, away_sigma)
        schedule.extend([claimed] * _duration(rng, median, sigma))
        claimed = not claimed
    return schedule[:cycles]


def run_lengths(schedule: list) -> list[tuple]:
    """[(state, how many cycles in a row)] for a schedule."""
    runs: list[tuple] = []
    for state in schedule:
        if runs and runs[-1][0] == state:
            runs[-1] = (state, runs[-1][1] + 1)
        else:
            runs.append((state, 1))
    return runs


HANDOFF_PROB = 0.1     # after a stretch held by an extender: the phone goes straight to the other extender (a sticky roam that skips the router) instead of passing through the router's own Wi-Fi first


def _next_state(rng: random.Random, state: str | None, extenders: tuple[str, ...], handoff_prob: float) -> str | None:
    """The geography is extender 1 - router - extender 2, the router in the middle with its own Wi-Fi (there the phone answers for itself): from answering itself the phone is taken by
    either extender, equally likely (same distance); from an extender it goes back through the router's Wi-Fi, and only rarely straight to the other extender."""
    if state is None:
        return rng.choice(extenders)
    others = [e for e in extenders if e != state]
    return rng.choice(others) if others and rng.random() < handoff_prob else None


def roam_schedule(rng: random.Random, cycles: int, extenders: tuple[str, ...] = ("ext", "ext2"), handoff_prob: float = HANDOFF_PROB,
                  claim_median: float = CLAIM_MEDIAN, away_median: float = AWAY_MEDIAN, claim_sigma: float = CLAIM_SIGMA, away_sigma: float = AWAY_SIGMA) -> list[str | None]:
    """The holder of the phone in each of `cycles` cycles: None (the phone is on the router's Wi-Fi, in the middle, and answers itself) or the name of the extender that answers for it, one at a
    time (the extenders are far from each other), starting on the router's Wi-Fi."""
    schedule, state = [], None
    while len(schedule) < cycles:
        median, sigma = (away_median, away_sigma) if state is None else (claim_median, claim_sigma)
        schedule.extend([state] * _duration(rng, median, sigma))
        state = _next_state(rng, state, extenders, handoff_prob)
    return schedule[:cycles]
