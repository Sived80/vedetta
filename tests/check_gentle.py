"""The limit that keeps the tests from saturating the computer (tools/gentle.py): on Windows a process that limits itself to N processors passes the limit to the processes it starts; elsewhere nothing is
done. The check runs in child processes, so the limit never touches the process that runs this test."""
import os
import subprocess
import sys

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
sys.path.insert(0, TOOLS)
import gentle  # noqa: E402

CHILD = "import sys; sys.path.insert(0, sys.argv[1]); import gentle; applied = gentle.limit_cpus(int(sys.argv[2])); print(applied, gentle.current_mask())"
GRANDCHILD = "import sys, subprocess; sys.path.insert(0, sys.argv[1]); import gentle; gentle.limit_cpus(int(sys.argv[2])); print(subprocess.run([sys.executable, '-c', 'import sys; sys.path.insert(0, sys.argv[1]); import gentle; print(gentle.current_mask())', sys.argv[1]], capture_output=True, text=True).stdout.strip())"


def run(code, count):
    out = subprocess.run([sys.executable, "-c", code, TOOLS, str(count)], capture_output=True, text=True, timeout=60)
    return out.stdout.strip()


# the number wanted: the default, the environment, a bad value
saved = os.environ.pop("VEDETTA_TEST_CPUS", None)
assert gentle.wanted_cpus() == gentle.DEFAULT_CPUS
os.environ["VEDETTA_TEST_CPUS"] = "2"
assert gentle.wanted_cpus() == 2
os.environ["VEDETTA_TEST_CPUS"] = "no"
assert gentle.wanted_cpus() == gentle.DEFAULT_CPUS
os.environ["VEDETTA_TEST_CPUS"] = "0"
assert gentle.wanted_cpus() == 0 and gentle.limit_cpus() == 0, "0 means no limit"
if saved is None:
    del os.environ["VEDETTA_TEST_CPUS"]
else:
    os.environ["VEDETTA_TEST_CPUS"] = saved

# which processors: the fastest class first, and inside a class the highest numbers first (the lowest are left to the system). A computer with performance
# and efficiency cores (a 13th generation Intel: 0-11 performance, 12-19 efficiency) must not be given the slow ones; with one class it is the last N, as it always was.
hybrid = [(i, 1) for i in range(12)] + [(i, 0) for i in range(12, 20)]
assert gentle.pick_mask(hybrid, 8) == 0xFF0, "8 of the 12 performance processors, the last 8 of that class"
assert gentle.pick_mask(hybrid, 12) == 0xFFF and gentle.pick_mask(hybrid, 2) == 0xC00
assert gentle.pick_mask(hybrid, 14) == 0xFFF | (1 << 19) | (1 << 18), "only after the fast ones are all taken does it take the slow ones, highest first"
assert gentle.pick_mask([(i, 0) for i in range(8)], 4) == 0xF0, "one class: the last N processors, as before"
assert gentle.pick_mask([(i, 0) for i in range(8)], 0) == 0
# the answer of Windows (SYSTEM_CPU_SET_INFORMATION, 32 bytes each: size, type, id, group, logical index, core, cache, numa, efficiency class, flags, scheduling class, tag)
import struct  # noqa: E402


def cpu_set(logical, efficiency, kind=0):
    return struct.pack("<IIIHBBBBBBBxxx", 32, kind, 256 + logical, 0, logical, logical // 2, 0, 0, efficiency, 0, 0) + b"\0" * 8


blob = cpu_set(0, 1) + cpu_set(1, 1) + cpu_set(2, 0) + cpu_set(3, 0, kind=9) + cpu_set(4, 0)
assert len(cpu_set(0, 1)) == 32
assert gentle.parse_cpu_sets(blob) == [(0, 1), (1, 1), (2, 0), (4, 0)], "an entry of another type is skipped"
assert gentle.parse_cpu_sets(b"") == [] and gentle.parse_cpu_sets(b"\x01\x02") == [], "nothing or rubbish: no processors, no crash"

cpus = os.cpu_count() or 1
if os.name == "nt" and 2 < cpus <= 64:
    classes = gentle.cpu_classes() or [(i, 0) for i in range(cpus)]
    assert len(classes) == cpus and {i for i, _ in classes} == set(range(cpus)), classes
    expected = gentle.pick_mask(classes, 2)
    assert bin(expected).count("1") == 2
    applied, mask = run(CHILD, 2).split()
    assert int(applied) == expected and int(mask) == expected, (applied, mask, expected)
    assert int(run(GRANDCHILD, 2)) == expected, "a process started by a limited process must be limited too"
    assert run(CHILD, 0).split()[0] == "0", "no limit when 0 is asked"
else:
    assert gentle.limit_cpus(2) == 0, "nothing is done outside Windows (or on a machine with too few processors)"

# the memory guard: no wait when enough is free; it waits (in steps) while little is free, and it gives up after the patience
steps = []
assert gentle.wait_for_memory(8, read=lambda: 20.0, sleep=steps.append) == 0.0 and not steps
levels = iter([2.0, 3.0, 9.0])
assert gentle.wait_for_memory(8, read=lambda: next(levels), sleep=steps.append) == 4.0 and len(steps) == 2, steps
assert gentle.wait_for_memory(8, read=lambda: 1.0, sleep=steps.append, patience_s=6.0) == 6.0, "it must give up, not wait for ever"
assert isinstance(gentle.free_memory_gb(), float) and gentle.free_memory_gb() > 0

# the memory ceiling (in a child process, so this one is not capped): beyond it an allocation fails with a MemoryError instead of filling the computer
CAP = """
import sys
sys.path.insert(0, sys.argv[1])
import gentle
ok = gentle.cap_memory(300, 400)
try:
    block = bytearray(900 * 1024 * 1024)
    print(ok, 'NO-ERROR')
except MemoryError:
    print(ok, 'MemoryError')
"""
out = subprocess.run([sys.executable, "-c", CAP, TOOLS], capture_output=True, text=True, timeout=60).stdout.split()
if os.name == "nt":
    assert out == ["True", "MemoryError"], out
else:
    assert out[0] == "False", out
print("TUTTO OK")
