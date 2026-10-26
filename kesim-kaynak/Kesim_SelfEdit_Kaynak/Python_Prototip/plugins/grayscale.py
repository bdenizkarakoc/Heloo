NAME = "grayscale"
DESCRIPTION = "Görüntüyü siyah-beyaz yapar"
PARAMS = {}


def video_filter(params, ctx):
    return "hue=s=0"
