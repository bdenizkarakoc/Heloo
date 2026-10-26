NAME = "blur"
DESCRIPTION = "Gauss bulanıklığı"
PARAMS = {"sigma": 5.0}


def video_filter(params, ctx):
    s = params["sigma"]
    if not 0.1 <= s <= 100:
        raise ValueError("sigma 0.1 ile 100 arasında olmalı")
    return f"gblur=sigma={s}"
