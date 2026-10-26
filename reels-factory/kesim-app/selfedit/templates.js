/* Kesim SelfEdit: çevrimdışı şablon kütüphanesi (internet/API anahtarı olmadan çalışan öneriler).
 * Her biri bir efekt TARİFİdir; doğrulayıcıdan ve işlevsel kontrolden geçmeden uygulanmaz. */
"use strict";

const T = (keywords, recipe) => ({ keywords, recipe: { v: 1, ...recipe } });

module.exports = [
  T(["sıcak", "sicak", "warm", "turuncu ton", "gün batımı tonu"], {
    id: "sicak_ton", name: "Sıcak ton", group: "Renk", di: 0.6, desc: "Görüntüyü hafif turuncu ve canlı yapar.",
    ops: [
      { op: "filter", fx: [{ f: "sepia", v: "i*0.35" }, { f: "saturate", v: "1+i*0.35" }, { f: "brightness", v: "1+i*0.04" }] },
      { op: "fill", color: "#ff9a3c", alpha: "i*0.14", comp: "overlay" }],
  }),
  T(["soğuk", "soguk", "cold", "cool", "mavi ton", "buz"], {
    id: "soguk_ton", name: "Soğuk ton", group: "Renk", di: 0.6, desc: "Görüntüye serin, mavimsi bir hava verir.",
    ops: [
      { op: "filter", fx: [{ f: "hue-rotate", v: "-i*12" }, { f: "saturate", v: "1+i*0.1" }] },
      { op: "fill", color: "#3c78ff", alpha: "i*0.16", comp: "overlay" }],
  }),
  T(["turkuaz", "teal", "sinematik renk", "film renk", "sinema renk"], {
    id: "turkuaz_turuncu", name: "Turkuaz-turuncu", group: "Renk", di: 0.7, desc: "Sinema filmlerindeki klasik renk ayrımı.",
    ops: [
      { op: "gradient", kind: "linear", angle: "90", stops: [[0, "#00b4c8"], [1, "#ff8a2b"]], alpha: "i*0.32", comp: "soft-light" },
      { op: "filter", fx: [{ f: "contrast", v: "1+i*0.12" }, { f: "saturate", v: "1+i*0.1" }] }],
  }),
  T(["solmuş", "solmus", "faded", "mat", "analog film", "eski film rengi"], {
    id: "solmus_film", name: "Solmuş film", group: "Retro", di: 0.6, desc: "Mat, hafif soluk analog film görünümü.",
    ops: [
      { op: "filter", fx: [{ f: "contrast", v: "1-i*0.12" }, { f: "brightness", v: "1+i*0.06" }, { f: "saturate", v: "1-i*0.3" }] },
      { op: "fill", color: "#1b2a49", alpha: "i*0.14", comp: "lighten" },
      { op: "noise", amount: "i*0.18", comp: "overlay", animate: true }],
  }),
  T(["rüya", "ruya", "dream", "yumuşak parıltı", "bloom", "ışıltı", "isilti"], {
    id: "ruya_parilti", name: "Rüya parıltısı", group: "Işık", di: 0.6, desc: "Parlak yerlerden yumuşak bir ışık yayılır.",
    ops: [
      { op: "glow", radius: "0.02", strength: "i*0.8" },
      { op: "filter", fx: [{ f: "saturate", v: "1+i*0.2" }, { f: "brightness", v: "1+i*0.03" }] }],
  }),
  T(["korku", "horror", "kırmızı vinyet", "kirmizi", "tehlike"], {
    id: "korku_vinyet", name: "Kırmızı karanlık", group: "Işık", di: 0.7, desc: "Kenarları kırmızıya boyayan gergin bir atmosfer.",
    ops: [
      { op: "filter", fx: [{ f: "contrast", v: "1+i*0.2" }, { f: "saturate", v: "1-i*0.25" }] },
      { op: "gradient", kind: "radial", r0: "0.15", r1: "0.6", stops: [[0, "#ff000000"], [1, "#c8000099"]], alpha: "i" }],
  }),
  T(["matrix", "yeşil", "yesil", "hacker", "terminal"], {
    id: "matrix_yesil", name: "Matrix yeşili", group: "Retro", di: 0.7, desc: "Yeşil tonlu, tarama çizgili hacker görünümü.",
    ops: [
      { op: "filter", fx: [{ f: "grayscale", v: "1" }, { f: "contrast", v: "1.1" }] },
      { op: "fill", color: "#00ff55", alpha: "i*0.6", comp: "multiply" },
      { op: "scanlines", alpha: "i*0.4" }],
  }),
  T(["duoton", "iki renk", "ikili renk", "mor", "pop art"], {
    id: "duoton_mor_turuncu", name: "İkili renk (mor-turuncu)", group: "Renk", di: 0.8, desc: "Gri tonları mor ve turuncuya boyar.",
    ops: [
      { op: "filter", fx: [{ f: "grayscale", v: "1" }, { f: "contrast", v: "1.15" }] },
      { op: "gradient", kind: "linear", angle: "0", stops: [[0, "#7a2cff"], [1, "#ff8a2b"]], alpha: "i", comp: "multiply" },
      { op: "filter", fx: [{ f: "brightness", v: "1+i*0.25" }], alpha: "i*0.5", comp: "screen" }],
  }),
  T(["kontrast", "contrast", "vurgu", "darbe", "patlama"], {
    id: "kontrast_darbesi", name: "Kontrast darbesi", group: "Işık", di: 0.7, desc: "Başlangıçta güçlü kontrast, sonra yumuşak geri dönüş.",
    ops: [{ op: "filter", fx: [{ f: "contrast", v: "1+i*0.6*(1-ease(p))" }, { f: "saturate", v: "1+i*0.4*(1-ease(p))" }] }],
  }),
  T(["uzaklaş", "uzaklas", "zoom out", "açılış", "acilis", "reveal"], {
    id: "uzaklasarak_acilis", name: "Uzaklaşarak açılış", group: "Hareket", di: 0.7, desc: "Yakından başlayıp yavaşça geri çekilen kamera.",
    ops: [{ op: "zoom", scale: "1+i*0.35*(1-ease(p))" }],
  }),
  T(["nefes", "breathing", "salınım", "süzül", "suzul", "hafif sallan"], {
    id: "nefes_alan_kamera", name: "Nefes alan kamera", group: "Hareket", di: 0.5, desc: "Yavaşça yaklaşıp uzaklaşan, hafif eğilen kamera.",
    ops: [{ op: "zoom", scale: "1.04+0.03*i*sin(lt*sp*2.2)", rot: "0.012*i*sin(lt*sp*1.4)", dy: "0.006*i*sin(lt*sp*1.7)" }],
  }),
  T(["dörtlü", "dortlu", "kaleydoskop", "ayna", "simetri", "dörde böl"], {
    id: "dortlu_ayna", name: "Dörtlü ayna", group: "Bozulma", di: 1, desc: "Görüntüyü hem sağ-sol hem alt-üst yansıtır.",
    ops: [{ op: "mirror", axis: "h" }, { op: "mirror", axis: "v" }],
  }),
  T(["alarm", "polis", "uyarı", "uyari", "yanıp sön", "kırmızı flaş"], {
    id: "alarm_flasi", name: "Alarm flaşı", group: "Işık", di: 0.7, desc: "Kırmızı ışığın ritimle yanıp sönmesi.",
    ops: [{ op: "fill", color: "#ff1020", alpha: "i*0.55*(1-step(0.5,fract(lt*sp*2.5)))", comp: "screen" }],
  }),
  T(["gün batımı", "gun batimi", "sunset", "gökyüzü", "altın saat", "golden"], {
    id: "gun_batimi", name: "Gün batımı", group: "Renk", di: 0.7, desc: "Üstten alta pembe-altın bir gün batımı geçişi.",
    ops: [
      { op: "gradient", kind: "linear", angle: "90", stops: [[0, "#ff5e62"], [0.6, "#ffa45e66"], [1, "#ffd36e00"]], alpha: "i*0.8", comp: "soft-light" },
      { op: "filter", fx: [{ f: "saturate", v: "1+i*0.25" }] }],
  }),
  T(["buzlu", "frosted", "cam", "bulanık parlak", "bulanik"], {
    id: "buzlu_cam", name: "Buzlu cam", group: "Odak", di: 0.6, desc: "Bulanık, hafif beyazlatılmış buzlu cam etkisi.",
    ops: [
      { op: "filter", fx: [{ f: "blur", v: "i*W*0.008" }, { f: "brightness", v: "1+i*0.08" }] },
      { op: "fill", color: "#ffffff", alpha: "i*0.14", comp: "screen" }],
  }),
  T(["70", "yetmiş", "yetmis", "nostaljik", "retro renk", "vintage"], {
    id: "yetmisler", name: "70'ler", group: "Retro", di: 0.6, desc: "Sepya, vinyet ve gren ile nostaljik görünüm.",
    ops: [
      { op: "filter", fx: [{ f: "sepia", v: "i*0.5" }, { f: "contrast", v: "1.05" }, { f: "saturate", v: "1+i*0.2" }] },
      { op: "gradient", kind: "radial", r0: "0.25", r1: "0.62", stops: [[0, "#00000000"], [1, "#000000aa"]], alpha: "i*0.8" },
      { op: "noise", amount: "i*0.22", comp: "overlay", animate: true }],
  }),
  T(["gece", "mavi gece", "ay ışığı", "ay isigi", "moonlight", "night blue"], {
    id: "mavi_gece", name: "Mavi gece", group: "Renk", di: 0.6, desc: "Karanlık, mavimsi bir gece havası.",
    ops: [
      { op: "filter", fx: [{ f: "brightness", v: "1-i*0.15" }, { f: "saturate", v: "0.85" }] },
      { op: "fill", color: "#3a5cff", alpha: "i*0.35", comp: "multiply" },
      { op: "fill", color: "#3a5cff", alpha: "i*0.08", comp: "screen" }],
  }),
  T(["ritim şerit", "ritimli şerit", "şerit", "serit", "bant", "nabız şerit"], {
    id: "ritmik_seritler", name: "Ritmik şeritler", group: "Hareket", di: 0.7, desc: "Alt ve üstte ritimle açılıp kapanan siyah şeritler.",
    ops: [{ op: "bars", edge: "vertical", size: "0.07*i*(0.5+0.5*sin(lt*sp*6))" }],
  }),
  T(["sansür", "sansur", "gizle", "mozaik küçük", "bulanık mozaik"], {
    id: "iri_mozaik", name: "İri mozaik", group: "Bozulma", di: 0.8, desc: "Görüntüyü büyük karelerle mozaikler.",
    ops: [{ op: "pixelate", cells: "48-i*20" }],
  }),
];
