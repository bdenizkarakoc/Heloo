"""Efekt eklentilerini yükler ve çalıştırır.

Bir eklenti plugins/ içinde tek bir .py dosyasıdır ve şunları tanımlar:
  NAME, DESCRIPTION, PARAMS (varsayılan değerler sözlüğü)
  video_filter(params, ctx) -> str | None
  audio_filter(params, ctx) -> str | None      (isteğe bağlı)
  duration_factor(params)   -> float           (isteğe bağlı, hız gibi süreyi değiştirenler)
"""
import importlib.util
import math
import re

from . import paths


class EffectError(ValueError):
    pass


class UnknownEffect(EffectError):
    pass


_FORBIDDEN_FILTER_CHARS = re.compile(r"[;\[\]\n\r]")


def coerce(defaults: dict, given: dict) -> dict:
    out = dict(defaults)
    for k, v in (given or {}).items():
        if k not in defaults:
            raise EffectError(f"Bilinmeyen parametre: {k}")
        d = defaults[k]
        try:
            if isinstance(d, bool):
                out[k] = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "evet", "yes")
            elif isinstance(d, int):
                out[k] = int(float(v))
            elif isinstance(d, float):
                out[k] = float(v)
                if not math.isfinite(out[k]):
                    raise ValueError
            else:
                out[k] = str(v)
        except (TypeError, ValueError):
            raise EffectError(f"'{k}' parametresi geçersiz: {v!r}")
    return out


class Effect:
    def __init__(self, module):
        self.module = module
        self.name = module.NAME
        self.description = getattr(module, "DESCRIPTION", "")
        self.params = dict(getattr(module, "PARAMS", {}))


class Registry:
    def __init__(self, plugins_dir=None):
        self.dir = plugins_dir or paths.plugins()
        self.effects = {}
        self.errors = {}
        self._load()

    def _load(self):
        for f in sorted(self.dir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"selfedit_plugin_{f.stem}", f)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if not callable(getattr(mod, "video_filter", None)):
                    raise AttributeError("video_filter fonksiyonu yok")
                eff = Effect(mod)
                self.effects[eff.name] = eff
            except Exception as e:  # bozuk eklenti diğerlerini etkilemesin
                self.errors[f.name] = f"{type(e).__name__}: {e}"

    def names(self):
        return sorted(self.effects)

    def get(self, name: str) -> Effect:
        if name not in self.effects:
            raise UnknownEffect(f"Efekt bulunamadı: {name}")
        return self.effects[name]

    @staticmethod
    def _check(s, what):
        if s is None:
            return None
        if not isinstance(s, str) or _FORBIDDEN_FILTER_CHARS.search(s):
            raise EffectError(f"{what} geçersiz filtre üretti")
        return s

    def apply(self, name: str, params: dict, ctx: dict):
        """(video_filtresi, ses_filtresi, süre_çarpanı) döndürür."""
        eff = self.get(name)
        p = coerce(eff.params, params)
        mod = eff.module
        try:
            vf = self._check(mod.video_filter(p, ctx), name)
            af_fn = getattr(mod, "audio_filter", None)
            af = self._check(af_fn(p, ctx), name) if af_fn else None
            df = getattr(mod, "duration_factor", None)
            factor = float(df(p)) if df else 1.0
        except EffectError:
            raise
        except Exception as e:
            raise EffectError(f"'{name}' efekti çalışmadı: {e}")
        if not (0.01 <= factor <= 100):
            raise EffectError(f"'{name}' geçersiz süre çarpanı verdi")
        return vf, af, factor


def load_registry(plugins_dir=None) -> Registry:
    return Registry(plugins_dir)
