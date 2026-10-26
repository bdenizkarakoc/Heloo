"""Arka plan servisi: belirli aralıklarla geliştirme döngüsünü çalıştırır."""
import json
import os
import signal
import time

from .. import config, paths
from . import engine


def _status_file():
    return paths.data() / "daemon_status.json"


def _stop_file():
    return paths.data() / "STOP"


def read_status() -> dict:
    try:
        st = json.loads(_status_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"running": False}
    interval = config.load()["interval_minutes"] * 60
    fresh = time.time() - st.get("heartbeat", 0) < 2 * interval + 60
    st["running"] = bool(st.get("running")) and fresh
    return st


def _write(**kw):
    st = {}
    try:
        st = json.loads(_status_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    st.update(kw, heartbeat=time.time(), pid=os.getpid())
    _status_file().write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")


def request_stop():
    _stop_file().write_text("stop", encoding="utf-8")


def run(once: bool = False, offline: bool = False, log=print) -> None:
    if not once and read_status().get("running") and read_status().get("pid") != os.getpid():
        log("Servis zaten çalışıyor (data/daemon_status.json). Durdurmak için: selfedit daemon stop")
        return
    _stop_file().unlink(missing_ok=True)
    stop = {"flag": False}

    def _sig(*_):
        stop["flag"] = True

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(s, _sig)
        except (ValueError, OSError):
            pass

    log(f"SelfEdit servisi başladı (mod: {config.load()['mode']}).")
    while not stop["flag"]:
        cfg = config.load()  # her turda yeniden oku: ayar değişince hemen geçerli olur
        _write(running=True, state="çalışıyor")
        res = engine.run_cycle(offline=offline)
        log(f"[{time.strftime('%H:%M:%S')}] {res}")
        nxt = time.time() + cfg["interval_minutes"] * 60
        _write(running=True, state="bekliyor", last_result=res, last_run=time.time(), next_run=nxt)
        if once:
            break
        while time.time() < nxt and not stop["flag"]:
            if _stop_file().exists():
                stop["flag"] = True
                break
            _write(running=True)
            time.sleep(min(15, max(1, nxt - time.time())))
    _write(running=False, state="durdu")
    _stop_file().unlink(missing_ok=True)
    log("Servis durdu.")
