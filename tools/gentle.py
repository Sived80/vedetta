"""Keeps the tests and the gate from taking the computer of the person who runs them (it froze twice, once until it had to be switched off). The process limits itself to a few logical processors BEFORE it
starts any child, and a child inherits that limit, so everything the gate starts (the tests, radon, the structure check) shares those few processors and the rest of the machine stays free.
Windows only; elsewhere (a CI runner, a Linux box) it does nothing. VEDETTA_TEST_CPUS changes the number (0 = no limit)."""
import os

DEFAULT_CPUS = 8          # a middle way: about 40% of a 20-processor machine at most, with a low priority (4 made the gate last 15 minutes, all of them froze the computer)


def wanted_cpus() -> int:
    text = os.environ.get("VEDETTA_TEST_CPUS", "")
    return int(text) if text.strip().isdigit() else DEFAULT_CPUS


def limit_cpus(count: int | None = None) -> int:
    """Restricts this process, and so every process it starts, to the last `count` logical processors (the first ones are left to the system). Returns the mask applied, 0 when nothing was done."""
    count = wanted_cpus() if count is None else count
    cpus = os.cpu_count() or 1
    if os.name != "nt" or count <= 0 or cpus <= count or cpus > 64:
        return 0
    mask = ((1 << count) - 1) << (cpus - count)
    kernel, handle = _kernel()
    return mask if kernel.SetProcessAffinityMask(handle, mask) else 0


def _kernel():
    """kernel32 with the types of the calls declared (without them a 64-bit handle is cut and the call fails), and the handle of this process."""
    import ctypes
    kernel = ctypes.windll.kernel32
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel.GetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    return kernel, kernel.GetCurrentProcess()


def current_mask() -> int:
    """The processors this process may use, as a bit mask (0 where it cannot be read)."""
    if os.name != "nt":
        return 0
    import ctypes
    kernel, handle = _kernel()
    process, system = ctypes.c_size_t(0), ctypes.c_size_t(0)
    kernel.GetProcessAffinityMask(handle, ctypes.byref(process), ctypes.byref(system))
    return process.value


MIN_FREE_GB = 8.0          # no new test starts while less memory than this is free


def free_memory_gb() -> float:
    """Free physical memory in GB (Windows; elsewhere a large number: the guard does nothing)."""
    if os.name != "nt":
        return 1e9
    import ctypes

    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong), ("totalpage", ctypes.c_ulonglong),
                    ("availpage", ctypes.c_ulonglong), ("totalvirt", ctypes.c_ulonglong), ("availvirt", ctypes.c_ulonglong), ("availext", ctypes.c_ulonglong)]
    status = Status()
    status.length = ctypes.sizeof(Status)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return status.avail / 1024 ** 3


def wait_for_memory(minimum: float = MIN_FREE_GB, read=free_memory_gb, sleep=None, patience_s: float = 600.0) -> float:
    """Waits (at most `patience_s`) until at least `minimum` GB are free; returns the seconds waited. A test that starts when memory is short makes the whole computer crawl."""
    import time
    sleep = sleep or time.sleep
    waited = 0.0
    while read() < minimum and waited < patience_s:
        sleep(2.0)
        waited += 2.0
    return waited


DEFAULT_PROCESS_MB = 2048     # no single test may hold more than this (a runaway loop gets a MemoryError instead of filling the computer)
DEFAULT_JOB_MB = 8192         # nor all the tests together


def cap_memory(process_mb: int | None = None, job_mb: int | None = None) -> bool:
    """Puts this process, and every process it starts, in a Windows job with a memory ceiling per process and in total (and the children die with the job: no orphan is left running if the parent is
    killed). The ceilings are in MB, VEDETTA_TEST_MEM_MB changes the one per process (0 = no ceiling). Returns True when the ceiling was set; nothing is done outside Windows."""
    text = os.environ.get("VEDETTA_TEST_MEM_MB", "")
    process_mb = int(text) if text.strip().isdigit() else (DEFAULT_PROCESS_MB if process_mb is None else process_mb)
    job_mb = DEFAULT_JOB_MB if job_mb is None else job_mb
    if os.name != "nt" or process_mb <= 0:
        return False
    import ctypes
    from ctypes import wintypes

    class Basic(ctypes.Structure):
        _fields_ = [("user_time", ctypes.c_longlong), ("job_user_time", ctypes.c_longlong), ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                    ("active", wintypes.DWORD), ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

    class Extended(ctypes.Structure):
        _fields_ = [("basic", Basic), ("io", ctypes.c_ulonglong * 6), ("process_limit", ctypes.c_size_t), ("job_limit", ctypes.c_size_t), ("peak_process", ctypes.c_size_t), ("peak_job", ctypes.c_size_t)]

    kernel, handle = _kernel()
    kernel.CreateJobObjectW.restype = ctypes.c_void_p
    kernel.SetInformationJobObject.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    job = kernel.CreateJobObjectW(None, None)
    info = Extended()
    info.basic.flags = 0x100 | 0x200 | 0x2000          # per-process memory, job memory, kill the processes when the job is closed
    info.process_limit, info.job_limit = process_mb * 1024 * 1024, max(job_mb, process_mb) * 1024 * 1024
    if not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        return False
    return bool(kernel.AssignProcessToJobObject(job, handle))
