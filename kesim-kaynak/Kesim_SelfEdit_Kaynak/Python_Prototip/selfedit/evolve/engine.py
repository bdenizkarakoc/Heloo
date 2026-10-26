"""Geliştirme döngüsü: analiz -> öneri -> doğrulama -> (onay) -> uygulama -> sağlık kontrolü."""
import time

from .. import config, paths, telemetry
from ..effects import load_registry
from . import proposer, store, validator


def run_cycle(offline: bool = False, run_suite: bool = True, force: bool = False) -> dict:
    cfg = config.load()
    if not force:
        if store.count_today() >= cfg["max_per_day"]:
            return {"result": "skipped", "reason": "günlük öneri sınırına ulaşıldı"}
        if len(store.list_all("validated")) >= cfg["max_pending"]:
            return {"result": "skipped", "reason": "onay bekleyen öneri sayısı sınırda"}

    reg = load_registry()
    summary = telemetry.summarize()
    p = proposer.pick(cfg, offline=offline)
    try:
        prop = p.propose(summary, reg)
    except Exception as e:  # API hatası vb. döngüyü düşürmesin
        return {"result": "error", "reason": f"öneri üretilemedi: {type(e).__name__}: {e}"}
    if prop is None:
        return {"result": "nothing", "reason": "yeni öneri yok"}
    if prop["plugin_name"] in reg.effects or prop["plugin_name"] in store.known_names():
        return {"result": "skipped", "reason": f"'{prop['plugin_name']}' zaten var veya önerilmiş"}

    report = validator.validate(prop["code"], prop["plugin_name"], run_suite=run_suite)
    prop["validation"] = report
    prop["status"] = "validated" if report["ok"] else "failed"
    store.save(prop)
    store.changelog({"event": "proposal", "id": prop["id"], "status": prop["status"], "source": prop["source"]})

    out = {"result": prop["status"], "id": prop["id"], "plugin": prop["plugin_name"], "source": prop["source"]}
    if report["ok"] and cfg["mode"] == "auto":
        out["applied"] = apply(prop["id"])
        out["result"] = "applied" if out["applied"]["ok"] else "rolled_back"
    return out


def apply(prop_id: str) -> dict:
    prop = store.load(prop_id)
    if prop["status"] not in ("validated",):
        return {"ok": False, "detail": f"durum '{prop['status']}', yalnızca doğrulanmış öneriler uygulanır"}
    # Uygulama anında tekrar doğrula: bu arada plugins/ değişmiş olabilir
    report = validator.validate(prop["code"], prop["plugin_name"], run_suite=False)
    if not report["ok"]:
        prop["status"], prop["validation"] = "failed", report
        store.save(prop)
        return {"ok": False, "detail": "yeniden doğrulama başarısız"}

    target = paths.plugins() / f"{prop['plugin_name']}.py"
    target.write_text(prop["code"], encoding="utf-8")

    # Canlı ağaçta sağlık kontrolü; bozulursa kendiliğinden geri al
    health = validator.smoke(paths.code_root(), prop["plugin_name"]) if paths.root() == paths.code_root() \
        else _live_smoke(prop["plugin_name"])
    if not health["ok"]:
        target.unlink(missing_ok=True)
        prop["status"] = "rolled_back"
        store.save(prop)
        store.changelog({"event": "auto_rollback", "id": prop["id"], "detail": health.get("detail")})
        return {"ok": False, "detail": f"sağlık kontrolü başarısız, geri alındı: {health.get('detail')}"}

    prop["status"], prop["applied_at"] = "applied", time.time()
    store.save(prop)
    store.changelog({"event": "applied", "id": prop["id"], "plugin": prop["plugin_name"]})
    return {"ok": True, "detail": f"'{prop['plugin_name']}' eklendi"}


def _live_smoke(name: str) -> dict:
    """SELFEDIT_HOME farklıysa (ör. testler) canlı eklenti klasörünü kopyalayıp dener."""
    box = validator.make_sandbox()
    try:
        return validator.smoke(box, name)
    finally:
        import shutil
        shutil.rmtree(box, ignore_errors=True)


def reject(prop_id: str) -> dict:
    prop = store.load(prop_id)
    if prop["status"] == "applied":
        return {"ok": False, "detail": "uygulanmış öneri reddedilemez; rollback kullanın"}
    prop["status"] = "rejected"
    store.save(prop)
    store.changelog({"event": "rejected", "id": prop["id"]})
    return {"ok": True, "detail": "reddedildi"}


def rollback(prop_id: str) -> dict:
    prop = store.load(prop_id)
    if prop["status"] != "applied":
        return {"ok": False, "detail": "yalnızca uygulanmış öneriler geri alınır"}
    (paths.plugins() / f"{prop['plugin_name']}.py").unlink(missing_ok=True)
    prop["status"] = "rolled_back"
    store.save(prop)
    store.changelog({"event": "rollback", "id": prop["id"]})
    return {"ok": True, "detail": f"'{prop['plugin_name']}' kaldırıldı"}
