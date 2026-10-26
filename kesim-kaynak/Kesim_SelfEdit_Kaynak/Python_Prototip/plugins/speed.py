NAME = "speed"
DESCRIPTION = "Hız değiştirir (2.0 = iki kat hızlı, 0.5 = yarı hız)"
PARAMS = {"factor": 2.0}


def _check(f):
    if not 0.1 <= f <= 16:
        raise ValueError("factor 0.1 ile 16 arasında olmalı")


def video_filter(params, ctx):
    f = params["factor"]
    _check(f)
    return f"setpts=PTS/{f}"


def audio_filter(params, ctx):
    f = params["factor"]
    _check(f)
    parts = []
    while f > 2.0:
        parts.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        parts.append("atempo=0.5")
        f *= 2.0
    parts.append(f"atempo={f:.5f}")
    return ",".join(parts)


def duration_factor(params):
    _check(params["factor"])
    return 1.0 / params["factor"]
