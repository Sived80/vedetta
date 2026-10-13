"""The atomic write of a file: a temporary file in the same folder, then os.replace. A crash or an interruption in the middle of the write leaves the previous file intact (never a truncated one)."""
import os
import tempfile
from pathlib import Path


def _sync_folder(folder: Path) -> None:
    """Best effort: make the new name durable (the sequence that is documented as crash-safe is temp file, fsync, rename, fsync of the folder). Not every system lets a folder be opened: then nothing is lost."""
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def write_atomic(path: Path, write, prefix: str, *, folder: Path | None = None, newline: str | None = None, durable: bool = True) -> None:
    """`write(f)` writes the content to the open text file (UTF-8). The temporary file is made in `folder` (default: the folder of `path`) with the given name prefix."""
    folder = folder or path.parent
    folder.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            write(f)
            if durable:
                f.flush()
                os.fsync(f.fileno())          # the data is on disk BEFORE the rename: a power cut must not leave the new name with an empty file
        os.replace(tmp, path)
        if durable:
            _sync_folder(path.parent)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
