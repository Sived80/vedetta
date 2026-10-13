"""Update test on a COPY of real data: the folder of data of an installation (what /data holds) is copied, opened by the old code, by the new code and again by the old code (the way back), and what must survive is compared.

    python tools/upgrade_check.py <data folder> [--old origin/main] [--new .]

The original folder is never touched: every step works on a copy in a temporary folder. The old code is taken from a git revision (git archive), the new one from the working tree. A step is a fresh process (the data
folder is read when the modules are imported). What is compared (inventory): the integrity of the database, the rows of every table that the old code knows, the cards of devices.yaml (id, name, address, the choices of the user)
and the other files of the folder. Going forward the new code may add tables, columns and keys; going back the old code must still open everything and find the same rows.
Exit code 0 = all as it must be; 1 = something was lost or does not open."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Run by the old and by the new code (a fresh process each time) on the copy; prints the inventory as JSON.
INVENTORY = r'''
import json, os, sqlite3, sys
from pathlib import Path
data = Path(os.environ["VEDETTA_DATA_DIR"])
if sys.argv[1:] == ["upgrade"]:
    from app.storage import devices_config
    if hasattr(devices_config, "ensure_seq_safely"):
        devices_config.ensure_seq_safely()
    import app.storage.history  # noqa: F401  (creating the History opens the database and adds the tables the version needs)
else:
    import app.storage.history  # noqa: F401
from app.storage import devices_config
con = sqlite3.connect(str(data / "vedetta.db"))
tables = {r[0]: con.execute('select count(*) from "%s"' % r[0]).fetchone()[0] for r in con.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by 1")}
out = {"integrity": con.execute("pragma integrity_check").fetchone()[0], "tables": tables}
out["devices"] = {d["id"]: {k: d.get(k) for k in ("ip", "name", "type_user", "brand_user", "mobile", "adapter", "ignored")} for d in devices_config.load_devices()}
out["files"] = sorted(p.name for p in data.iterdir() if p.is_file() and not p.name.startswith("vedetta.db-") and ".bak" not in p.name)
print("INVENTORY" + json.dumps(out, sort_keys=True))
'''


def compare(before: dict, after: dict, direction: str) -> list[str]:
    """What was lost between two inventories (pure). Going forward ("forward") tables and files may appear; nothing that was there may disappear or shrink; going back the same."""
    problems = []
    if after.get("integrity") != "ok":
        problems.append("%s: the database is not ok: %s" % (direction, after.get("integrity")))
    for table, rows in before["tables"].items():
        if table not in after["tables"]:
            problems.append("%s: table %s is gone" % (direction, table))
        elif after["tables"][table] < rows:
            problems.append("%s: table %s lost rows (%d -> %d)" % (direction, table, rows, after["tables"][table]))
    for device_id, card in before["devices"].items():
        if device_id not in after["devices"]:
            problems.append("%s: the card %s is gone" % (direction, device_id))
        elif after["devices"][device_id] != card:
            problems.append("%s: the card %s changed: %s -> %s" % (direction, device_id, card, after["devices"][device_id]))
    problems += ["%s: the file %s is gone" % (direction, name) for name in before["files"] if name not in after["files"]]
    return problems


def _run(code_root: Path, work: Path, step: str) -> dict:
    env = dict(os.environ, VEDETTA_DATA_DIR=str(work), PYTHONPATH=str(code_root), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-W", "ignore", "-c", INVENTORY, step], cwd=code_root, env=env, capture_output=True, text=True, timeout=600)
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("INVENTORY")), None)
    if done.returncode != 0 or line is None:
        raise RuntimeError("step %s failed (%s): %s" % (step, done.returncode, (done.stderr or done.stdout)[-600:]))
    return json.loads(line[len("INVENTORY"):])


def _checkout(ref: str, into: Path) -> Path:
    """The code of a git revision (or the working tree when ref is "."), as a folder with the package `app`."""
    if ref == ".":
        return ROOT / "vedetta"
    archive = subprocess.run(["git", "archive", ref, "vedetta/app"], cwd=ROOT, capture_output=True, check=True).stdout
    tar_path = into / "code.tar"
    tar_path.write_bytes(archive)
    with tarfile.open(tar_path) as tar:
        tar.extractall(into, filter="data")
    return into / "vedetta"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("data")
    ap.add_argument("--old", default="origin/main")
    ap.add_argument("--new", default=".")
    args = ap.parse_args()
    source = Path(args.data)
    if not (source / "vedetta.db").exists():
        print("no vedetta.db in", source)
        return 2
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        tmp_path = Path(tmp)
        work = tmp_path / "data"
        shutil.copytree(source, work)                      # the original is never opened again
        for name in ("old", "new"):
            (tmp_path / name).mkdir()
        old_code = _checkout(args.old, tmp_path / "old")
        new_code = _checkout(args.new, tmp_path / "new")
        start = _run(old_code, work, "read")
        forward = _run(new_code, work, "upgrade")
        back = _run(old_code, work, "read")
    problems = compare(start, forward, "forward") + compare(start, back, "back")
    print("cards:", len(start["devices"]), "| tables before:", len(start["tables"]), "after the new code:", len(forward["tables"]), "| new tables:", sorted(set(forward["tables"]) - set(start["tables"])))
    print("files only after the new code:", sorted(set(forward["files"]) - set(start["files"])))
    print("\n".join(problems) if problems else "UPDATE AND WAY BACK: ALL AS IT MUST BE")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
