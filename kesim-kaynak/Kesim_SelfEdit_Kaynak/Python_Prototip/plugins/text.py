import re

NAME = "text"
DESCRIPTION = "Videonun üstüne yazı ekler (start/end saniye; end=0 ise hep görünür)"
PARAMS = {
    "text": "Merhaba",
    "size": 48,
    "color": "white",
    "x": "(w-text_w)/2",
    "y": "h-th-60",
    "start": 0.0,
    "end": 0.0,
}

_EXPR = re.compile(r"^[A-Za-z0-9_+\-*/(). ]+$")
_COLOR = re.compile(r"^[A-Za-z0-9#@.]+$")


def video_filter(params, ctx):
    if not params["text"].strip():
        raise ValueError("text boş olamaz")
    if not 4 <= params["size"] <= 400:
        raise ValueError("size 4 ile 400 arasında olmalı")
    if not _COLOR.match(params["color"]):
        raise ValueError("color geçersiz")
    if not _EXPR.match(params["x"]) or not _EXPR.match(params["y"]):
        raise ValueError("x ve y yalnızca basit ifadeler olabilir")
    parts = [
        "textfile=" + ctx["textfile"](params["text"]),
        f"fontsize={params['size']}",
        f"fontcolor={params['color']}",
        f"x='{params['x']}'",
        f"y='{params['y']}'",
        "box=1:boxcolor=black@0.4:boxborderw=10",
    ]
    if ctx.get("font"):
        parts.append("fontfile=" + ctx["font"])
    if params["end"] > params["start"]:
        parts.append(f"enable='between(t,{params['start']},{params['end']})'")
    return "drawtext=" + ":".join(parts)
