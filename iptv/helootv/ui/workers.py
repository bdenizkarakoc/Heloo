"""Arka plan işleri (QThreadPool). Sonuçlar ana iş parçacığına sinyalle döner."""
from __future__ import annotations

import inspect
import logging
import traceback
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger("helootv.ui")
_ACTIVE: set["Task"] = set()


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


class Task(QRunnable):
    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()
        try:
            self._wants_progress = "progress" in inspect.signature(fn).parameters
        except (TypeError, ValueError):
            self._wants_progress = False

    def run(self) -> None:
        try:
            kwargs = dict(self.kwargs)
            if self._wants_progress and "progress" not in kwargs:
                kwargs["progress"] = self.signals.progress.emit
            result = self.fn(*self.args, **kwargs)
        except Exception as e:  # noqa: BLE001 — kullanıcıya iletilir
            log.debug("arka plan işi hatası: %s", traceback.format_exc())
            self.signals.failed.emit(str(e) or e.__class__.__name__)
        else:
            self.signals.done.emit(result)


def run_task(fn: Callable, *args, on_done: Callable | None = None, on_error: Callable | None = None,
             on_progress: Callable | None = None, **kwargs) -> Task:
    task = Task(fn, *args, **kwargs)
    task.setAutoDelete(False)
    _ACTIVE.add(task)

    def finish(*_a):
        _ACTIVE.discard(task)

    if on_done:
        task.signals.done.connect(on_done)
    if on_error:
        task.signals.failed.connect(on_error)
    if on_progress:
        task.signals.progress.connect(on_progress)
    task.signals.done.connect(finish)
    task.signals.failed.connect(finish)
    QThreadPool.globalInstance().start(task)
    return task
