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

cpus = os.cpu_count() or 1
if os.name == "nt" and 2 < cpus <= 64:
    expected = ((1 << 2) - 1) << (cpus - 2)
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
