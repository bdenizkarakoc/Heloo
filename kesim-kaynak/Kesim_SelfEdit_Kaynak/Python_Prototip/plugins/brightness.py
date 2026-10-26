NAME = "brightness"
DESCRIPTION = "Parlaklık ayarı (-1.0 ile 1.0 arası)"
PARAMS = {"amount": 0.1}


def video_filter(params, ctx):
    a = params["amount"]
    if not -1.0 <= a <= 1.0:
        raise ValueError("amount -1 ile 1 arasında olmalı")
    return f"eq=brightness={a}"
