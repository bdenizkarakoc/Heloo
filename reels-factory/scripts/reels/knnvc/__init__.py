"""kNN-VC ses dönüşümü (Baas, van Niekerk, Kamper 2023; MIT lisansı — LICENSE).

Kaynak: https://github.com/bshall/knn-vc — model tanımları (wavlm/, hifigan/) ve matcher.py buraya alındı;
torch.hub ile uzak kod çalıştırılmaz. WavLM'deki eval() güvenli ayrıştırıcıyla değiştirildi. Yalnızca ağırlıklar
indirilir ve torch.load(weights_only=True) ile (kod çalıştırmadan) yüklenir.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import ROOT
from ..util import download

HERE = Path(__file__).parent
CACHE = ROOT / "studio" / "cache" / "models"
RELEASE = "https://github.com/bshall/knn-vc/releases/download/v0.1/"
WEIGHTS = {"prematch_g_02500000.pt": 66214643, "WavLM-Large.pt": 1261965425}


def _weights(name: str) -> Path:
    dest = CACHE / name
    if not dest.exists() or dest.stat().st_size != WEIGHTS[name]:
        download(RELEASE + name, dest, max_mb=1300)
        if dest.stat().st_size != WEIGHTS[name]:
            dest.unlink(missing_ok=True)
            raise RuntimeError(f"{name} eksik indirildi")
    return dest


def load(device: str = "cpu"):
    import torch

    from .hifigan.models import Generator as HiFiGAN
    from .hifigan.utils import AttrDict
    from .matcher import KNeighborsVC
    from .wavlm.WavLM import WavLM, WavLMConfig

    h = AttrDict(json.loads((HERE / "hifigan" / "config_v1_wavlm.json").read_text()))
    gen = HiFiGAN(h)
    gen.load_state_dict(torch.load(_weights("prematch_g_02500000.pt"), map_location=device,
                                   weights_only=True)["generator"])
    gen.eval()
    gen.remove_weight_norm()
    ck = torch.load(_weights("WavLM-Large.pt"), map_location=device, weights_only=True)
    wavlm = WavLM(WavLMConfig(ck["cfg"]))
    wavlm.load_state_dict(ck["model"])
    wavlm.eval()
    return KNeighborsVC(wavlm, gen, h, device)
