"""Çalışan üretimi durdurma: iş kuyruğunun başlattığı alt süreçleri (ffmpeg, HyperFrames/Remotion, Claude Code...)
izler ve istenince süreç ağacıyla birlikte sonlandırır; adım başlarında durdurma isteği denetlenir.

Bu modül reels içinden hiçbir şey içe aktarmaz (reels/__init__.py Popen kancası bunu kullanır).
"""
from __future__ import annotations

import os
import subprocess
import threading
import weakref

EVENT = threading.Event()          # durdurma istendi
WORKER_THREADS = {"worker"}        # yalnızca bu iş parçacıklarının süreçleri izlenir (uygulamanın iş kuyruğu)
_procs: "weakref.WeakSet[subprocess.Popen]" = weakref.WeakSet()
_lock = threading.Lock()


class Cancelled(RuntimeError):
    """Kullanıcı üretimi durdurdu (StageError değildir: yeniden deneme / otomatik kurtarma yapılmaz)."""


def track(proc: subprocess.Popen) -> None:
    if threading.current_thread().name in WORKER_THREADS:
        with _lock:
            _procs.add(proc)


def check() -> None:
    if EVENT.is_set() and threading.current_thread().name in WORKER_THREADS:
        raise Cancelled("kullanıcı durdurdu")


def _children(pid: int) -> list[int]:
    """POSIX: süreç ağacındaki bütün alt süreçler (ps ile; psutil gerekmez)."""
    try:
        out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    kids: dict[int, list[int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2:
            kids.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, stack = [], [pid]
    while stack:
        for c in kids.get(stack.pop(), []):
            found.append(c)
            stack.append(c)
    return found


def kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return
    import signal
    for pid in reversed(_children(proc.pid)):
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass


def request() -> int:
    """Durdurma ister ve izlenen bütün alt süreçleri sonlandırır; sonlandırılan süreç sayısını döndürür."""
    EVENT.set()
    with _lock:
        procs = [p for p in _procs if p.poll() is None]
    for p in procs:
        kill_tree(p)
    return len(procs)


def clear() -> None:
    EVENT.clear()
    with _lock:
        _procs.clear()
