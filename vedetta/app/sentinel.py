"""Sentinel: which changes of the network become a message for the person, and when. Pure: it is handed what happened (a new device,
a card going offline or coming back) and the time, and it says what to send now; sending and saving are the caller's.

Every change is an EVENT with a state: "pending" (still being judged), "sent", or "suppressed" with a reason. Nothing is sent the
moment it happens: once per cycle `due` gathers what is ready, so one cycle gives at most one message, in sections.

The rules (the person sees few alarms, and none of them false):
  - new device: ready at once;
  - down: only for a card the person watches ("tell me if it disappears"). The event is born at the first cycle the card is offline
    and is ready only when the card is STILL offline after `down_delay_s` (plus `sleep_s` for a card that may sleep: a phone, a
    tablet: "sleeping" before "down"). A card that comes back before that never gives a "down" (suppressed: returned);
  - back: only after a "down" that was really SENT; never after one that was suppressed (otherwise "back" would be the first and
    only thing the person hears of an absence they were never told about);
  - flapping: a card with at least `flap_count` changes in `flap_window_s` is "unstable": its "down" waits longer, `unstable_wait_s`
    of absence in a row (and is suppressed if it comes back meanwhile), so a flaky Wi-Fi device does not send a message every few
    minutes, and one that then really goes away is still told (the user, 17/11: it waited up to an hour);
  - silence: a card the person silenced for N hours sends nothing until then (its events are suppressed: silenced);
  - one "down" per absence: a second "offline" without an "online" between them adds nothing.
The state is plain JSON (to_json / from_json), so it survives a restart: a "down" that was sent before the restart still gives its
"back" after."""
from dataclasses import dataclass

NEW, DOWN, BACK = "new", "down", "back"
PENDING, SENT, SUPPRESSED = "pending", "sent", "suppressed"
OPEN_DOWN_MAX_S = 90 * 86400    # a sent "down" waits for its "back" this long at most (the card may have been deleted while away), as long as the history
KEEP_DONE_S = 7 * 86400          # finished events are kept a week (the page can show them), then dropped
MAX_EVENTS = 2000                # and never more than this many, the oldest finished ones go first


@dataclass(frozen=True)
class Rules:
    down_delay_s: float = 300.0       # a watched card is "down" only after 5 minutes offline
    sleep_s: float = 300.0            # a card that may sleep (a phone) is "sleeping" 5 minutes more: 10 in all (the user, 17/11: 35 was too late)
    flap_count: int = 3               # at least 3 changes ...
    flap_window_s: float = 3600.0     # ... in one hour: unstable
    unstable_wait_s: float = 900.0    # an unstable card is "down" after 15 minutes of absence in a row (never less than its usual wait)


DEFAULT_RULES = Rules()


class Sentinel:
    def __init__(self, rules: Rules = DEFAULT_RULES):
        self.rules = rules
        self.events: list[dict] = []          # {"id", "kind", "card", "at", "state", "reason"?, "params"}
        self.changes: dict[str, list] = {}    # card -> times of its last online/offline changes (for flapping)
        self.sent_at: dict[str, float] = {}   # card -> time of the last message that spoke of it (for the silence)
        self.silenced: dict[str, float] = {}  # card -> silent until this time
        self._seq = 0

    # ---- what happened ----
    def new_device(self, card: str, now: float, **params) -> None:
        """A device never seen before (one per MAC: the caller already warns once)."""
        self._add(NEW, card, now, params)

    def presence(self, card: str, online: bool, now: float, *, watched: bool, **params) -> None:
        """A card changed between online and offline (the caller passes only real changes, after its tolerance to missed checks)."""
        self._note_change(card, now)
        open_down = self._open_down(card)
        if not online:
            if watched and open_down is None:
                self._add(DOWN, card, now, params)
            return
        if open_down is None:
            return
        if open_down["state"] == PENDING:
            self._finish(open_down, now, SUPPRESSED, "returned")
        elif open_down["state"] == SENT and watched:
            self._add(BACK, card, now, {**params, "away_s": round(now - open_down["at"])})
        open_down["closed"] = True                     # this absence is over: the next "offline" is a new one

    def silence(self, card: str, until: float) -> None:
        self.silenced[card] = until

    # ---- what to send ----
    def due(self, now: float, still_offline, may_sleep, still_watched=lambda card: True) -> list[dict]:
        """The events ready to be sent now, oldest first; the ones that can never be sent are suppressed here. `still_offline(card)`,
        `may_sleep(card)` and `still_watched(card)` are asked of the caller (the live state of the card, its category, its bell: a "down"
        whose bell was switched off, or whose card was deleted, while it waited is never sent)."""
        ready = []
        for ev in self.events:
            if ev["state"] != PENDING:
                continue
            verdict = self._judge(ev, now, still_offline, may_sleep, still_watched)
            if verdict is True:
                ready.append(ev)
            elif verdict:
                self._finish(ev, now, SUPPRESSED, verdict)
        return ready

    def mark_sent(self, events: list[dict], now: float) -> None:
        for ev in events:
            self._finish(ev, now, SENT)
            self.sent_at[ev["card"]] = now

    def forget_gone(self, present, now: float) -> None:
        """The "down" events of cards that no longer exist (deleted or ignored while away) are closed: a card id is its address, and a new card at
        the same address must not inherit them (18/11 review 3). One still pending is suppressed with the reason "removed"."""
        for ev in self.events:
            if ev["kind"] != DOWN or ev["card"] in present or ev.get("closed") or ev["state"] == SUPPRESSED:
                continue
            if ev["state"] == PENDING:
                self._finish(ev, now, SUPPRESSED, "removed")
            ev["closed"] = True

    def unstable(self, card: str, now: float) -> bool:
        recent = [t for t in self.changes.get(card, ()) if now - t <= self.rules.flap_window_s]
        return len(recent) >= self.rules.flap_count

    def prune(self, now: float) -> None:
        """Drops finished events older than a week, and the oldest finished ones beyond MAX_EVENTS; old change times, silences and message times. A "down"
        that was sent and whose absence is still open is never dropped: its "back" needs it, however long the device stays away (18/11 review)."""
        self.events = [e for e in self.events if _kept(e, now) or now - e.get("done_at", e["at"]) <= KEEP_DONE_S]
        while len(self.events) > MAX_EVENTS and any(not _kept(e, now) for e in self.events):
            self.events.remove(next(e for e in self.events if not _kept(e, now)))
        self.changes = {c: kept for c, ts in self.changes.items() if (kept := [t for t in ts if now - t <= self.rules.flap_window_s])}
        self._prune_times(now)

    def _prune_times(self, now: float) -> None:
        """The silences that ended, and the times of messages older than a week (one key per card ever spoken of: it must not grow for ever)."""
        self.silenced = {c: t for c, t in self.silenced.items() if t > now}
        self.sent_at = {c: t for c, t in self.sent_at.items() if now - t <= KEEP_DONE_S}

    # ---- the rules ----
    def _judge(self, ev: dict, now: float, still_offline, may_sleep, still_watched):
        """True = send now; False = not yet; a string = never (the reason it is suppressed)."""
        card = ev["card"]
        if self.silenced.get(card, 0) > now:
            return "silenced"
        if ev["kind"] != DOWN:
            return True
        if not still_watched(card):
            return "unwatched"
        if not still_offline(card):
            return "returned"
        wait = self.rules.down_delay_s + (self.rules.sleep_s if may_sleep(card) else 0)
        if self.unstable(card, now):
            wait = max(wait, self.rules.unstable_wait_s)
        return now - ev["at"] >= wait

    def _open_down(self, card: str) -> dict | None:
        """The "down" of the current absence of the card (pending or sent), if any."""
        for ev in reversed(self.events):
            if ev["card"] == card and ev["kind"] == DOWN:
                return None if ev.get("closed") or ev["state"] == SUPPRESSED else ev
        return None

    def _note_change(self, card: str, now: float) -> None:
        self.changes.setdefault(card, []).append(now)

    def _add(self, kind: str, card: str, now: float, params: dict) -> None:
        self._seq += 1
        self.events.append({"id": self._seq, "kind": kind, "card": card, "at": now, "state": PENDING, "params": dict(params)})

    @staticmethod
    def _finish(ev: dict, now: float, state: str, reason: str | None = None) -> None:
        ev["state"] = state
        ev["done_at"] = now
        if reason:
            ev["reason"] = reason

    # ---- saving ----
    def to_json(self) -> dict:
        return {"events": self.events, "changes": self.changes, "sent_at": self.sent_at, "silenced": self.silenced, "seq": self._seq}

    @classmethod
    def from_json(cls, data, rules: Rules = DEFAULT_RULES) -> "Sentinel":
        """From a saved state; anything malformed starts empty (a lost queue of alerts is better than a wrong one)."""
        s = cls(rules)
        if not isinstance(data, dict):
            return s
        try:
            s.events = [e for e in data.get("events") or [] if isinstance(e, dict) and {"id", "kind", "card", "at", "state"} <= e.keys()]
            s.changes = {str(c): [float(t) for t in ts] for c, ts in (data.get("changes") or {}).items()}
            s.sent_at = {str(c): float(t) for c, t in (data.get("sent_at") or {}).items()}
            s.silenced = {str(c): float(t) for c, t in (data.get("silenced") or {}).items()}
            s._seq = max([int(data.get("seq") or 0), *(int(e["id"]) for e in s.events)])
        except (TypeError, ValueError, AttributeError):
            return cls(rules)
        return s


def _kept(ev: dict, now: float) -> bool:
    """An event prune() never drops: one still being judged, or a "down" that was sent and not yet closed by its "back" (up to OPEN_DOWN_MAX_S:
    a card deleted while away never closes its "down")."""
    open_down = ev["kind"] == DOWN and ev["state"] == SENT and not ev.get("closed") and now - ev.get("done_at", ev["at"]) <= OPEN_DOWN_MAX_S
    return ev["state"] == PENDING or open_down
