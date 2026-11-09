"""Görüntü ayarları penceresi: hazır ayarlar + parlaklık/kontrast/doygunluk/gama/ton, keskinlik, karıncalanma
(gürültü) azaltma, renk bandı yumuşatma. Değişiklikler oynatılan görüntüye anında uygulanır (motor.apply_picture)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QSlider, QVBoxLayout)

from ..player import options as opt

SLIDERS = (("brightness", "Parlaklık"), ("contrast", "Kontrast"), ("saturation", "Renk doygunluğu"),
           ("gamma", "Gama (koyu alanlar)"), ("hue", "Renk tonu"))
SHARPEN = (("off", "Kapalı"), ("light", "Hafif"), ("medium", "Orta"), ("strong", "Güçlü"))
DENOISE = (("auto", "Otomatik (düşük kalitede açık)"), ("off", "Kapalı"), ("light", "Hafif"), ("medium", "Orta"),
           ("strong", "Güçlü — karıncalı yayınlar"))
DEBAND = ((0, "Kapalı"), (1, "Hafif"), (2, "Orta"), (3, "Güçlü"))


class PictureDialog(QDialog):
    """`changed` her değişiklikte yayılır; ana pencere motoru günceller ve ayarları kaydeder."""
    changed = Signal()

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Görüntü ayarları")
        self.setMinimumWidth(680)
        self._loading = False
        self._emit_timer = QTimer(self)
        self._emit_timer.setSingleShot(True)
        self._emit_timer.setInterval(120)
        self._emit_timer.timeout.connect(self.changed.emit)

        lay = QVBoxLayout(self)
        info = QLabel("Ayarlar oynayan görüntüye anında uygulanır ve kaydedilir. Karıncalanma azaltma gecikme eklemez "
                      "(yalnız önceki kareyi kullanır); keskinlik bulanıklığı giderir.")
        info.setWordWrap(True)
        info.setObjectName("Muted")
        lay.addWidget(info)

        lay.addWidget(QLabel("Hazır ayar:"))
        pre = QHBoxLayout()
        pre.setSpacing(6)
        self.preset_btns: dict[str, QPushButton] = {}
        for key in ("natural", "vivid", "cinema", "sports", "noisy"):
            b = QPushButton(opt.PRESET_LABELS[key])
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, k=key: self._preset(k))
            pre.addWidget(b, 1)
            self.preset_btns[key] = b
        lay.addLayout(pre)
        self.preset_note = QLabel("")
        self.preset_note.setObjectName("Muted")
        lay.addWidget(self.preset_note)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self.sliders: dict[str, QSlider] = {}
        self.values: dict[str, QLabel] = {}
        r = 0
        for key, label in SLIDERS:
            s = QSlider(Qt.Horizontal)
            s.setRange(-100, 100)
            s.setPageStep(5)
            s.setToolTip("Çift tık: sıfırla")
            v = QLabel("0")
            v.setMinimumWidth(36)
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            s.valueChanged.connect(lambda val, k=key: self._slider(k, val))
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(s, r, 1)
            grid.addWidget(v, r, 2)
            self.sliders[key], self.values[key] = s, v
            r += 1

        def combo(items, cb):
            c = QComboBox()
            for val, text in items:
                c.addItem(text, val)
            c.currentIndexChanged.connect(lambda _i: cb(c.currentData()))
            return c

        self.sharpen = combo(SHARPEN, lambda v: self._set("video", "sharpen", v))
        self.denoise = combo(DENOISE, lambda v: self._set("picture", "denoise", v))
        self.deband = combo(DEBAND, lambda v: self._set("picture", "deband", int(v)))
        for label, w in (("Keskinlik (CAS)", self.sharpen), ("Karıncalanma azaltma", self.denoise),
                         ("Renk bandı yumuşatma", self.deband)):
            grid.addWidget(QLabel(label), r, 0)
            grid.addWidget(w, r, 1, 1, 2)
            r += 1
        self.low_boost = QCheckBox("Düşük kaliteli (SD/576p) yayınlarda daha güçlü iyileştir")
        self.low_boost.toggled.connect(lambda on: self._set("video", "low_boost", bool(on)))
        grid.addWidget(self.low_boost, r, 0, 1, 3)
        lay.addLayout(grid)

        btns = QHBoxLayout()
        reset = QPushButton("Sıfırla (Doğal)")
        reset.clicked.connect(lambda: self._preset("natural"))
        close = QPushButton("Kapat")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        btns.addWidget(reset)
        btns.addStretch(1)
        btns.addWidget(close)
        lay.addLayout(btns)
        self.load()

    # ------------------------------------------------------------------
    def load(self) -> None:
        self._loading = True
        pic, vid = self.settings["picture"], self.settings["video"]
        for key, s in self.sliders.items():
            s.setValue(int(pic.get(key, 0)))
            self.values[key].setText(f"{int(pic.get(key, 0)):+d}" if pic.get(key) else "0")
        for c, val in ((self.sharpen, vid.get("sharpen", "light")), (self.denoise, pic.get("denoise", "auto")),
                       (self.deband, int(pic.get("deband", 1)))):
            i = c.findData(val)
            c.setCurrentIndex(max(0, i))
        self.low_boost.setChecked(bool(vid.get("low_boost", True)))
        cur = pic.get("preset", "natural")
        for k, b in self.preset_btns.items():
            b.setChecked(k == cur)
        self.preset_note.setText("Kendi ayarınız kullanılıyor." if cur == "custom" else "")
        self._loading = False

    def _preset(self, name: str) -> None:
        opt.apply_preset(self.settings, name)
        self.load()
        self._emit_timer.start()

    def _slider(self, key: str, val: int) -> None:
        self.values[key].setText(f"{val:+d}" if val else "0")
        self._set("picture", key, int(val))

    def _set(self, section: str, key: str, val) -> None:
        if self._loading:
            return
        self.settings[section][key] = val
        self.settings["picture"]["preset"] = "custom"
        for b in self.preset_btns.values():
            b.setChecked(False)
        self.preset_note.setText("Kendi ayarınız kullanılıyor.")
        self._emit_timer.start()

    def mouseDoubleClickEvent(self, event) -> None:  # kaydırıcı üstünde çift tık: sıfırla
        w = self.childAt(event.position().toPoint())
        for s in self.sliders.values():
            if w is s:
                s.setValue(0)
        super().mouseDoubleClickEvent(event)
