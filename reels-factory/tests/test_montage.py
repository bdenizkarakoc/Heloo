"""Montaj: kısa video kurgu kuralları (görüntü 2-3 sn'de bir değişir, vurguda kısa zoom)."""
from reels.studio_render import DEFAULT_STYLE, emphasis_times, full_style, zoom_plan


def words(spec):
    return [{"word": w, "start": s, "end": s + 0.3} for w, s in spec]


def test_long_piece_gets_interrupts():
    plan = zoom_plan([(0.0, 9.0)], [], full_style(DEFAULT_STYLE))  # kesimsiz 9 sn → 4 parça, ikisi zoomlu
    assert len(plan) == 2 and all(abs(v - 1.12) < 1e-6 for _, _, v in plan)
    assert all(b - a <= 2.8 for a, b, _ in plan)


def test_alternating_cuts_and_emphasis():
    st = full_style(DEFAULT_STYLE)
    plan = zoom_plan([(0, 2), (2, 4), (4, 6)], words([("Merhaba", 0.2), ("1923", 0.5), ("muhteşem!", 4.4)]), st)
    vals = {round(v, 3) for _, _, v in plan}
    assert 1.12 in vals                      # ikinci kesim zoomlu
    assert any(a <= 0.6 < b and abs(v - 1.08) < 1e-6 for a, b, v in plan)  # zoomsuz parçada vurgu
    assert any(a <= 4.5 < b for a, b, _ in plan)


def test_emphasis_gap_and_stopwords():
    t = emphasis_times(words([("1923", 0.0), ("2024", 1.0), ("gerçekten", 3.0), ("inanılmazdı", 3.5)]))
    assert t == [0.0, 3.5]


def test_punch_disabled():
    st = full_style({**DEFAULT_STYLE, "punch": {"enabled": False, "scale": 1.12}})
    assert zoom_plan([(0, 9)], words([("1923", 1)]), st) == []
