"""Montaj: CapCut tarzı altyazı animasyonları, dolgu sesi kesme, zoom ifadesi, film efektleri, sihirbaz seçenekleri."""
from reels import brief
from reels.studio_render import (DEFAULT_STYLE, build_ass, cut_times, drop_fillers, full_style, plan_pieces,
                                 video_filter, word_boxes, zoom_expr, zoom_plan)


def W(spec):
    return [{"word": w, "start": s, "end": s + 0.3} for w, s in spec]


def style(**over):
    return full_style({**DEFAULT_STYLE, **over})


def test_fillers_dropped_and_cut():
    ws = drop_fillers(W([("Merhaba", 0.0), ("ııı", 0.4), ("arkadaşlar", 0.8), ("eee", 1.2), ("başlıyoruz", 1.6)]))
    assert [w["word"] for w in ws] == ["Merhaba", "arkadaşlar", "başlıyoruz"] and ws[0]["cut_after"]
    assert len(plan_pieces(ws, 0, 2.2, style())) == 3          # dolgu sesleri kısa olsa da kesilir
    assert [w["word"] for w in drop_fillers(W([("şey", 0), ("emin", 1), ("ama", 2)]))] == ["şey", "emin", "ama"]


def test_box_caption_positions():
    boxes = word_boxes(["BU", "VİDEO", "HARİKA"], 900, 78, 1080)
    assert all(a < b for a, b in boxes) and boxes[0][1] < boxes[1][0] < boxes[1][1] < boxes[2][0]
    assert abs((boxes[0][0] + boxes[-1][1]) / 2 - 540) < 2          # satır ortalı
    ass, _ = build_ass(W([("Bu", 0.1), ("video", 0.5), ("harika", 0.9)]), None,
                       style(captions={**DEFAULT_STYLE["captions"], "anim": "kutu"}), 1080, 1920, 5)
    assert ass.count("\\p1") == 3                                  # her kelime için bir kutu


def test_caption_anims_and_keyword():
    ws = W([("Tam", 0.1), ("1923", 0.5), ("yılında", 0.9)])
    cap = DEFAULT_STYLE["captions"]
    ass, _ = build_ass(ws, None, style(captions={**cap, "anim": "daktilo"}), 1080, 1920, 5)
    assert "\\alpha&HFF&" in ass
    ass, _ = build_ass(ws, None, style(captions={**cap, "anim": "bounce", "keyword": "#00FF00"}), 1080, 1920, 5)
    assert "\\fscx118" in ass and "&H0000FF00" in ass
    assert style(captions={**cap, "anim": "tek"})["captions"]["words"] == 1
    assert style(captions={**cap, "anim": "uydurma"})["captions"]["anim"] == "pop"


def test_zoom_expr_modes_and_outro():
    pieces = [(0, 3), (3, 6)]
    st = style(punch={**DEFAULT_STYLE["punch"], "mode": "smooth", "bump": 0.05})
    z = zoom_expr(zoom_plan(pieces, [], st), pieces, st)
    assert z.startswith("min(1.5") and "(it-" in z and "0.050" in z
    assert zoom_expr([], pieces, style(punch={"enabled": False})) == ""
    assert cut_times([(0, 1), (1, 2), (2, 5)], 1.5) == [1.0]
    ass, _ = build_ass([], None, style(outro={"enabled": True, "text": "Takip et!", "seconds": 2}), 1080, 1920, 10)
    assert "TAKİP ET!" in ass and "0:00:08.00" in ass


def test_fx_filters_in_graph_and_clamped():
    st = style(fx={"cut_flash": 9, "grain": 99, "letterbox": 0.08, "glow": 0.3, "vhs": 4, "sharpen": 0.5, "fade_out": 0.4},
               grade={**DEFAULT_STYLE["grade"], "look": "teal"})
    assert st["fx"]["cut_flash"] == 0.3 and st["fx"]["grain"] == 30
    g = video_filter(st, 1080, 1920, [(0, 3), (3, 6)], 6.0, "1", 30)
    for part in ("eval=frame", "noise=alls=30", "drawbox", "blend=all_mode=screen", "rgbashift", "unsharp",
                 "colorbalance=rs=-0.06", "fade=out"):
        assert part in g, part
    plain = video_filter(style(), 1080, 1920, [(0, 6)], 6.0, "1", 30)
    assert "noise" not in plain and "blend" not in plain and "eval=frame" not in plain
    assert full_style({"grade": {"look": "yok-boyle"}})["grade"]["look"] == ""


def test_brief_new_options():
    o = brief.build({"tarz": "viral", "zoom": "yumusak", "filtre": "gren", "bitis": "Takip et!"})
    so = o["style_overrides"]
    assert so["captions"]["anim"] == "kutu" and so["punch"]["mode"] == "smooth" and so["fx"]["grain"] == 9
    assert so["outro"] == {"enabled": True, "text": "Takip et!"}
    full_style(so)                                                 # geçerli stil üretir
    k = brief.keywords("capcut gibi viral olsun, tek kelime altyazı, yavaş zoom, vhs efekti, sonda takip et yazsın")
    assert k["tarz"] == "viral" and k["altyazi"] == "tek" and k["zoom"] == "yumusak" and k["filtre"] == "vhs"
    assert k["bitis"] == "Takip et!"
    for name, t in brief.TARZ.items():
        full_style(t)
