NAME = "fade"
DESCRIPTION = "Klibin başında ve sonunda yumuşak geçiş (görüntü + ses)"
PARAMS = {"in_s": 0.5, "out_s": 0.5}


def _parts(params, ctx, prefix):
    d = ctx["duration"]
    parts = []
    if params["in_s"] > 0:
        parts.append(f"{prefix}=t=in:st=0:d={params['in_s']}")
    if params["out_s"] > 0:
        st = max(0.0, d - params["out_s"])
        parts.append(f"{prefix}=t=out:st={st:.3f}:d={params['out_s']}")
    return ",".join(parts) or None


def video_filter(params, ctx):
    return _parts(params, ctx, "fade")


def audio_filter(params, ctx):
    return _parts(params, ctx, "afade")
