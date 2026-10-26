"""İyileştirme önerilerinin saklanması (data/proposals/*.json) ve değişiklik günlüğü."""
import json
import time
from pathlib import Path

from .. import paths

# Durumlar: validated (doğrulandı, onay bekliyor) | failed (doğrulama geçilemedi)
#           applied | rejected | rolled_back


def _dir() -> Path:
    p = paths.data() / "proposals"
    p.mkdir(parents=True, exist_ok=True)
    return p


def new_id(plugin_name: str) -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + plugin_name


def save(prop: dict) -> None:
    (_dir() / f"{prop['id']}.json").write_text(
        json.dumps(prop, indent=2, ensure_ascii=False), encoding="utf-8")


def load(prop_id: str) -> dict:
    f = _dir() / f"{prop_id}.json"
    if not f.exists():
        matches = sorted(_dir().glob(f"*{prop_id}*.json"))
        if len(matches) != 1:
            raise KeyError(f"Öneri bulunamadı veya belirsiz: {prop_id}")
        f = matches[0]
    return json.loads(f.read_text(encoding="utf-8"))


def list_all(status: str = None) -> list:
    out = []
    for f in sorted(_dir().glob("*.json")):
        try:
            p = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if status is None or p.get("status") == status:
            out.append(p)
    return out


def count_today() -> int:
    cutoff = time.time() - 86400
    return sum(1 for p in list_all() if p.get("created", 0) >= cutoff)


def known_names() -> set:
    """Daha önce önerilmiş (reddedilen dahil) eklenti adları; tekrar önerilmesin."""
    return {p["plugin_name"] for p in list_all()}


def changelog(entry: dict) -> None:
    entry = {"ts": time.time(), **entry}
    with (paths.data() / "changelog.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
