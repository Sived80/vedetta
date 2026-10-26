"""The rules that keep the gate from saying «green» without proof (used by tools/gate.py and tools/run_tests.py; tested in tests/check_gate_rules.py). Pure functions."""
import re

_SKIP = re.compile(r"^SKIP\b", re.M)
_GOLDEN = "tests/golden/"
_PATH = re.compile(r'^(?:\?\?|[ MADRCU?!]{1,2})\s+(?:"?[^"]*"?\s+->\s+)?"?(?P<path>[^"]+?)"?\s*$')


def worker_counts(cpus: int, serial: bool, python_cap: int, ui_cap: int) -> tuple[int, int]:
    """(Python tests, UI tests) that run together: the caps asked for, limited by the machine (the Python pool leaves 6 processors to the system, the UI pool takes
    a quarter of them), never fewer than one; a CI runner with 2 cores gets 1 + 1, and `serial` gets 1 + 1 whatever the machine."""
    if serial:
        return 1, 1
    return max(1, min(python_cap, cpus - 6)), max(1, min(ui_cap, cpus // 4))


def is_skip(stdout: str) -> bool:
    """A test that exited 0 but printed a line starting with SKIP did not test anything (jsdom or a browser is missing)."""
    return bool(_SKIP.search(stdout or ""))


def dirty_goldens(porcelain: str) -> list[str]:
    """The golden files that were changed, created or removed, from `git status --porcelain`: a golden is regenerated on purpose only (see PROJECT rules), never by the run itself."""
    found = []
    for line in (porcelain or "").splitlines():
        m = _PATH.match(line)
        if m and m.group("path").startswith(_GOLDEN):
            found.append(m.group("path"))
    return sorted(found)


def golden_problem(porcelain: str, allowed: bool) -> str | None:
    """The message for goldens that a run changed or created, None when there are none or when it is on purpose (--allow-golden-update, with the proof in the commit message)."""
    dirty = dirty_goldens(porcelain)
    if not dirty or allowed:
        return None
    return f"golden changed or created: {', '.join(dirty[:3])}{' ...' if len(dirty) > 3 else ''} (use --allow-golden-update when it is on purpose)"


def worst_complexity(radon_output: str) -> list[int]:
    """The five highest cognitive complexities (grade C and worse) in the output of `radon cc -s -n C`, lowest first."""
    return sorted(int(m.group(1)) for m in re.finditer(r"\((\d+)\)\s*$", radon_output or "", re.M))[-5:]


def complexity_problem(worst: list[int], base_worst: list[int]) -> str | None:
    """None when nothing got worse than the base: neither the worst function nor the number of complex functions."""
    if not worst or not base_worst:
        return None
    if worst[-1] > base_worst[-1]:
        return f"max complexity {base_worst[-1]} -> {worst[-1]}"
    if len(worst) > len(base_worst) or sum(worst) > sum(base_worst):
        return f"more complex functions ({base_worst} -> {worst})"
    return None


def folder_state(folder) -> dict:
    """{name: (size, modified time in ns)} of the files of a folder, {} if it does not exist: taken before and after the tests."""
    state = {}
    if folder.is_dir():
        for item in folder.iterdir():
            if item.is_file():
                info = item.stat()
                state[item.name] = (info.st_size, info.st_mtime_ns)
    return state


def folder_problem(before: dict, after: dict) -> str | None:
    """None when the folder is the same; otherwise the names of the files that appeared, changed or disappeared."""
    names = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    return "the tests touched the real data folder: " + ", ".join(names[:5]) if names else None


NESTING_KEYS = ("deep3", "deep4", "deep5", "js_deep")


def nesting_problem(now: dict, base: dict | None) -> str | None:
    """None when no count of deeply nested functions or lines went up since the base (a ratchet: it can only go down); the base may not have the counts yet."""
    if not base:
        return None
    worse = [f"{key} {base[key]} -> {now[key]}" for key in NESTING_KEYS if key in base and now.get(key, 0) > base[key]]
    return "nesting got worse: " + ", ".join(worse) if worse else None


def deep_problem(found: set, allowed: dict) -> str | None:
    """None when every function nested too deep is on the list of allowed ones and every allowed one is still that deep (a list that does not shrink with the code is no list)."""
    new = sorted(found - set(allowed))
    stale = sorted(set(allowed) - found)
    parts = []
    if new:
        parts.append("nested more than 3 levels: " + ", ".join(new[:4]))
    if stale:
        parts.append("no longer deep, take them off the list: " + ", ".join(stale[:4]))
    return "; ".join(parts) or None
