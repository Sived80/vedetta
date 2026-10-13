"""Tolerant, lazy reading of the text tables the kernel exposes (/proc/net/route, /proc/net/arp, /proc/self/status). The file may not be there (not Linux, a restricted container): the table is then empty,
never an error, and the first time a path cannot be read it is told at debug level (an empty answer without a trace hides a fault). The lines are read one at a time, as the callers always did: a caller that
stops at the first line it wants never reads (or decodes) the rest. With the default errors="strict" a decoding error (a ValueError) goes up to the caller; with errors="ignore" the bad bytes are dropped."""
import itertools
from collections.abc import Iterator

from .applog import logger

_unreadable: set[str] = set()      # paths already told, so a table read every few seconds does not fill the log


def lines(path, errors: str = "strict") -> Iterator[str]:
    """The lines of the file, one at a time (each with its line end); nothing when it cannot be opened or read."""
    try:
        with open(path, encoding="ascii", errors=errors) as f:
            yield from f
    except OSError:
        if str(path) not in _unreadable:
            _unreadable.add(str(path))
            logger.debug("Kernel table not readable: %s", path)


def table(path, header: int = 1, errors: str = "strict") -> Iterator[list[str]]:
    """The rows of a whitespace-separated table, each split in columns, without its first `header` lines."""
    for line in itertools.islice(lines(path, errors), header, None):
        yield line.split()
