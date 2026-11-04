from PIL import Image, ImageDraw

from reels import characters, visuals
from reels.config import load_config
from reels.script_model import normalize
from reels.yt_tools import hook_score


def test_cta_shortened():
    cfg = load_config()
    for cta, want in [("Takip et, tarihten bir an daha gelsin", "Takip et"), ("Kaydet", "Kaydet")]:
        s = normalize({"scenes": [{"layout": "outro", "narration": "a b c", "on_screen": {"headline": "x", "cta": cta}}]}, cfg)
        assert s["scenes"][0]["on_screen"]["cta"] == want
    long = normalize({"scenes": [{"layout": "outro", "narration": "a b c",
                                  "on_screen": {"headline": "x", "cta": "Takip et ve kaydet bu videoyu sonra izlemek için"}}]}, cfg)
    assert len(long["scenes"][0]["on_screen"]["cta"]) <= 28


def test_license_ok():
    ok = ["CC0 1.0", "BY 4.0", "CC BY 4.0", "Public domain", "PDM 1.0", "Pexels License"]
    bad = ["CC BY-SA 4.0", "BY-NC 2.0", "BY-SA 2.0", "lisans bilgisi yok"]
    assert all(visuals.license_ok({"license": x}) for x in ok)
    assert not any(visuals.license_ok({"license": x}) for x in bad)


def test_broader_queries_and_year_rank():
    q = visuals.broader_queries("Ankara 1923 dinner table Ataturk friends", "Mustafa Kemal Atatürk")
    assert q[0] == "Ankara 1923 dinner" and "Mustafa Kemal Atatürk" in q and len(q) <= 4
    c = [{"title": "Grand National Assembly of Turkey MPs in June 2015"}, {"title": "Grand National Assembly of Turkey (1928)"}]
    assert visuals.rank(c, "Grand National Assembly Turkey Ankara 1923")[0]["title"].endswith("(1928)")


def test_turkish_hook_address():
    assert hook_score("Hiç duydun mu: Cumhuriyet bir akşam yemeğinde doğdu.")["properties"]["ADDRESS"] > 50
    assert hook_score("Yarın işten kovulursanız buna şaşırmayın.")["properties"]["ADDRESS"] > 26
    assert hook_score("Bir kadın altın buldu.")["properties"]["ADDRESS"] == 26  # 'kadın' hitap sayılmaz


def test_character_card_keying():
    im = Image.new("RGB", (832, 1248), (0, 255, 0)); d = ImageDraw.Draw(im)
    d.ellipse((316, 180, 516, 400), fill=(255, 226, 194), outline=(36, 23, 38), width=10)
    d.rounded_rectangle((330, 400, 502, 1010), 40, fill=(232, 120, 44))
    card = characters.fit_card(characters.key_out(im))
    a = card.getchannel("A")
    assert card.size == (600, 1000) and a.getpixel((5, 5)) == 0 and a.getbbox()[3] == characters.SOLE_Y
