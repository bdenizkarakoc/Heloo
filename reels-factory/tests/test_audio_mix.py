"""Ses: kesim yerlerinde çıt sesi olmaması, yedek müziğin havaya göre seçilmesi."""
import shutil

import numpy as np
import pytest

from reels import audio
from reels.studio_render import soften_cuts
from reels.util import load_audio, write_wav

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg yok")


@needs_ffmpeg
def test_soften_cuts_removes_jump(tmp_path):
    x = np.full((48000, 2), 0.5, dtype=np.float32)
    x[24000:] = -0.5                                  # kesimde ani sıçrama (çıt)
    wav = write_wav(tmp_path / "v.wav", x, 48000)
    assert soften_cuts(wav, [(0.0, 0.5), (0.5, 1.0)]) == 1
    y = load_audio(wav, 48000, 2)
    assert np.abs(np.diff(y[:, 0])).max() < 0.01      # sıçrama kalmadı
    assert abs(y[12000, 0] - 0.5) < 0.01 and abs(y[40000, 0] + 0.5) < 0.01   # kesim dışı aynen
    assert soften_cuts(wav, [(0.0, 1.0)]) == 0


def test_mood_selection():
    assert audio._mood(["energetic upbeat"])[1] > 100 and audio._mood(["energetic upbeat"])[2]
    assert not audio._mood(["sad piano emotional"])[2]
    assert audio._mood(["lofi chill"])[4] == "soft"
    assert audio._mood(["bilinmeyen"]) == audio.MOODS[2]


@needs_ffmpeg
def test_procedural_music_has_rhythm(tmp_path):
    m = audio._music_procedural(None, ["energetic upbeat"], tmp_path, set(), 6.0)
    y = load_audio(m["path"], 48000, 1)
    assert len(y) > 48000 * 6 and 0.05 < np.abs(y).max() <= 1.0
    env = np.abs(y[: 48000 * 6]).reshape(-1, 2400).mean(axis=1)      # 50 ms zarf
    assert env.max() > 2.5 * np.median(env)                          # vuruşlar var (düz uğultu değil)
