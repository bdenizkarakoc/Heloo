NAME = "volume"
DESCRIPTION = "Ses seviyesi çarpanı (1.0 = değişmez, 0 = sessiz)"
PARAMS = {"gain": 1.5}


def video_filter(params, ctx):
    return None


def audio_filter(params, ctx):
    g = params["gain"]
    if not 0.0 <= g <= 10.0:
        raise ValueError("gain 0 ile 10 arasında olmalı")
    return f"volume={g}"
