"""Cycle statistics (app/cyclestats.py): chained cycles are warned once per 10 minutes with their causes, a slow cycle is warned, the hourly
summary is written and kept for the export, and a forced cycle is not counted as a chain."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "vedetta"))
from app import cyclestats  # noqa: E402

warnings, infos = [], []
cyclestats.logger.warning = lambda msg, *a, **k: warnings.append(msg % a if a else msg)
cyclestats.logger.info = lambda msg, *a, **k: infos.append(msg % a if a else msg)

s = cyclestats.CycleStats()
for _ in range(cyclestats.CHAIN_WARN - 1):
    s.note_start("mqtt", 10.0)
s.note_start("force", 10.0)                                   # forced by hand: never a chain
s.note_start("", 10.0)                                        # the timer: never a chain
assert warnings == [] and s.total_chains == 0
s.note_start("ip_changed", 10.0)
assert len(warnings) == 1 and "mqtt x3" in warnings[0] and "ip_changed x1" in warnings[0] and "10 s" in warnings[0], warnings
assert s.total_chains == 1
s.note_start("mqtt", 10.0)                                    # within 10 minutes: not repeated
assert len(warnings) == 1 and s.total_chains == 1

s.note_end(time.monotonic() - 1.0, 254, 40, None)             # a normal cycle
assert s.total_cycles == 1 and 1.0 <= s.slowest < 2.0 and len(warnings) == 1
s.note_end(time.monotonic() - 45.0, 254, 40, None)            # a slow one
assert len(warnings) == 2 and "Controllo lento: 45 s (254 indirizzi" in warnings[1], warnings
assert s.slowest >= 45.0 and s.last_summary is None and infos == []

s._stat_since -= cyclestats.SUMMARY_S + 1                     # an hour has passed: the summary is written and the counters restart
s.note_end(time.monotonic() - 2.0, 300, 50, None)
assert len(infos) == 1 and s.last_summary["cycles"] == 3 and s.last_summary["chains"] == 1, s.last_summary
assert s.last_summary["addresses_asked"] == (254 + 254 + 300) // 3 and s._stat == []
s._stat_since -= cyclestats.SUMMARY_S + 1
s.note_end(time.monotonic() - 2.0, 10, 5, {"network": "10.0.0.0/16", "done": 3, "total": 9})
assert "3 blocchi su 9" in infos[1] and s.last_summary["cycles"] == 1
print("TUTTO OK")
